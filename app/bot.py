from __future__ import annotations
from .deps import *
from .admin_ui import *
from .admin_text import *
from .admin_callbacks import *
from .client import *
from .master_text import handle_master_text, master_add_preview
from .admin_booking import handle_admin_booking_text
from .metrics import cmd_stats

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx: Ctx = context.application.bot_data["ctx"]
    uid = update.effective_user.id
    state = ctx.flows.state(uid)
    if state:
        if state.startswith(("svc_", "gal_", "rev_", "why_", "con_", "set_", "mst_", "ab_", "stat_")):
            if not ctx.is_admin(uid):
                ctx.flows.clear(uid)
                await update.effective_message.reply_text("Нет доступа.")
                return
            if state.startswith("mst_"):
                await handle_master_text(ctx, update, state)
            elif state.startswith("ab_"):
                if not await handle_admin_booking_text(ctx, update, state):
                    await update.effective_message.reply_text(
                        "Используйте кнопки ниже или /cancel.",
                    )
            else:
                await handle_admin_text(ctx, update, state)
            return
        if state.startswith("cl_"):
            await handle_client_text(ctx, update, state)
            return
        ctx.flows.clear(uid)
    if ctx.is_admin(uid):
        await show_admin_home_message(ctx, update.effective_message)
    else:
        await show_client_home_message(ctx, update.effective_message, uid)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx: Ctx = context.application.bot_data["ctx"]
    message = update.effective_message
    uid = update.effective_user.id
    await clear_admin_media(ctx, uid)
    state = ctx.flows.state(uid)
    data = ctx.flows.data(uid)

    if state == "cl_phone":
        await message.reply_text("Фото не нужно. Введите телефон текстом или отправьте контакт.")
        return

    if not ctx.is_admin(uid):
        await message.reply_text("Фото сейчас не требуется.")
        return

    if state == "svc_add_photo":
        relative = await download_photo(ctx, message, "tmp")
        if not relative:
            await message.reply_text("Не удалось получить фото. Попробуйте ещё раз.")
            return
        draft = data.get("draft", {})
        remove_photo(ctx, draft.get("photo_tmp", ""))
        draft["photo_tmp"] = relative
        ctx.flows.update(uid, draft=draft)
        await send_service_add_preview(ctx, message, uid)
        return

    if state == "svc_edit_photo":
        service_id = int(data.get("service_id", 0))
        relative = await download_photo(ctx, message, "tmp")
        if not relative:
            await message.reply_text("Не удалось получить фото. Попробуйте ещё раз.")
            return
        remove_photo(ctx, data.get("photo_tmp", ""))
        ctx.flows.set(uid, "svc_photo_save", service_id=service_id, photo_tmp=relative)
        path = photo_path(ctx, relative)
        if not path:
            await message.reply_text("Фото не сохранилось. Попробуйте ещё раз.")
            return
        with open(path, "rb") as photo_file:
            sent = await message.reply_photo(
                photo=photo_file,
                caption="🖼 Предпросмотр нового фото услуги",
                parse_mode=ParseMode.HTML,
            )
        register_admin_media(ctx, uid, message.chat_id, sent)
        await message.reply_text(
            "Сохранить новое фото услуги?",
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:svc_photo_save")],
                [Btn("❌ Отмена", callback_data=f"adm:svc:{service_id}")],
            ]),
        )
        return

    if state == "mst_add_photo":
        relative = await download_photo(ctx, message, "tmp")
        if not relative:
            await message.reply_text("Не удалось получить фото. Попробуйте ещё раз.")
            return
        draft = data.get("draft", {})
        remove_photo(ctx, draft.get("photo_tmp", ""))
        draft["photo_tmp"] = relative
        ctx.flows.set(uid, "mst_add_save", draft=draft)
        await send_photo_file(
            ctx,
            message.chat_id,
            relative,
            caption=f"👨‍💈 Предпросмотр · {esc(draft.get('name', ''))}",
            user_id=uid,
        )
        await message.reply_text(
            master_add_preview(draft),
            parse_mode=ParseMode.HTML,
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:mst_add_save")],
                [Btn("❌ Отмена", callback_data="adm:mst_add_cancel")],
            ]),
        )
        return

    if state == "mst_photo":
        master_id = int(data.get("master_id", 0))
        master = await ctx.db.get_master(master_id)
        relative = await download_photo(ctx, message, "tmp")
        if not relative:
            await message.reply_text("Не удалось получить фото. Попробуйте ещё раз.")
            return
        remove_photo(ctx, data.get("photo_tmp", ""))
        ctx.flows.set(uid, "mst_photo_save", master_id=master_id, photo_tmp=relative)
        await send_photo_file(
            ctx,
            message.chat_id,
            relative,
            caption=f"👨‍💈 Предпросмотр · {esc(master['name']) if master else 'мастер'}",
            user_id=uid,
        )
        await message.reply_text(
            "Сохранить это фото мастера?",
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:mst_photo_save")],
                [Btn("❌ Отмена", callback_data=f"adm:mst:{master_id}")],
            ]),
        )
        return

    if state == "gal_add_photo":
        relative = await download_photo(ctx, message, "tmp")
        if not relative:
            await message.reply_text("Не удалось получить фото. Попробуйте ещё раз.")
            return
        draft = data.get("draft", {})
        remove_photo(ctx, draft.get("photo_tmp", ""))
        draft["photo_tmp"] = relative
        ctx.flows.set(uid, "gal_add_caption", draft=draft)
        await message.reply_text(
            "Подпись к фото.\n\n"
            "Например: фото · интерьер. Можно пропустить.",
            reply_markup=Kb([
                [Btn("⏭ Пропустить", callback_data="adm:gal_skip_caption")],
                [Btn("❌ Отмена", callback_data="adm:gal_add_cancel")],
            ]),
        )
        return

    if state == "gal_edit_photo":
        item_id = int(data.get("item_id", 0))
        relative = await download_photo(ctx, message, "tmp")
        if not relative:
            await message.reply_text("Не удалось получить фото. Попробуйте ещё раз.")
            return
        remove_photo(ctx, data.get("photo_tmp", ""))
        ctx.flows.set(uid, "gal_photo_save", item_id=item_id, photo_tmp=relative)
        item = await ctx.db.get_gallery(item_id)
        path = photo_path(ctx, relative)
        if not path:
            await message.reply_text("Фото не сохранилось. Попробуйте ещё раз.")
            return
        with open(path, "rb") as photo_file:
            sent = await message.reply_photo(
                photo=photo_file,
                caption=f"🖼 Предпросмотр. Подпись: {esc(item['caption']) if item else 'без подписи'}",
                parse_mode=ParseMode.HTML,
            )
        register_admin_media(ctx, uid, message.chat_id, sent)
        await message.reply_text(
            "Сохранить новое фото в галерею?",
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:gal_photo_save")],
                [Btn("❌ Отмена", callback_data=f"adm:gal:{item_id}")],
            ]),
        )
        return

    if state in {"svc_add_photo", "svc_edit_photo", "gal_add_photo", "gal_edit_photo", "mst_add_photo", "mst_photo"}:
        await message.reply_text("Отправьте изображение или нажмите «Отмена».")
        return

    await message.reply_text("Сейчас фото не требуется. Откройте нужный раздел в /admin.")


async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx: Ctx = context.application.bot_data["ctx"]
    message = update.effective_message
    uid = update.effective_user.id
    if ctx.flows.state(uid) != "cl_phone" or not message.contact:
        await message.reply_text("Контакт сейчас не требуется.")
        return
    phone = normalize_phone(message.contact.phone_number)
    if not phone:
        await message.reply_text("Не удалось прочитать номер. Введите его вручную.")
        return
    await after_client_phone(ctx, message, uid, phone)


# ============================================================
# Команды
# ============================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx: Ctx = context.application.bot_data["ctx"]
    uid = update.effective_user.id
    if ctx.is_admin(uid):
        await clear_admin_media(ctx, uid)
        cleanup_flow_temp(ctx, uid)
    ctx.flows.clear(uid)
    if ctx.is_admin(uid):
        await show_admin_home_message(ctx, update.effective_message)
    else:
        await show_client_home_message(ctx, update.effective_message, uid)
        if not ctx.cfg.admin_ids:
            await update.effective_message.reply_text(
                f"Ваш Telegram ID: <code>{uid}</code>\n\n"
                "Администратор ещё не настроен. Добавьте этот ID в ADMIN_IDS в файле .env "
                "и перезапустите бота.",
                parse_mode=ParseMode.HTML,
            )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx: Ctx = context.application.bot_data["ctx"]
    uid = update.effective_user.id
    if ctx.is_admin(uid):
        await clear_admin_media(ctx, uid)
        cleanup_flow_temp(ctx, uid)
    ctx.flows.clear(uid)
    await show_client_home_message(ctx, update.effective_message, uid)


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx: Ctx = context.application.bot_data["ctx"]
    uid = update.effective_user.id
    if not ctx.is_admin(uid):
        await update.effective_message.reply_text(
            f"Нет доступа.\n\nВаш Telegram ID: <code>{uid}</code>\n"
            "Передайте его владельцу бота — он добавит вас в ADMIN_IDS.",
            parse_mode=ParseMode.HTML,
        )
        return
    await clear_admin_media(ctx, uid)
    cleanup_flow_temp(ctx, uid)
    ctx.flows.clear(uid)
    await show_admin_home_message(ctx, update.effective_message)


async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx: Ctx = context.application.bot_data["ctx"]
    if not ctx.is_admin(update.effective_user.id):
        await update.effective_message.reply_text("Нет доступа.")
        return
    await clear_admin_media(ctx, update.effective_user.id)
    cleanup_flow_temp(ctx, update.effective_user.id)
    text, kb = await orders_screen(ctx, "upcoming", 0)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx: Ctx = context.application.bot_data["ctx"]
    user = update.effective_user
    if ctx.is_admin(user.id):
        await clear_admin_media(ctx, user.id)
    await update.effective_message.reply_text(
        f"🆔 Ваш Telegram ID: <code>{user.id}</code>\n"
        f"Чат: <code>{update.effective_chat.id}</code>\n"
        f"Админ: {'да' if ctx.is_admin(user.id) else 'нет'}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx: Ctx = context.application.bot_data["ctx"]
    uid = update.effective_user.id
    if ctx.is_admin(uid):
        await clear_admin_media(ctx, uid)
        cleanup_flow_temp(ctx, uid)
    ctx.flows.clear(uid)
    await update.effective_message.reply_text(
        "Действие отменено.",
        reply_markup=ReplyKeyboardRemove(),
    )
    if ctx.is_admin(uid):
        await show_admin_home_message(ctx, update.effective_message)
    else:
        await show_client_home_message(ctx, update.effective_message, uid)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx: Ctx = context.application.bot_data["ctx"]
    uid = update.effective_user.id
    if ctx.is_admin(uid):
        await clear_admin_media(ctx, uid)
    text = (
        "💈 <b>Как это работает</b>\n\n"
        "Клиент: /menu → «Записаться» → услуга, мастер, дата, время, имя и телефон. "
        "Заявка мгновенно приходит администратору.\n\n"
        "Администратор: /admin — заказы, новая запись, мастера, услуги, галерея, "
        "отзывы, контакты, настройки, фото и статистика.\n\n"
        "Команды: /start, /menu, /admin, /orders, /stats, /id, /cancel."
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_site(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx: Ctx = context.application.bot_data["ctx"]
    uid = update.effective_user.id
    if ctx.is_admin(uid):
        await clear_admin_media(ctx, uid)
    site_link = public_site_link(ctx.cfg)
    if site_link:
        await update.effective_message.reply_text(
            "🌐 Сайт барбершопа:",
            reply_markup=Kb([[Btn("Открыть сайт", url=site_link)]]),
            parse_mode=ParseMode.HTML,
        )
        return
    await update.effective_message.reply_text(
        f"🌐 <b>Сайт</b>\n\n<code>{esc(ctx.cfg.site_link)}</code>\n\n"
        "Откройте в браузере телефона, пока запущен бот.",
        parse_mode=ParseMode.HTML,
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx: Ctx = context.application.bot_data["ctx"]
    q = update.callback_query
    if q is None:
        return
    data = q.data or ""
    uid = q.from_user.id

    if data.startswith("adm:"):
        if not ctx.is_admin(uid):
            await safe_answer(q, "Нет доступа", show_alert=True)
            return
        await safe_answer(q)
        await handle_admin_cb(ctx, q, data)
        return

    if data.startswith("cl:"):
        if ctx.is_admin(uid):
            await clear_admin_media(ctx, uid)
        await safe_answer(q)
        await handle_client_cb(ctx, q, data)
        return

    await safe_answer(q)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    LOG.error("Ошибка Telegram-обработчика", exc_info=context.error)
    if not isinstance(update, Update) or not update.effective_message:
        return
    text = "Что-то пошло не так. Попробуйте ещё раз или отправьте /start."
    try:
        ctx: Ctx = context.application.bot_data["ctx"]
        user = update.effective_user
        if user and ctx.is_admin(user.id):
            detail = str(context.error)[:500]
            text += f"\n\n<code>{esc(detail)}</code>"
    except Exception:
        pass
    with contextlib.suppress(Exception):
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


# ============================================================
# Сборка приложения и запуск
# ============================================================

def build_application(ctx: Ctx) -> Application:
    builder = Application.builder().token(ctx.cfg.bot_token)
    if ctx.cfg.use_webhook:
        builder = builder.updater(None)
    app = builder.build()
    app.bot_data["ctx"] = ctx

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("orders", cmd_orders))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("site", cmd_site))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.CONTACT, on_contact))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app


async def set_bot_commands(ctx: Ctx) -> None:
    default_commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("menu", "Меню записи"),
        BotCommand("site", "Открыть сайт"),
        BotCommand("id", "Мой Telegram ID"),
        BotCommand("help", "Помощь"),
    ]
    admin_commands = default_commands + [
        BotCommand("admin", "Админ-панель"),
        BotCommand("orders", "Заказы"),
        BotCommand("stats", "Статистика нагрузки"),
    ]
    try:
        await ctx.bot.set_my_commands(default_commands)
    except TelegramError as exc:
        LOG.warning("Не удалось установить общие команды: %s", exc)
    for admin_id in ctx.admin_ids:
        try:
            await ctx.bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except TelegramError as exc:
            LOG.warning("Команды для админа %s не установлены: %s", admin_id, exc)


# Проверяем не чаще раза в 30 минут, чтобы Neon успевал уходить в scale-to-zero.
# Минимальный анонс — 35 минут, поэтому напоминание всё равно придёт до визита.
REMINDER_POLL_SECONDS = 30 * 60
REMINDER_MIN_LEAD_MINUTES = REMINDER_POLL_SECONDS // 60 + 5


async def send_due_reminders(ctx: Ctx) -> int:
    """Отправляет напоминания админам и возвращает их количество."""
    settings = await ctx.db.get_settings()
    try:
        remind_minutes = int(settings.get("reminder_minutes", "120") or 120)
    except ValueError:
        remind_minutes = 120
    orders = await ctx.db.pending_reminders()
    now = datetime.now(ctx.cfg.tz)
    effective_lead = max(remind_minutes, REMINDER_MIN_LEAD_MINUTES)
    sent = 0
    for order in orders:
        try:
            start = datetime.strptime(
                f"{order['date']} {order['time']}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=ctx.cfg.tz)
        except ValueError:
            await ctx.db.mark_reminded(order["id"])
            continue
        minutes = (start - now).total_seconds() / 60
        if minutes <= 0:
            await ctx.db.mark_reminded(order["id"])
            continue
        if minutes <= effective_lead:
            text = (
                f"⏰ <b>Напоминание о записи</b>\n\n"
                f"<b>{order['time']}</b> · {esc(order['name'])}\n"
                f"{esc(order['service_name'])} · {esc(order.get('master_name') or 'любой мастер')} · {money(order['price'])}\n"
                f"📞 {esc(display_phone(order['phone']))}\n"
                f"Через ~{max(1, round(minutes))} мин"
            )
            await send_admins(
                ctx,
                text,
                Kb([[Btn("📋 Открыть заказ", callback_data=f"adm:order:{order['id']}")]]),
            )
            await ctx.db.mark_reminded(order["id"])
            sent += 1
    return sent


async def reminder_loop(ctx: Ctx) -> None:
    while True:
        try:
            await send_due_reminders(ctx)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("Ошибка в цикле напоминаний")
        await asyncio.sleep(REMINDER_POLL_SECONDS)
