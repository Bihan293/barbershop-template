from __future__ import annotations
from logging.handlers import RotatingFileHandler
from .deps import *
from .web import create_web_app
from .bot import build_application, set_bot_commands, reminder_loop
from .metrics import Metrics

def setup_file_logging(cfg: Config) -> None:
    try:
        log_path = cfg.db_path.parent / "bot.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        ))
        LOG.addHandler(handler)
        LOG.info("Лог-файл: %s", log_path)
    except Exception:
        LOG.exception("Не удалось включить файловый лог")


async def run(cfg: Config) -> int:
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(line_buffering=True)
    setup_file_logging(cfg)
    db = Database(cfg.db_path, cfg.tz, cfg.database_url)
    await db.connect()
    cfg.media_dir.mkdir(parents=True, exist_ok=True)
    (cfg.media_dir / "tmp").mkdir(parents=True, exist_ok=True)
    (cfg.media_dir / "services").mkdir(parents=True, exist_ok=True)
    (cfg.media_dir / "gallery").mkdir(parents=True, exist_ok=True)
    (cfg.media_dir / "masters").mkdir(parents=True, exist_ok=True)
    cleanup_old_temp_files(cfg)
    try:
        await cleanup_orphan_media(ctx=None, db=db, cfg=cfg, min_age_hours=24)
    except Exception:
        LOG.exception("Не удалось очистить старые фото — продолжаю запуск")

    ctx = Ctx(cfg=cfg, db=db, flows=FlowStore(), metrics=Metrics())
    web_app = create_web_app(ctx)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, cfg.host, cfg.port)
    await site.start()

    print("\n" + "=" * 60)
    print("  ЛЕЗВИЕ · барбершоп")
    print("=" * 60)
    print(f"  Сайт:    {cfg.local_base}")
    print(f"  API:     {cfg.local_base}/api/site")
    print(f"  БД:      {db.label}")
    print(f"  Медиа:   {cfg.media_dir}")
    print(f"  Режим:   {'API only' if cfg.api_only else ('webhook' if cfg.use_webhook else 'polling')}")
    if cfg.site_link and cfg.site_link != cfg.local_base:
        print(f"  Публично:{cfg.site_link}")
    if not cfg.api_only and not cfg.admin_ids:
        print("  ВНИМАНИЕ: ADMIN_IDS пуст. Напишите боту /start и добавьте ID в .env.")
    print("=" * 60 + "\n")

    tasks: list[asyncio.Task] = []
    tg_app: Optional[Application] = None

    try:
        if not cfg.api_only:
            if not cfg.bot_token:
                print("BOT_TOKEN не задан. Запустите с --api-only или заполните .env.", file=sys.stderr)
                return 1

            tg_app = build_application(ctx)
            ctx.tg_app = tg_app
            ctx.bot = tg_app.bot
            ctx.update_queue = tg_app.update_queue

            await tg_app.initialize()
            await tg_app.start()
            await set_bot_commands(ctx)

            if cfg.use_webhook:
                webhook_url = f"{cfg.public_url}/tg/webhook/{cfg.webhook_secret}"
                await ctx.bot.set_webhook(
                    url=webhook_url,
                    secret_token=cfg.webhook_secret,
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,
                )
                LOG.info("Webhook установлен: %s", webhook_url)
            else:
                await ctx.bot.delete_webhook(drop_pending_updates=False)
                await tg_app.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=False,
                )
                LOG.info("Telegram polling запущен")

            tasks.append(asyncio.create_task(reminder_loop(ctx)))
            await show_startup_notice(ctx)

        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if tg_app is not None:
            with contextlib.suppress(Exception):
                if tg_app.updater and tg_app.updater.running:
                    await tg_app.updater.stop()
            with contextlib.suppress(Exception):
                await tg_app.stop()
            with contextlib.suppress(Exception):
                await tg_app.shutdown()
        with contextlib.suppress(Exception):
            await runner.cleanup()
        await db.close()
        LOG.info("Остановлено")
    return 0


async def show_startup_notice(ctx: Ctx) -> None:
    if not ctx.admin_ids:
        return
    text = (
        "🚀 <b>Бот запущен</b>\n\n"
        f"Сайт: {esc(ctx.cfg.site_link)}\n"
        f"Режим: {'webhook' if ctx.cfg.use_webhook else 'polling'}\n\n"
        "Откройте /admin, чтобы управлять заказами, мастерами, услугами, галереей и контактами."
    )
    try:
        await send_admins(ctx, text, Kb([[Btn("⚙️ Админ-панель", callback_data="adm:home")]]))
    except Exception:
        LOG.exception("Не удалось отправить стартовое сообщение")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ЛЕЗВИЕ — Telegram-бот и сайт")
    parser.add_argument("--api-only", action="store_true", help="Запустить только сайт и API, без Telegram")
    parser.add_argument("--host", default=None, help="Хост веб-сервера (по умолчанию 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="Порт веб-сервера (по умолчанию 8080)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = build_config(args)
    try:
        return asyncio.run(run(cfg))
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
