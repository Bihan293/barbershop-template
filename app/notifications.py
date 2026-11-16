from __future__ import annotations
import logging
from typing import Optional
from urllib.parse import quote
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.error import TelegramError
from .core import esc, money, digits_only, phone_digits, display_phone, date_label, status_icon, status_label, channel_label
from .context import Ctx

LOG = logging.getLogger("lezvie.notify")

# ============================================================
# Уведомления и карточки заказов
# ============================================================

def order_card_text(order: dict, *, nearest: bool = False, detail: bool = False) -> str:
    heading = "🔥 <b>Ближайший заказ</b>" if nearest else "🆕 <b>Новая заявка</b>"
    if detail:
        heading = f"{status_icon(order['status'])} <b>Заказ</b>"
    lines = [
        f"{heading} <b>№{order['id']}</b> · {status_label(order['status']) if detail else 'новая'}",
        "",
        f"👤 <b>{esc(order['name'])}</b>",
        f"📞 <a href=\"tel:{phone_digits(order['phone'])}\">{esc(display_phone(order['phone']) or order['phone'])}</a>",
        f"💈 {esc(order['service_name'])} · <b>{money(order['price'])}</b> · {order['duration']} мин",
        f"👨‍💈 {esc(order.get('master_name') or 'любой мастер')}",
        f"📅 {date_label(order['date'])}, <b>{order['time']}</b>",
        f"💬 {channel_label(order['channel'])}",
    ]
    if order.get("comment"):
        lines.append(f"📝 {esc(order['comment'])}")
    source_label = {
        "site": "сайт",
        "telegram": "Telegram",
        "admin": "админ",
    }.get(str(order.get("source") or ""), str(order.get("source") or "—"))
    lines.append(f"🌐 Источник: {source_label}")
    if detail and order.get("created_at"):
        lines.append(f"🕒 Создано: {esc(order['created_at'][:16].replace('T', ' '))}")
    if detail and order.get("consent_at"):
        lines.append(f"✅ Согласие: {esc(str(order['consent_at'])[:16].replace('T', ' '))}")
    return "\n".join(lines)


def order_whatsapp_url(ctx: Ctx, order: dict) -> str:
    digits = digits_only(order["phone"])
    text = (
        f"Здравствуйте, {order['name']}! "
        f"Пишу по записи №{order['id']}: "
        f"{order['service_name']}, {date_label(order['date'])}, {order['time']}"
        + (f", мастер {order['master_name']}" if order.get("master_name") else "")
        + "."
    )
    return f"https://wa.me/{digits}?text={quote(text)}"


def order_notification_kb(ctx: Ctx, order: dict) -> Kb:
    rows = []
    if order["status"] == "new":
        rows.append([
            Btn("✅ Подтвердить", callback_data=f"adm:ostatus:{order['id']}:confirm"),
            Btn("❌ Отменить", callback_data=f"adm:ostatus:{order['id']}:cancel"),
        ])
    elif order["status"] == "confirmed":
        rows.append([
            Btn("🏁 Завершить", callback_data=f"adm:ostatus:{order['id']}:done"),
            Btn("❌ Отменить", callback_data=f"adm:ostatus:{order['id']}:cancel"),
        ])
    rows.append([
        Btn("💬 WhatsApp", url=order_whatsapp_url(ctx, order)),
        Btn("📋 Детали", callback_data=f"adm:order:{order['id']}"),
    ])
    return Kb(rows)


async def send_admins(ctx: Ctx, text: str, kb: Optional[Kb] = None) -> None:
    if ctx.bot is None:
        LOG.info("Telegram не запущен, уведомление не отправлено")
        return
    if not ctx.admin_ids:
        LOG.warning("ADMIN_IDS не задан — уведомление не отправлено")
        return
    for admin_id in ctx.admin_ids:
        try:
            await ctx.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except TelegramError as exc:
            LOG.warning("Не удалось отправить уведомление %s: %s", admin_id, exc)


async def notify_new_order(ctx: Ctx, order: dict) -> None:
    nearest = await ctx.db.nearest_order()
    is_nearest = bool(nearest and nearest["id"] == order["id"])
    text = order_card_text(order, nearest=is_nearest)
    await send_admins(ctx, text, order_notification_kb(ctx, order))


async def notify_client(
    ctx: Ctx,
    order: dict,
    text: str,
    kb: Optional[Kb] = None,
) -> bool:
    if ctx.bot is None or not order.get("tg_id"):
        return False
    try:
        await ctx.bot.send_message(
            chat_id=int(order["tg_id"]),
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return True
    except TelegramError as exc:
        LOG.warning("Не удалось написать клиенту %s: %s", order["tg_id"], exc)
        return False
