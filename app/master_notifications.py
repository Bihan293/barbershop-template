from __future__ import annotations
from .deps import *


async def notify_master_orders(
    ctx: Ctx,
    master: dict,
    orders: list[dict],
    reason: str,
) -> int:
    """Сообщает клиентам и админу, что мастер не сможет принять записи."""
    if not orders:
        return 0
    settings = await ctx.db.get_settings()
    phone = settings.get("phone", "")
    name = esc(master.get("name", "Мастер"))
    reason_text = esc(reason)
    sent = 0
    failed = 0

    for order in orders:
        if not order.get("tg_id"):
            continue
        text = (
            "⚠️ <b>Изменение записи</b>\n\n"
            f"Мастер <b>{name}</b> {reason_text}.\n"
            f"Ваша запись: {esc(order['service_name'])} · "
            f"{date_label(order['date'])}, <b>{order['time']}</b>.\n\n"
            "Перенесите или отмените запись в «Моих записях» или позвоните в салон"
            + (f": <b>{esc(phone)}</b>" if phone else ".")
        )
        ok = await notify_client(
            ctx,
            order,
            text,
            Kb([[Btn("🗂 Мои записи", callback_data="cl:my")]]),
        )
        if ok:
            sent += 1
        else:
            failed += 1

    lines = [
        "⚠️ <b>Изменение у мастера</b>",
        "",
        f"👨‍💈 <b>{name}</b>",
        f"Причина: {reason_text}",
        f"Затронуто записей: <b>{len(orders)}</b>",
        "",
    ]
    for order in orders[:10]:
        source = {"site": "сайт", "telegram": "Telegram", "admin": "админ"}.get(
            str(order.get("source") or ""), str(order.get("source") or "")
        )
        lines.append(
            f"• {date_label(order['date'])}, {order['time']} · "
            f"{esc(order['name'])} · {esc(display_phone(order['phone']))} · "
            f"{esc(order['service_name'])} · {source}"
        )
    if len(orders) > 10:
        lines.append(f"…и ещё {len(orders) - 10}")
    lines.append("")
    if failed:
        lines.append(f"⚠️ Не удалось отправить Telegram-уведомлений: {failed}.")
    site_orders = [order for order in orders if not order.get("tg_id")]
    if site_orders:
        lines.append(
            f"⚠️ Клиентов с сайта/ручной записи: {len(site_orders)} — "
            "свяжитесь с ними вручную или перенесите запись."
        )
    telegram_count = sum(1 for order in orders if order.get("tg_id"))
    if telegram_count:
        lines.append(
            f"Telegram-клиентов: {telegram_count} — им отправлено сообщение, "
            "они могут перенести запись в «Моих записях»."
        )
    else:
        lines.append("Среди затронутых записей нет Telegram-клиентов.")

    await send_admins(
        ctx,
        "\n".join(lines),
        Kb([[Btn("📥 Открыть заказы", callback_data="adm:orders:upcoming:0")]]),
    )
    return sent
