from __future__ import annotations
from .deps import *

# ============================================================
# Админ-панель
# ============================================================

async def admin_home_text(ctx: Ctx) -> str:
    settings = await ctx.db.get_settings()
    stats = await ctx.db.today_stats()
    nearest = await ctx.db.nearest_order()
    new_row = await ctx.db.fetchone("SELECT COUNT(*) AS c FROM orders WHERE status='new'")
    new_count = int(new_row["c"]) if new_row else 0
    master_row = await ctx.db.fetchone("SELECT COUNT(*) AS c FROM masters WHERE active=1")
    master_count = int(master_row["c"]) if master_row else 0

    lines = [
        "⚙️ <b>Админ-панель</b>",
        f"{esc(settings.get('brand', 'ЛЕЗВИЕ'))} · {esc(settings.get('city', 'Алматы'))}",
        "",
        f"📅 Сегодня: <b>{stats['count']}</b> записей · <b>{money(stats['total'])}</b>",
        f"🆕 Новых заявок: <b>{new_count}</b> · 👨‍💈 Мастеров: <b>{master_count}</b>",
        "",
    ]
    if nearest:
        lines += [
            "🔥 <b>Ближайший заказ</b>",
            f"{short_date_label(nearest['date'], ctx.cfg.tz)}, <b>{nearest['time']}</b> · {esc(nearest['name'])}",
            f"{esc(nearest['service_name'])} · {money(nearest['price'])} · {esc(nearest['phone'])}",
        ]
    else:
        lines.append("Ближайших записей пока нет.")
    if master_count == 0:
        lines += ["", "⚠️ <b>Нет активных мастеров</b> — онлайн-запись не работает. Откройте «Мастера» и включите хотя бы одного."]
    elif settings.get("booking_enabled", "1") != "1":
        lines += ["", "⚠️ <b>Онлайн-запись выключена</b> — включите её в «Настройках», когда будете готовы."]
    lines += ["", "Выберите раздел — всё редактируется прямо здесь."]
    return "\n".join(lines)


async def admin_home_kb(ctx: Ctx) -> Kb:
    rows = [
        [Btn("📥 Заказы", callback_data="adm:orders:upcoming:0"),
         Btn("🆕 Новые", callback_data="adm:orders:new:0")],
        [Btn("➕ Новая запись", callback_data="adm:ab_start")],
        [Btn("💈 Услуги", callback_data="adm:services"),
         Btn("🖼 Галерея", callback_data="adm:gallery")],
        [Btn("👨‍💈 Мастера", callback_data="adm:masters"),
         Btn("🧹 Фото", callback_data="adm:media")],
        [Btn("⭐ Отзывы", callback_data="adm:reviews"),
         Btn("📍 Контакты", callback_data="adm:contacts")],
        [Btn("💡 Почему мы", callback_data="adm:whys"),
         Btn("🏷 Имя заведения", callback_data="adm:con_edit:brand")],
        [Btn("⚙️ Настройки", callback_data="adm:settings"),
         Btn("📈 Нагрузка", callback_data="adm:stats")],
        [Btn("🏆 Цифры и достижения", callback_data="adm:site_stats")],
    ]
    site_link = public_site_link(ctx.cfg)
    if site_link:
        rows.append([Btn("🌐 Открыть сайт", url=site_link)])
    else:
        rows.append([Btn("🌐 Адрес сайта", callback_data="adm:site")])
    rows.append([Btn("👤 Клиентское меню", callback_data="cl:menu")])
    return Kb(rows)


async def show_admin_home_message(ctx: Ctx, message) -> None:
    await clear_admin_media(ctx, message.chat_id)
    await message.reply_text(
        await admin_home_text(ctx),
        parse_mode=ParseMode.HTML,
        reply_markup=await admin_home_kb(ctx),
    )


async def show_admin_home_q(ctx: Ctx, q) -> None:
    await clear_admin_media(ctx, q.from_user.id)
    await edit_q(q, await admin_home_text(ctx), await admin_home_kb(ctx))


# ---------- заказы ----------

ORDERS_FILTERS = {
    "upcoming": "Актуальные",
    "new": "Новые",
    "today": "Сегодня",
    "all": "Все активные",
    "archive": "Архив",
}


async def orders_screen(ctx: Ctx, filter_name: str = "upcoming", page: int = 0) -> tuple[str, Kb]:
    if filter_name not in ORDERS_FILTERS:
        filter_name = "upcoming"
    page = max(0, page)
    limit = 7
    orders = await ctx.db.list_orders(filter_name, limit + 1, page * limit)
    has_more = len(orders) > limit
    orders = orders[:limit]
    nearest = None if filter_name == "archive" else await ctx.db.nearest_order()

    lines = [f"📥 <b>Заказы</b> · {ORDERS_FILTERS[filter_name]} · стр. {page + 1}"]
    if nearest:
        lines += [
            "",
            "🔥 <b>Ближайший</b>",
            f"<b>{nearest['time']}</b> · {short_date_label(nearest['date'], ctx.cfg.tz)} · {esc(nearest['name'])}",
            f"{esc(nearest['service_name'])} · {esc(nearest.get('master_name') or 'любой мастер')} · {money(nearest['price'])}",
            f"📞 {esc(display_phone(nearest['phone']))}",
        ]

    lines += ["", "<b>Список</b>" if orders else "Заказов пока нет."]
    for order in orders:
        lines.append(
            f"{status_icon(order['status'])} <b>{order['time']}</b> · "
            f"{short_date_label(order['date'], ctx.cfg.tz)} · {esc(order['name'])} · "
            f"{esc(order['service_name'])} · {esc(order.get('master_name') or '—')} · {money(order['price'])}"
        )

    rows: list[list[Btn]] = []
    if nearest:
        rows.append([Btn("🔥 Открыть ближайший", callback_data=f"adm:order:{nearest['id']}")])
    for order in orders:
        rows.append([
            Btn(
                f"{status_icon(order['status'])} {order['time']} · {order['name'][:9]} · "
                f"{(order.get('master_name') or '—')[:7]}",
                callback_data=f"adm:order:{order['id']}",
            )
        ])

    rows.append([
        Btn("Актуальные", callback_data="adm:orders:upcoming:0"),
        Btn("Новые", callback_data="adm:orders:new:0"),
    ])
    rows.append([
        Btn("Сегодня", callback_data="adm:orders:today:0"),
        Btn("Все", callback_data="adm:orders:all:0"),
        Btn("Архив", callback_data="adm:orders:archive:0"),
    ])
    rows.append([Btn("➕ Новая запись", callback_data="adm:ab_start")])

    nav = []
    if page > 0:
        nav.append(Btn("← Назад", callback_data=f"adm:orders:{filter_name}:{page - 1}"))
    if has_more:
        nav.append(Btn("Вперёд →", callback_data=f"adm:orders:{filter_name}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([Btn("← В админ-панель", callback_data="adm:home")])
    return "\n".join(lines), Kb(rows)


def order_detail_kb(ctx: Ctx, order: dict) -> Kb:
    rows: list[list[Btn]] = []
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
    if order["status"] in {"new", "confirmed"}:
        rows.append([Btn("📅 Перенести", callback_data=f"adm:move:{order['id']}")])
    rows.append([
        Btn("💬 WhatsApp", url=order_whatsapp_url(ctx, order)),
    ])
    if order.get("tg_id"):
        rows.append([Btn("👤 Telegram", url=f"tg://user?id={order['tg_id']}")])
    rows.append([Btn("← К заказам", callback_data="adm:orders:upcoming:0")])
    return Kb(rows)


async def order_detail_screen(ctx: Ctx, order_id: int) -> tuple[str, Kb]:
    order = await ctx.db.get_order(order_id)
    if not order:
        return "Заказ не найден.", Kb([[Btn("← К заказам", callback_data="adm:orders:upcoming:0")]])
    text = order_card_text(order, detail=True)
    services = await ctx.db.get_order_services(order_id)
    if len(services) > 1:
        text += "\n\n<b>Услуги в записи</b>"
        for item in services:
            text += f"\n• {esc(item['service_name'])} · {money(item['price'])} · {item['duration']} мин"
    return text, order_detail_kb(ctx, order)


ORDER_ACTIONS = {
    "confirm": ("подтвердить", "confirmed"),
    "cancel": ("отменить", "cancelled"),
    "done": ("завершить", "completed"),
}
ORDER_ALLOWED = {
    "confirm": {"new"},
    "cancel": {"new", "confirmed"},
    "done": {"confirmed"},
}


async def ask_order_status(ctx: Ctx, order_id: int, action: str) -> tuple[str, Kb]:
    order = await ctx.db.get_order(order_id)
    if not order or action not in ORDER_ACTIONS:
        return "Заказ не найден.", Kb([[Btn("← К заказам", callback_data="adm:orders:upcoming:0")]])
    if order["status"] not in ORDER_ALLOWED.get(action, set()):
        return (
            f"Статус заказа №{order['id']} уже изменился: {status_label(order['status'])}.",
            Kb([[Btn("← К заказу", callback_data=f"adm:order:{order['id']}")]]),
        )
    verb, _ = ORDER_ACTIONS[action]
    text = (
        f"Подтвердите действие\n\n"
        f"<b>{verb.capitalize()} заказ №{order['id']}?</b>\n"
        f"{esc(order['name'])} · {short_date_label(order['date'], ctx.cfg.tz)}, {order['time']}\n"
        f"{esc(order['service_name'])} · {esc(order.get('master_name') or 'любой мастер')} · {money(order['price'])}"
    )
    if action == "cancel" and not order.get("tg_id"):
        if order.get("source") == "admin":
            text += (
                "\n\n⚠️ Запись создана вручную — Telegram-уведомление клиенту не уйдёт. "
                "После отмены позвоните ему или напишите в WhatsApp."
            )
        else:
            text += (
                "\n\n⚠️ Клиент записался через сайт — Telegram-уведомление не уйдёт. "
                "После отмены напишите ему в WhatsApp или позвоните."
            )
    kb = Kb([
        [Btn("✅ Да", callback_data=f"adm:ostatusok:{order_id}:{action}")],
        [Btn("← Нет, назад", callback_data=f"adm:order:{order_id}")],
    ])
    return text, kb


async def apply_order_status(ctx: Ctx, order_id: int, action: str) -> Optional[dict]:
    if action not in ORDER_ACTIONS:
        return None
    status = ORDER_ACTIONS[action][1]
    order = await ctx.db.get_order(order_id)
    if not order:
        return None
    if order["status"] not in ORDER_ALLOWED.get(action, set()):
        return None
    updated = await ctx.db.set_order_status(
        order_id,
        status,
        allowed_from=ORDER_ALLOWED.get(action),
    )
    if not updated:
        return None

    settings = await ctx.db.get_settings()
    address = settings.get("address", "")
    phone = settings.get("phone", "")
    if status == "confirmed":
        text = (
            f"✅ <b>Запись подтверждена</b>\n\n"
            f"{esc(updated['service_name'])} · {esc(updated.get('master_name') or 'любой мастер')}\n"
            f"{date_label(updated['date'])}, <b>{updated['time']}</b>\n"
            f"{esc(address)}\n"
            f"Если планы изменятся — позвоните: {esc(phone)}"
        )
    elif status == "cancelled":
        text = (
            f"❌ <b>Запись отменена</b>\n\n"
            f"{esc(updated['service_name'])} · {esc(updated.get('master_name') or 'любой мастер')}\n"
            f"{date_label(updated['date'])}, {updated['time']}\n"
            f"Если это ошибка — позвоните: {esc(phone)}"
        )
    else:
        text = (
            "🏁 <b>Визит завершён</b>\n\n"
            f"Спасибо, что выбрали {esc(settings.get('brand', 'салон'))}. Будем рады видеть снова!"
        )
    notified = await notify_client(ctx, updated, text)
    updated["client_notified"] = notified
    return updated


async def admin_move_dates_screen(ctx: Ctx, q, order_id: int) -> None:
    order = await ctx.db.get_order(order_id)
    if not order or order["status"] not in {"new", "confirmed"}:
        await edit_q(
            q,
            "Перенести можно только новый или подтверждённый заказ.",
            Kb([[Btn("← К заказу", callback_data=f"adm:order:{order_id}")]]),
        )
        return
    today = datetime.now(ctx.cfg.tz).date()
    rows: list[list[Btn]] = []
    pair: list[Btn] = []
    for offset in range(30):
        day = (today + timedelta(days=offset)).isoformat()
        pair.append(Btn(move_day_label(day, ctx.cfg.tz), callback_data=f"adm:move_date:{order_id}:{day}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([Btn("← К заказу", callback_data=f"adm:order:{order_id}")])
    text = (
        f"📅 <b>Перенести заказ №{order['id']}</b>\n\n"
        f"Сейчас: <b>{date_label(order['date'])}, {order['time']}</b>\n"
        f"{esc(order['service_name'])} · {esc(order.get('master_name') or 'любой мастер')} · {order['duration']} мин\n\n"
        "Выберите новую дату:"
    )
    await edit_q(q, text, Kb(rows))


async def order_move_master_id(ctx: Ctx, order: dict) -> Optional[int]:
    """Если мастер отключён/удалён, разрешаем перенос к любому свободному."""
    try:
        master_id = int(order.get("master_id")) if order.get("master_id") is not None else None
    except (TypeError, ValueError):
        master_id = None
    if not master_id:
        return None
    master = await ctx.db.get_master(master_id)
    if not master or not int(master.get("active") or 0):
        return None
    return master_id


async def admin_move_times_screen(ctx: Ctx, q, order_id: int, day: str) -> None:
    order = await ctx.db.get_order(order_id)
    iso_day = valid_iso_date(day)
    if not order or not iso_day or order["status"] not in {"new", "confirmed"}:
        await edit_q(q, "Заказ или дата не найдены.", Kb([[Btn("← К заказу", callback_data=f"adm:order:{order_id}")]]))
        return
    move_master_id = await order_move_master_id(ctx, order)
    slots = await ctx.db.available_slots(
        iso_day,
        int(order["duration"] or 30),
        exclude_order_id=order_id,
        master_id=move_master_id,
    )
    master_label = esc(order.get("master_name")) if move_master_id else "любой свободный"
    settings = await ctx.db.get_settings()
    text = (
        f"🕘 <b>Новое время · заказ №{order['id']}</b>\n\n"
        f"Сейчас: {date_label(order['date'])}, {order['time']}\n"
        f"Новая дата: <b>{date_label(iso_day)}</b>\n"
        f"{esc(order['service_name'])} · {master_label} · {order['duration']} мин\n\n"
    )
    if (
        slots
        and iso_day == datetime.now(ctx.cfg.tz).date().isoformat()
        and slots[0] > settings.get("work_start", "10:00")
    ):
        text += (
            f"⚠️ Сегодня доступны слоты с <b>{slots[0]}</b> — "
            "более раннее время уже прошло.\n\n"
        )
    if not slots:
        text += "На эту дату свободных слотов нет. Выберите другую дату."
        rows = [[Btn("📅 Другая дата", callback_data=f"adm:move:{order_id}")]]
        rows.append([Btn("← К заказу", callback_data=f"adm:order:{order_id}")])
        await edit_q(q, text, Kb(rows))
        return
    text += "Выберите новое время:"
    rows = []
    row: list[Btn] = []
    for slot in slots:
        row.append(Btn(slot, callback_data=f"adm:move_time:{order_id}:{iso_day}:{slot}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([Btn("📅 Другая дата", callback_data=f"adm:move:{order_id}")])
    rows.append([Btn("← К заказу", callback_data=f"adm:order:{order_id}")])
    await edit_q(q, text, Kb(rows))


async def admin_move_confirm_screen(ctx: Ctx, q, order_id: int, day: str, slot: str) -> None:
    order = await ctx.db.get_order(order_id)
    iso_day = valid_iso_date(day)
    valid_slot = valid_time(slot)
    if not order or not iso_day or not valid_slot or order["status"] not in {"new", "confirmed"}:
        await edit_q(q, "Заказ или время не найдены.", Kb([[Btn("← К заказу", callback_data=f"adm:order:{order_id}")]]))
        return
    move_master_id = await order_move_master_id(ctx, order)
    slots = await ctx.db.available_slots(
        iso_day,
        int(order["duration"] or 30),
        exclude_order_id=order_id,
        master_id=move_master_id,
    )
    if valid_slot not in slots:
        await admin_move_times_screen(ctx, q, order_id, iso_day)
        return
    text = (
        f"📅 <b>Подтвердите перенос</b>\n\n"
        f"Заказ №{order['id']} · {esc(order['service_name'])} · "
        f"{esc(order.get('master_name')) if move_master_id else 'любой свободный'}\n"
        f"Было: {date_label(order['date'])}, <b>{order['time']}</b>\n"
        f"Станет: {date_label(iso_day)}, <b>{valid_slot}</b>\n\n"
        f"👤 {esc(order['name'])} · 📞 {esc(display_phone(order['phone']))}"
    )
    if not order.get("tg_id"):
        text += "\n\n⚠️ Клиент записан через сайт — после переноса сообщите ему."
    rows = [
        [Btn("✅ Перенести", callback_data=f"adm:move_ok:{order_id}:{iso_day}:{valid_slot}")],
        [Btn("← Нет, назад", callback_data=f"adm:order:{order_id}")],
    ]
    await edit_q(q, text, Kb(rows))


async def apply_admin_move(ctx: Ctx, q, order_id: int, day: str, slot: str) -> None:
    order = await ctx.db.get_order(order_id)
    if not order:
        await safe_answer(q, "Заказ не найден", show_alert=True)
        return
    old_label = f"{date_label(order['date'])}, {order['time']}"
    updated, error = await ctx.db.reschedule_order(order_id, day, slot)
    if error or not updated:
        await safe_answer(q, error or "Не удалось перенести", show_alert=True)
        await admin_move_times_screen(ctx, q, order_id, day)
        return
    settings = await ctx.db.get_settings()
    phone = settings.get("phone", "")
    heading = "Заявка перенесена" if updated["status"] == "new" else "Запись перенесена"
    client_text = (
        f"📅 <b>{heading}</b>\n\n"
        f"Было: {old_label}\n"
        f"Стало: <b>{date_label(updated['date'])}, {updated['time']}</b>\n"
        f"{esc(updated['service_name'])} · {esc(updated.get('master_name') or 'любой мастер')} · {money(updated['price'])}\n\n"
        + ("Мастер подтвердит новое время.\n\n" if updated["status"] == "new" else "")
        + f"Если время не подходит — позвоните: {esc(phone)}"
    )
    notified = await notify_client(ctx, updated, client_text)
    detail, kb = await order_detail_screen(ctx, order_id)
    suffix = "\n\n✅ Заказ перенесён."
    if updated.get("master_id") != order.get("master_id") and updated.get("master_name"):
        suffix += f" Назначен мастер: <b>{esc(updated['master_name'])}</b>."
    if notified:
        suffix += " Клиент получил уведомление в Telegram."
    elif updated.get("tg_id"):
        suffix += (
            " ⚠️ Не удалось отправить уведомление клиенту. "
            f"Напишите ему: {esc(display_phone(updated['phone']))}"
        )
    else:
        if updated.get("source") == "admin":
            suffix += (
                "\n\n⚠️ <b>Запись создана вручную — сообщите клиенту о переносе.</b>"
                f"\n📞 <b>{esc(display_phone(updated['phone']))}</b>"
            )
        else:
            suffix += (
                "\n\n⚠️ <b>Клиент записался через сайт — сообщите ему о переносе.</b>"
                f"\n📞 <b>{esc(display_phone(updated['phone']))}</b>"
            )
    await edit_q(q, detail + suffix, kb)



# ---------- услуги ----------

async def services_screen(ctx: Ctx) -> tuple[str, Kb]:
    services = await ctx.db.list_services()
    lines = ["💈 <b>Услуги</b>", f"Всего: {len(services)}", ""]
    for service in services:
        lines.append(
            f"<b>{esc(service['name'])}</b> · {money(service['price'])} · {service['duration']} мин"
        )
    if not services:
        lines.append("Услуг пока нет — добавьте первую.")
    rows: list[list[Btn]] = []
    for service in services:
        rows.append([
            Btn(
                f"💈 {service['name'][:14]} · {money(service['price'])}",
                callback_data=f"adm:svc:{service['id']}",
            )
        ])
    rows.append([Btn("➕ Добавить услугу", callback_data="adm:svc_add")])
    rows.append([Btn("← В админ-панель", callback_data="adm:home")])
    return "\n".join(lines), Kb(rows)


def service_text(service: dict) -> str:
    return (
        f"💈 <b>{esc(service['name'])}</b>\n\n"
        f"{esc(service['description']) or 'Без описания'}\n\n"
        f"💰 <b>{money(service['price'])}</b> · ⏱ {service['duration']} мин\n"
        f"🖼 Фото: {'есть' if service.get('photo') else 'нет'}"
    )


def service_kb(service: dict) -> Kb:
    sid = service["id"]
    rows = [
        [Btn("✏️ Название", callback_data=f"adm:svc_edit:{sid}:name"),
         Btn("📝 Описание", callback_data=f"adm:svc_edit:{sid}:description")],
        [Btn("💰 Цена", callback_data=f"adm:svc_edit:{sid}:price"),
         Btn("⏱ Длительность", callback_data=f"adm:svc_edit:{sid}:duration")],
        [Btn("🖼 Фото", callback_data=f"adm:svc_edit:{sid}:photo")],
    ]
    if service.get("photo"):
        rows.append([Btn("🗑 Удалить фото", callback_data=f"adm:svc_photo_del:{sid}")])
    rows += [
        [Btn("🗑 Удалить услугу", callback_data=f"adm:svc_del:{sid}")],
        [Btn("← К услугам", callback_data="adm:services")],
    ]
    return Kb(rows)


async def show_service_detail(ctx: Ctx, q, service_id: int) -> None:
    service = await ctx.db.get_service(service_id)
    if not service:
        await edit_q(q, "Услуга не найдена.", Kb([[Btn("← К услугам", callback_data="adm:services")]]))
        return
    await replace_admin_screen(
        ctx,
        q,
        service_text(service),
        service_kb(service),
        photo_rel=service.get("photo", ""),
        caption=f"{esc(service['name'])} · {money(service['price'])}",
        photo_caption=service_text(service),
        user_id=q.from_user.id,
    )


# ---------- галерея ----------

async def gallery_screen(ctx: Ctx) -> tuple[str, Kb]:
    items = await ctx.db.list_gallery()
    lines = ["🖼 <b>Галерея</b>", f"Всего: {len(items)}", ""]
    for index, item in enumerate(items, start=1):
        line = f"{index:02d} · {esc(item['caption']) or 'без подписи'}"
        if not item.get("image"):
            line += " · <i>без фото</i>"
        lines.append(line)
    if not items:
        lines.append("Галерея пуста.")
    rows: list[list[Btn]] = []
    for index, item in enumerate(items, start=1):
        rows.append([
            Btn(
                f"{index:02d} · {item['caption'][:20] or 'без подписи'}",
                callback_data=f"adm:gal:{item['id']}",
            )
        ])
    rows.append([Btn("➕ Добавить фото", callback_data="adm:gal_add")])
    rows.append([Btn("← В админ-панель", callback_data="adm:home")])
    return "\n".join(lines), Kb(rows)


def gallery_text(item: dict) -> str:
    return (
        f"🖼 <b>Фото №{item['id']}</b>\n\n"
        f"Подпись: {esc(item['caption']) or 'без подписи'}\n"
        f"Изображение: {'загружено' if item.get('image') else 'нет'}"
    )


def gallery_kb(item: dict) -> Kb:
    iid = item["id"]
    rows = [
        [Btn("✏️ Подпись", callback_data=f"adm:gal_caption:{iid}"),
         Btn("🖼 Заменить фото", callback_data=f"adm:gal_photo:{iid}")],
    ]
    if item.get("image"):
        rows.append([Btn("🗑 Удалить фото", callback_data=f"adm:gal_photo_del:{iid}")])
    rows += [
        [Btn("🗑 Удалить карточку", callback_data=f"adm:gal_del:{iid}")],
        [Btn("← К галерее", callback_data="adm:gallery")],
    ]
    return Kb(rows)


async def show_gallery_detail(ctx: Ctx, q, item_id: int) -> None:
    item = await ctx.db.get_gallery(item_id)
    if not item:
        await edit_q(q, "Фото не найдено.", Kb([[Btn("← К галерее", callback_data="adm:gallery")]]))
        return
    await replace_admin_screen(
        ctx,
        q,
        gallery_text(item),
        gallery_kb(item),
        photo_rel=item.get("image", ""),
        caption=esc(item["caption"]) or "Без подписи",
        photo_caption=gallery_text(item),
        user_id=q.from_user.id,
    )


# ---------- отзывы ----------

async def reviews_screen(ctx: Ctx) -> tuple[str, Kb]:
    reviews = await ctx.db.list_reviews()
    lines = ["⭐ <b>Отзывы</b>", f"Всего: {len(reviews)}", ""]
    for review in reviews:
        lines.append(
            f"{'★' * int(review['rating'])}{'☆' * (5 - int(review['rating']))} "
            f"<b>{esc(review['name'])}</b> · {esc(review['source'])}"
        )
        lines.append(f"<i>{esc(review['text'])[:110]}</i>")
        lines.append("")
    if not reviews:
        lines.append("Отзывов пока нет — добавьте первый.")
    rows: list[list[Btn]] = []
    for review in reviews:
        rows.append([
            Btn(
                f"⭐ {review['name'][:18]} · {review['rating']}/5",
                callback_data=f"adm:rev:{review['id']}",
            )
        ])
    rows.append([Btn("➕ Добавить отзыв", callback_data="adm:rev_add")])
    rows.append([Btn("← В админ-панель", callback_data="adm:home")])
    return "\n".join(lines), Kb(rows)


def review_text(review: dict) -> str:
    rating = int(review["rating"])
    return (
        f"⭐ <b>Отзыв №{review['id']}</b>\n\n"
        f"{'★' * rating}{'☆' * (5 - rating)} · <b>{esc(review['name'])}</b>\n"
        f"{esc(review['source'])}\n\n"
        f"<i>{esc(review['text'])}</i>"
    )


def review_kb(review: dict) -> Kb:
    rid = review["id"]
    return Kb([
        [Btn("✏️ Имя", callback_data=f"adm:rev_edit:{rid}:name"),
         Btn("📝 Текст", callback_data=f"adm:rev_edit:{rid}:text")],
        [Btn("⭐ Рейтинг", callback_data=f"adm:rev_edit:{rid}:rating"),
         Btn("🏷 Источник", callback_data=f"adm:rev_edit:{rid}:source")],
        [Btn("🗑 Удалить", callback_data=f"adm:rev_del:{rid}")],
        [Btn("← К отзывам", callback_data="adm:reviews")],
    ])


async def show_review_detail(ctx: Ctx, q, review_id: int) -> None:
    review = await ctx.db.get_review(review_id)
    if not review:
        await edit_q(q, "Отзыв не найден.", Kb([[Btn("← К отзывам", callback_data="adm:reviews")]]))
        return
    await edit_q(q, review_text(review), review_kb(review))


# ---------- почему мы ----------

async def why_screen(ctx: Ctx) -> tuple[str, Kb]:
    items = await ctx.db.list_why()
    lines = ["💡 <b>Почему мы</b>", f"Карточек: {len(items)}", ""]
    for item in items:
        lines.append(f"{esc(item['icon'])} <b>{esc(item['title'])}</b>")
        lines.append(f"<i>{esc(item['text'])[:120]}</i>")
        lines.append("")
    if not items:
        lines.append("Карточек пока нет — добавьте первую.")
    rows: list[list[Btn]] = []
    for item in items:
        rows.append([
            Btn(
                f"{item['icon']} {item['title'][:20]}",
                callback_data=f"adm:why:{item['id']}",
            )
        ])
    rows.append([Btn("➕ Добавить карточку", callback_data="adm:why_add")])
    rows.append([Btn("← В админ-панель", callback_data="adm:home")])
    return "\n".join(lines), Kb(rows)


def why_text(item: dict) -> str:
    return (
        f"💡 <b>Почему мы · карточка №{item['id']}</b>\n\n"
        f"<b>{esc(item['icon'])}</b>\n"
        f"<b>{esc(item['title'])}</b>\n\n"
        f"{esc(item['text'])}"
    )


def why_kb(item: dict) -> Kb:
    wid = item["id"]
    return Kb([
        [Btn("✏️ Иконка", callback_data=f"adm:why_edit:{wid}:icon"),
         Btn("📝 Заголовок", callback_data=f"adm:why_edit:{wid}:title")],
        [Btn("📄 Текст", callback_data=f"adm:why_edit:{wid}:text")],
        [Btn("🗑 Удалить", callback_data=f"adm:why_del:{wid}")],
        [Btn("← К «Почему мы»", callback_data="adm:whys")],
    ])


async def show_why_detail(ctx: Ctx, q, item_id: int) -> None:
    item = await ctx.db.get_why(item_id)
    if not item:
        await edit_q(q, "Карточка не найдена.", Kb([[Btn("← К «Почему мы»", callback_data="adm:whys")]]))
        return
    await edit_q(q, why_text(item), why_kb(item))


def why_preview(draft: dict) -> str:
    return (
        "💡 <b>Проверьте карточку</b>\n\n"
        f"<b>{esc(draft.get('icon', ''))}</b>\n"
        f"<b>{esc(draft.get('title', ''))}</b>\n\n"
        f"{esc(draft.get('text', ''))}"
    )


# ---------- контакты ----------

CONTACTS = [
    ("brand", "Название", "ЛЕЗВИЕ"),
    ("city", "Город", "Алматы"),
    ("address", "Адрес", "пр. Достык, 132"),
    ("address_note", "Адрес: уточнение", "уг. ул. Кабанбай батыра"),
    ("phone", "Телефон", "+7 700 000 00 00"),
    ("whatsapp", "WhatsApp (цифры)", "77000000000"),
    ("twogis_url", "Ссылка 2ГИС", "https://2gis.kz/..."),
    ("instagram", "Instagram", "@lezvie.barber"),
]
CONTACT_MAP = {key: (label, placeholder) for key, label, placeholder in CONTACTS}


async def contacts_screen(ctx: Ctx) -> tuple[str, Kb]:
    settings = await ctx.db.get_settings()
    lines = ["📍 <b>Контакты и бренд</b>", ""]
    for key, label, _ in CONTACTS:
        value = settings.get(key, "")
        if key == "whatsapp":
            value = display_phone(whatsapp_digits(settings))
        lines.append(f"<b>{esc(label)}:</b> {esc(value) or '—'}")
    lines += [
        "",
        f"🕘 Часы работы: <b>{esc(settings_hours_text(settings))}</b>",
        f"{esc(settings_hours_note(settings))}",
        "",
        "Часы работы и обед меняются в «Настройках» — они общие для сайта, "
        "записи и всех мастеров.",
        "Нажмите поле, чтобы изменить. Изменения появятся на сайте после обновления страницы.",
    ]
    rows: list[list[Btn]] = []
    pair: list[Btn] = []
    for key, label, _ in CONTACTS:
        pair.append(Btn(label, callback_data=f"adm:con_edit:{key}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([Btn("← В админ-панель", callback_data="adm:home")])
    return "\n".join(lines), Kb(rows)


# ---------- настройки ----------

async def settings_screen(ctx: Ctx) -> tuple[str, Kb]:
    settings = await ctx.db.get_settings()
    enabled = settings.get("booking_enabled", "1") == "1"
    lines = [
        "⚙️ <b>Настройки записи</b>",
        "",
        f"Онлайн-запись: <b>{'включена' if enabled else 'выключена'}</b>",
        f"Часы работы: <b>{settings.get('work_start', '10:00')}–{settings.get('work_end', '21:00')}</b>",
        f"Последний старт: <b>{settings.get('last_slot', '20:00')}</b>",
        f"Шаг слотов: <b>{settings.get('slot_step', '30')} мин</b>",
        f"Напоминание админу: <b>за {settings.get('reminder_minutes', '120')} мин</b>",
        f"Редакция политики: <b>{esc(settings.get('privacy_updated', '—'))}</b>",
        "",
        "Эти часы — единые для сайта, записи и всех мастеров. "
        "Перерыв у каждого мастера свой и задаётся в карточке мастера. "
        "Сайт показывает эти же часы в контактах.",
    ]
    rows = [
        [Btn("🔴 Выключить запись" if enabled else "🟢 Включить запись", callback_data="adm:set_toggle")],
        [
            Btn("🕘 Открытие", callback_data="adm:set_edit:work_start"),
            Btn("🕘 Закрытие", callback_data="adm:set_edit:work_end"),
        ],
        [
            Btn("🕘 Последний старт", callback_data="adm:set_edit:last_slot"),
            Btn("⏱ Шаг слотов", callback_data="adm:set_step"),
        ],
        [Btn("🔔 Напоминание", callback_data="adm:set_edit:reminder_minutes"),
         Btn("📄 Дата политики", callback_data="adm:set_edit:privacy_updated")],
        [Btn("← В админ-панель", callback_data="adm:home")],
    ]
    return "\n".join(lines), Kb(rows)


# ---------- цифры и достижения на сайте ----------

def stat_display_label(value: str) -> str:
    return str(value or "").replace("|", " · ")


def stat_is_numeric(value: Any) -> bool:
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    try:
        float(text)
    except (TypeError, ValueError):
        return False
    return True


def stat_plus_suffix(value: Any, plus: Any) -> str:
    return "+" if int(plus or 0) and stat_is_numeric(value) else ""


async def site_stats_screen(ctx: Ctx) -> tuple[str, Kb]:
    items = await ctx.db.list_site_stats()
    lines = [
        "🏆 <b>Цифры и достижения</b>",
        "",
        "Это блок на главной странице сразу под обложкой.",
        "Значение может быть числом или коротким текстом. «|» в подписи означает перенос строки.",
        "Можно добавлять свои достижения: «50 точек по всему миру», «у нас стриглась знаменитость» и т.п.",
        "",
    ]
    if items:
        for item in items:
            plus = stat_plus_suffix(item.get("value"), item.get("plus"))
            lines.append(
                f"{esc(item.get('value'))}{plus} · {esc(stat_display_label(item.get('label', '')))}"
            )
    else:
        lines.append("Пока пусто — добавьте первое достижение.")
    rows: list[list[Btn]] = []
    for item in items:
        plus = stat_plus_suffix(item.get("value"), item.get("plus"))
        label = stat_display_label(item.get("label", ""))
        button = f"{str(item.get('value') or '')[:10]}{plus} · {label[:16]}"
        rows.append([Btn(button[:40], callback_data=f"adm:stat:{item['id']}")])
    rows.append([Btn("➕ Добавить достижение", callback_data="adm:stat_add")])
    rows.append([Btn("← В админ-панель", callback_data="adm:home")])
    return "\n".join(lines), Kb(rows)


def site_stat_text(item: dict) -> str:
    plus = stat_plus_suffix(item.get("value"), item.get("plus"))
    return (
        f"🏆 <b>Достижение №{item['id']}</b>\n\n"
        f"<b>{esc(item.get('value'))}{plus}</b>\n"
        f"{esc(stat_display_label(item.get('label', '')))}\n\n"
        "Так это выглядит в блоке на главной."
    )


def site_stat_kb(item: dict) -> Kb:
    sid = item["id"]
    rows = [
        [Btn("✏️ Значение", callback_data=f"adm:stat_edit:{sid}:value"),
         Btn("✏️ Подпись", callback_data=f"adm:stat_edit:{sid}:label")],
    ]
    if stat_is_numeric(item.get("value")):
        plus = int(item.get("plus") or 0)
        rows.append([
            Btn(
                "➖ Убрать плюсик" if plus else "➕ Добавить плюсик",
                callback_data=f"adm:stat_plus:{sid}",
            )
        ])
    rows += [
        [Btn("🗑 Удалить достижение", callback_data=f"adm:stat_del:{sid}")],
        [Btn("← К цифрам", callback_data="adm:site_stats")],
    ]
    return Kb(rows)


async def show_site_stat_detail(ctx: Ctx, q, stat_id: int) -> None:
    item = await ctx.db.get_site_stat(stat_id)
    if not item:
        await edit_q(
            q,
            "Достижение не найдено.",
            Kb([[Btn("← К цифрам", callback_data="adm:site_stats")]]),
        )
        return
    await edit_q(q, site_stat_text(item), site_stat_kb(item))


def stat_add_preview_text(draft: dict) -> str:
    plus = stat_plus_suffix(draft.get("value"), draft.get("plus"))
    return (
        "🏆 <b>Проверьте достижение</b>\n\n"
        f"<b>{esc(draft.get('value'))}{plus}</b>\n"
        f"{esc(stat_display_label(draft.get('label', '')))}\n\n"
        "Сохранить и показать на главной?"
    )


def stat_add_preview_kb(draft: dict) -> Kb:
    rows: list[list[Btn]] = []
    if stat_is_numeric(draft.get("value")):
        plus = int(draft.get("plus") or 0)
        rows.append([
            Btn(
                "➖ Убрать плюсик" if plus else "➕ Добавить плюсик",
                callback_data="adm:stat_add_plus",
            )
        ])
    rows += [
        [Btn("✅ Сохранить", callback_data="adm:stat_add_save")],
        [Btn("❌ Отмена", callback_data="adm:stat_add_cancel")],
    ]
    return Kb(rows)


# ---------- фото и очистка ----------

async def media_screen(ctx: Ctx) -> tuple[str, Kb]:
    inventory = media_inventory(ctx.cfg)
    references = await ctx.db.media_references()
    total_files = sum(item["files"] for item in inventory.values())
    total_bytes = sum(item["bytes"] for item in inventory.values())
    lines = [
        "🧹 <b>Фото и очистка</b>",
        "",
        f"Всего файлов: <b>{total_files}</b> · {format_bytes(total_bytes)}",
        f"Ссылок в базе: <b>{len(references)}</b>",
        "",
    ]
    for name, title in (("services", "Услуги"), ("gallery", "Галерея"), ("masters", "Мастера"), ("tmp", "Временные")):
        item = inventory.get(name, {"files": 0, "bytes": 0})
        lines.append(f"{title}: {item['files']} · {format_bytes(item['bytes'])}")
    lines += [
        "",
        "«Проверить» покажет, сколько файлов не используется, но ничего не удалит.",
        "«Удалить лишние» стирает только файлы старше 24 часов, на которые нет ссылки в базе. "
        "Фото, заменённые или удалённые в админке, удаляются сразу. "
        "Временные файлы старше 24 часов чистятся при запуске.",
    ]
    rows = [
        [Btn("🔍 Проверить без удаления", callback_data="adm:media_check")],
        [Btn("🗑 Удалить лишние файлы", callback_data="adm:media_clean")],
        [Btn("← В админ-панель", callback_data="adm:home")],
    ]
    return "\n".join(lines), Kb(rows)
