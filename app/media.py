from __future__ import annotations
import contextlib
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from telegram import InlineKeyboardMarkup as Kb, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.error import TelegramError
from .context import Ctx
from .core import Config

LOG = logging.getLogger("lezvie.media")

def photo_path(ctx: Ctx, relative: str) -> Optional[Path]:
    if not relative:
        return None
    path = ctx.cfg.media_dir / relative
    return path if path.exists() else None


async def download_photo(ctx: Ctx, message, subdir: str = "tmp") -> Optional[str]:
    suffix = ".jpg"
    if message.photo:
        tg_file = await message.photo[-1].get_file()
    elif message.document and str(message.document.mime_type or "").startswith("image/"):
        tg_file = await message.document.get_file()
        suffix = Path(message.document.file_name or "").suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            suffix = ".jpg"
    else:
        return None
    name = f"{uuid.uuid4().hex}{suffix}"
    relative = f"{subdir}/{name}"
    path = ctx.cfg.media_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    await tg_file.download_to_drive(custom_path=str(path))
    return relative


def move_photo(ctx: Ctx, temp_relative: str, subdir: str) -> str:
    if not temp_relative:
        return ""
    source = ctx.cfg.media_dir / temp_relative
    if not source.exists():
        return ""
    suffix = source.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = ".jpg"
    name = f"{uuid.uuid4().hex}{suffix}"
    target = ctx.cfg.media_dir / subdir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return f"{subdir}/{name}"


def cleanup_old_temp_files(cfg: Config) -> None:
    folder = cfg.media_dir / "tmp"
    if not folder.exists():
        return
    cutoff = time.time() - 24 * 3600
    for file in folder.iterdir():
        try:
            if file.is_file() and file.stat().st_mtime < cutoff:
                file.unlink()
        except OSError:
            pass


def remove_photo(ctx: Ctx, relative: str) -> None:
    if not relative:
        return
    path = ctx.cfg.media_dir / relative
    with contextlib.suppress(FileNotFoundError):
        if path.is_file():
            path.unlink()


def register_admin_media(ctx: Ctx, user_id: int, chat_id: int, sent: Any) -> None:
    if sent is None:
        return
    message_id = getattr(sent, "message_id", None)
    if message_id:
        ctx.media_messages[user_id] = (chat_id, int(message_id))


async def clear_admin_media(ctx: Ctx, user_id: int) -> None:
    """Удаляет предыдущее фото админ-экрана, чтобы оно не копилось в чате."""
    info = ctx.media_messages.pop(user_id, None)
    if not info or ctx.bot is None:
        return
    chat_id, message_id = info
    with contextlib.suppress(TelegramError):
        await ctx.bot.delete_message(chat_id=chat_id, message_id=message_id)


async def send_photo_file(
    ctx: Ctx,
    chat_id: int,
    relative: str,
    caption: str = "",
    user_id: Optional[int] = None,
    reply_markup: Optional[Kb] = None,
) -> bool:
    path = photo_path(ctx, relative)
    if not path or ctx.bot is None:
        return False
    if user_id is not None:
        await clear_admin_media(ctx, user_id)
    try:
        with open(path, "rb") as photo_file:
            sent = await ctx.bot.send_photo(
                chat_id=chat_id,
                photo=photo_file,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        if user_id is not None and sent is not None:
            message_id = getattr(sent, "message_id", None)
            if message_id:
                ctx.media_messages[user_id] = (chat_id, int(message_id))
        return True
    except TelegramError as exc:
        LOG.warning("send_photo_file: %s", exc)
        return False


async def replace_admin_screen(
    ctx: Ctx,
    q,
    text: str,
    kb: Optional[Kb] = None,
    *,
    photo_rel: str = "",
    caption: str = "",
    photo_caption: str = "",
    user_id: Optional[int] = None,
) -> None:
    """Удаляет старый экран и присылает новый: фото сверху, кнопки снизу."""
    chat_id = q.message.chat_id
    await clear_admin_media(ctx, user_id or q.from_user.id)
    deleter = getattr(q.message, "delete", None)
    if deleter is not None:
        with contextlib.suppress(TelegramError):
            await deleter()
    if photo_rel:
        # Если полный текст помещается в подпись — прикрепляем кнопки
        # прямо к фото, чтобы они не терялись отдельным сообщением.
        if photo_caption and len(photo_caption) <= 900 and kb is not None:
            sent = await send_photo_file(
                ctx,
                chat_id,
                photo_rel,
                photo_caption,
                user_id=user_id or q.from_user.id,
                reply_markup=kb,
            )
            if sent:
                return
        await send_photo_file(
            ctx, chat_id, photo_rel, caption, user_id=user_id or q.from_user.id
        )
    if ctx.bot is None:
        return
    await ctx.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def media_inventory(cfg: Config) -> dict[str, dict[str, int]]:
    inventory: dict[str, dict[str, int]] = {}
    for folder_name in ("services", "gallery", "masters", "tmp"):
        folder = cfg.media_dir / folder_name
        files = 0
        total = 0
        if folder.exists():
            for path in folder.rglob("*"):
                if path.is_file():
                    try:
                        total += path.stat().st_size
                        files += 1
                    except OSError:
                        pass
        inventory[folder_name] = {"files": files, "bytes": total}
    return inventory


def format_bytes(value: int) -> str:
    size = float(value or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ГБ"


async def cleanup_orphan_media(
    ctx: Ctx | None = None,
    *,
    db: Any = None,
    cfg: Config | None = None,
    min_age_hours: float = 24,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Удаляет файлы, на которые не ссылается база.

    Свежие файлы (моложе min_age_hours) не трогаем: они могут быть
    загружены в диалоге и ещё не сохранены в БД.
    """
    database = db or (ctx.db if ctx else None)
    config = cfg or (ctx.cfg if ctx else None)
    if database is None or config is None:
        raise ValueError("cleanup_orphan_media: нужны db и cfg")

    references = await database.media_references()
    cutoff = time.time() - max(0.0, float(min_age_hours)) * 3600
    removed = 0
    removed_bytes = 0
    kept = 0
    skipped_new = 0
    folders = ("services", "gallery", "masters")

    for folder_name in folders:
        folder = config.media_dir / folder_name
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(config.media_dir).as_posix()
            if relative in references:
                kept += 1
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime >= cutoff:
                skipped_new += 1
                continue
            if not dry_run:
                try:
                    path.unlink()
                except OSError:
                    continue
            removed += 1
            removed_bytes += stat.st_size

    result = {
        "removed": removed,
        "bytes": removed_bytes,
        "kept": kept,
        "skipped_new": skipped_new,
        "references": len(references),
        "dry_run": dry_run,
    }
    LOG.info(
        "Очистка фото%s: удалено %s (%s), занято %s, свежих пропущено %s",
        " (проверка)" if dry_run else "",
        removed,
        format_bytes(removed_bytes),
        kept,
        skipped_new,
    )
    return result

