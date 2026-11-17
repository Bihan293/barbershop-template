from __future__ import annotations
from .deps import *
from .services import combine_services, service_items

# ============================================================
# Клиентское меню и запись
# ============================================================

async def client_home_text(ctx: Ctx) -> str:
    settings = await ctx.db.get_settings()
    return (
        f"💈 <b>{esc(settings.get('brand', 'ЛЕЗВИЕ'))}</b> · {esc(settings.get('city', 'Алматы'))}\n\n"
        f"{esc(settings.get('address', ''))}\n"
        f"{esc(settings_hours_text(settings))}\n"
        + (f"{esc(settings_hours_note(settings))}\n" if settings_hours_note(settings) else "")
        + "\n"
        "Запишитесь за пару минут: выберите услугу, дату и время. "
        "Мастер подтвердит запись в выбранном мессенджере."
    )


async def client_home_kb(ctx: Ctx, uid: int) -> Kb:
    rows = [
        [Btn("📅 Записаться", callback_data="cl:book")],
        [Btn("💈 Услуги", callback_data="cl:services"), Btn("📞 Контакты", callback_data="cl:contacts")],
        [Btn("🗂 Мои записи", callback_data="cl:my")],
    ]
    site_link = public_site_link(ctx.cfg)
    if site_link:
        rows.append([Btn("🌐 Наш сайт", url=site_link)])
    if ctx.is_admin(uid):
        rows.append([Btn("⚙️ Админ-панель", callback_data="adm:home")])
    return Kb(rows)


async def show_client_home_message(ctx: Ctx, message, uid: int) -> None:
    await message.reply_text(
        await client_home_text(ctx),
        parse_mode=ParseMode.HTML,
        reply_markup=await client_home_kb(ctx, uid),
    )


async def show_client_home_q(ctx: Ctx, q, uid: int) -> None:
    await edit_q(q, await client_home_text(ctx), await client_home_kb(ctx, uid))


async def client_services_screen(ctx: Ctx, uid: int) -> tuple[str, Kb]:
    services = await ctx.db.list_services()
    data = ctx.flows.data(uid)
    selected = data.get("selected_services")
    if not isinstance(selected, list):
        draft = data.get("draft") if isinstance(data.get("draft"), dict) else {}
        raw = draft.get("service_ids")
        if not isinstance(raw, list):
            raw = [draft.get("service_id")] if draft.get("service_id") else []
        selected = raw
    valid_ids = {int(item["id"]) for item in services}
    selected = [int(item) for item in selected if int(item) in valid_ids]
    ctx.flows.set(uid, "cl_services", selected_services=selected)
    selected_set = set(selected)
    lines = ["💈 <b>Выберите услуги</b>", "Можно выбрать несколько.", ""]
    rows: list[list[Btn]] = []
    total_price = 0
    total_duration = 0
    for service in services:
        sid = int(service["id"])
        chosen = sid in selected_set
        if chosen:
            total_price += int(service["price"] or 0)
            total_duration += int(service["duration"] or 0)
        lines += [
            f"{'✅' if chosen else '▫️'} <b>{esc(service['name'])}</b> · {money(service['price'])} · {service['duration']} мин",
        ]
        rows.append([
            Btn(
                f"{'✅' if chosen else '➕'} {service['name'][:22]}",
                callback_data=f"cl:svc_toggle:{sid}",
            )
        ])
    if not services:
        lines.append("Список услуг обновляется. Позвоните нам, чтобы записаться.")
    if selected:
        lines += [
            "",
            f"Выбрано: <b>{len(selected)}</b> · {total_duration} мин · <b>{money(total_price)}</b>",
        ]
        rows.append([Btn("➡️ Продолжить", callback_data="cl:svc_done")])
    rows.append([Btn("← В меню", callback_data="cl:menu")])
    return "\n".join(lines), Kb(rows)


async def resolve_draft_services(
    ctx: Ctx, draft: dict
) -> tuple[Optional[dict], list[dict], Optional[str]]:
    raw_ids = draft.get("service_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raw_ids = [draft.get("service_id")]
    services: list[dict] = []
    seen: set[int] = set()
    for raw in raw_ids[:10]:
        try:
            service = await ctx.db.get_service(int(raw))
        except (TypeError, ValueError):
            service = None
        if not service:
            return None, [], "Одна из услуг больше недоступна. Выберите услуги заново."
        if int(service["id"]) not in seen:
            seen.add(int(service["id"]))
            services.append(service)
    if not services:
        return None, [], "Выберите услугу"
    return combine_services(services), service_items(services), None


async def client_contacts_text(ctx: Ctx) -> str:
    settings = await ctx.db.get_settings()
    return (
        "📞 <b>Контакты</b>\n\n"
        f"📍 {esc(settings.get('address', ''))}\n"
        + (f"{esc(settings.get('address_note', ''))}\n" if settings.get("address_note") else "")
        + "\n"
        f"🕘 {esc(settings_hours_text(settings))}\n"
        + (f"{esc(settings_hours_note(settings))}\n" if settings_hours_note(settings) else "")
        + "\n"
        f"☎️ {esc(settings.get('phone', ''))}\n"
        f"💬 WhatsApp: {esc(display_phone(whatsapp_digits(settings)))}\n"
        f"🖼 Instagram: {esc(instagram_label(settings.get('instagram', '')))}"
    )


async def client_booking_allowed(ctx: Ctx, uid: int) -> tuple[bool, str]:
    if ctx.is_admin(uid):
        return True, ""
    settings = await ctx.db.get_settings()
    if settings.get("booking_enabled", "1") == "1":
        masters = await ctx.db.list_masters(active_only=True)
        if masters:
            return True, ""
        phone = settings.get("phone", "")
        return False, (
            "⛔ <b>Онлайн-запись временно недоступна</b>\n\n"
            "Сейчас нет активных мастеров. "
            f"Позвоните нам: <b>{esc(phone)}</b>"
        )
    phone = settings.get("phone", "")
    return False, (
        "⛔ <b>Онлайн-запись временно недоступна</b>\n\n"
        f"Позвоните нам: <b>{esc(phone)}</b>\n"
        "Или загляните чуть позже."
    )


async def client_masters_screen(ctx: Ctx, q, uid: int) -> None:
    data = ctx.flows.data(uid)
    draft = data.get("draft", {})
    service, items, service_error = await resolve_draft_services(ctx, draft)
    if service_error or not service:
        ctx.flows.clear(uid)
        await edit_q(q, service_error or "Услуга больше недоступна.", Kb([[Btn("← К услугам", callback_data="cl:services")]]))
        return
    draft["service_id"] = service["id"]
    draft["service_ids"] = [item["id"] for item in items]
    draft["service_name"] = service["name"]
    draft["price"] = service["price"]
    draft["duration"] = service["duration"]
    draft["service_items"] = items
    masters = await ctx.db.list_masters(active_only=True)
    if not masters:
        draft["master_id"] = None
        draft["master_name"] = ""
        ctx.flows.set(uid, "cl_date", draft=draft)
        await client_dates_screen(ctx, q, uid)
        return
    draft["service_name"] = service["name"]
    draft["price"] = service["price"]
    draft["duration"] = service["duration"]
    ctx.flows.set(uid, "cl_master", draft=draft)
    rows: list[list[Btn]] = [[Btn("👥 Любой свободный мастер", callback_data="cl:master:0")]]
    for master in masters:
        rows.append([
            Btn(
                f"👨‍💈 {master['name'][:20]}",
                callback_data=f"cl:master:{master['id']}",
            )
        ])
    rows.append([Btn("← К услугам", callback_data="cl:services")])
    lines = [
        "👨‍💈 <b>Выберите мастера</b>",
        "",
        f"Услуга: <b>{esc(service['name'])}</b> · {service['duration']} мин",
        "",
    ]
    for master in masters:
        description = clean_text(master.get("description") or "", 120)
        lines.append(
            f"<b>{esc(master['name'])}</b>"
            + (f" — {esc(description)}" if description else "")
        )
    lines += ["", "Можно выбрать конкретного мастера или довериться свободному."]
    text = "\n".join(lines)
    await edit_q(q, text, Kb(rows))


async def client_dates_screen(ctx: Ctx, q, uid: int) -> None:
    data = ctx.flows.data(uid)
    draft = data.get("draft", {})
    service, items, service_error = await resolve_draft_services(ctx, draft)
    if service_error or not service:
        ctx.flows.clear(uid)
        await edit_q(q, service_error or "Услуга больше недоступна.", Kb([[Btn("← К услугам", callback_data="cl:services")]]))
        return
    draft["service_id"] = service["id"]
    draft["service_ids"] = [item["id"] for item in items]
    draft["service_name"] = service["name"]
    draft["price"] = service["price"]
    draft["duration"] = service["duration"]
    draft["service_items"] = items
    if draft.get("master_id"):
        master = await ctx.db.get_master(int(draft["master_id"]))
        if master and int(master.get("active") or 0):
            draft["master_name"] = master["name"]
        else:
            draft["master_id"] = None
            draft["master_name"] = ""
    ctx.flows.set(uid, "cl_date", draft=draft)

    today = datetime.now(ctx.cfg.tz).date()
    rows: list[list[Btn]] = []
    pair: list[Btn] = []
    for offset in range(10):
        day = today + timedelta(days=offset)
        iso = day.isoformat()
        if offset == 0:
            label = "Сегодня"
        elif offset == 1:
            label = "Завтра"
        else:
            label = f"{day.day} {MONTHS_GEN[day.month - 1]}, {WEEKDAYS[day.weekday()]}"
        pair.append(Btn(label, callback_data=f"cl:date:{iso}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([Btn("← К мастерам", callback_data="cl:masters")])
    text = (
        f"📅 <b>Выберите дату</b>\n\n"
        f"Услуга: <b>{esc(service['name'])}</b>\n"
        f"Мастер: <b>{esc(draft.get('master_name') or 'любой свободный')}</b>\n"
        f"{money(service['price'])} · {service['duration']} мин"
    )
    await edit_q(q, text, Kb(rows))


async def client_times_screen(ctx: Ctx, q, uid: int, day: str) -> None:
    data = ctx.flows.data(uid)
    draft = data.get("draft", {})
    service, items, service_error = await resolve_draft_services(ctx, draft)
    if service_error or not service:
        ctx.flows.clear(uid)
        await edit_q(q, service_error or "Услуга больше недоступна.", Kb([[Btn("← К услугам", callback_data="cl:services")]]))
        return
    draft["service_id"] = service["id"]
    draft["service_ids"] = [item["id"] for item in items]
    draft["service_name"] = service["name"]
    draft["price"] = service["price"]
    draft["duration"] = service["duration"]
    draft["service_items"] = items
    slots = await ctx.db.available_slots(
        day,
        int(service["duration"]),
        master_id=draft.get("master_id"),
    )
    draft["date"] = day
    ctx.flows.set(uid, "cl_time", draft=draft)

    if not slots:
        await edit_q(
            q,
            f"На {date_label(day)} свободных слотов нет.\n\n"
            "Попробуйте другую дату — обычно есть места на завтра и далее.",
            Kb([
                [Btn("📅 Другая дата", callback_data="cl:dates")],
                [Btn("👥 Любой мастер", callback_data="cl:master:0")],
                [Btn("← В меню", callback_data="cl:menu")],
            ]),
        )
        return

    rows: list[list[Btn]] = []
    row: list[Btn] = []
    for slot in slots:
        row.append(Btn(slot, callback_data=f"cl:time:{slot}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([Btn("← Другая дата", callback_data="cl:dates")])

    expected_start = ""
    if draft.get("master_id"):
        schedule = await ctx.db.get_master_schedule_day(
            int(draft["master_id"]), date_from_iso(day).weekday()
        )
        expected_start = (schedule or {}).get("work_start", "")
    if not expected_start:
        settings = await ctx.db.get_settings()
        expected_start = settings.get("work_start", "10:00")

    note = ""
    if day == datetime.now(ctx.cfg.tz).date().isoformat() and slots:
        if slots[0] > expected_start:
            note = (
                f"⚠️ Сегодня доступные слоты начинаются с <b>{slots[0]}</b> — "
                "более раннее время уже прошло или занято.\n"
                "Выберите другую дату, чтобы увидеть полный день.\n\n"
            )

    text = (
        f"🕘 <b>Выберите время</b>\n\n"
        f"{date_label(day)}\n"
        f"<b>{esc(service['name'])}</b> · {money(service['price'])} · {service['duration']} мин\n"
        f"👨‍💈 {esc(draft.get('master_name') or 'любой свободный')}"
        + (f"\n\n{note}" if note else "")
    )
    await edit_q(q, text, Kb(rows))


def client_summary_text(ctx: Ctx, draft: dict) -> str:
    date_value = draft.get("date")
    date_text = date_label(date_value) if date_value else "дата не выбрана"
    items = draft.get("service_items")
    items = items if isinstance(items, list) else []
    lines = [
        "Проверьте запись",
        "",
        f"💈 <b>{esc(draft.get('service_name', ''))}</b>",
    ]
    if len(items) > 1:
        for item in items:
            lines.append(
                f"• {esc(item.get('name', ''))} · {money(item.get('price', 0))} · {item.get('duration', 0)} мин"
            )
    lines += [
        f"💰 {money(draft.get('price', 0))} · {draft.get('duration', 0)} мин",
        f"📅 {date_text}, <b>{draft.get('time', '')}</b>",
        f"👨‍💈 {esc(draft.get('master_name') or 'любой мастер')}",
        "",
        f"👤 {esc(draft.get('name', ''))}",
        f"📞 {esc(draft.get('phone', ''))}",
        f"💬 {channel_label(draft.get('channel', 'telegram'))}",
    ]
    if draft.get("comment"):
        lines.append(f"📝 {esc(draft['comment'])}")
    policy = public_site_link(ctx.cfg)
    policy_link = (
        f' <a href="{esc(policy)}/privacy.html">политикой</a>'
        if policy
        else ""
    )
    lines += [
        "",
        f"Нажимая «Подтвердить запись», вы соглашаетесь с обработкой персональных данных{policy_link}.",
    ]
    return "\n".join(lines)


async def client_success_text(ctx: Ctx, order: dict) -> tuple[str, Kb]:
    settings = await ctx.db.get_settings()
    text = (
        f"✅ <b>Заявка №{order['id']} принята</b>\n\n"
        f"💈 {esc(order['service_name'])}\n"
        f"📅 {date_label(order['date'])}, <b>{order['time']}</b>\n"
        f"💰 {money(order['price'])}\n\n"
        f"Мастер свяжется с вами в {channel_label(order['channel'])} и подтвердит запись.\n"
        f"📍 {esc(settings.get('address', ''))}"
    )
    rows = [
        [Btn("🗂 Мои записи", callback_data="cl:my")],
        [Btn("← В меню", callback_data="cl:menu")],
    ]
    wa = whatsapp_digits(settings)
    if order["channel"] == "whatsapp" and wa:
        body = (
            f"Здравствуйте! Я записался(ась) на {date_label(order['date'])} в {order['time']}, "
            f"{order['service_name']}"
            + (f", мастер {order['master_name']}" if order.get("master_name") else "")
            + f". Заявка №{order['id']}."
        )
        rows.insert(0, [Btn("💬 Открыть WhatsApp", url=f"https://wa.me/{wa}?text={quote(body)}")])
    return text, Kb(rows)


async def client_my_orders(ctx: Ctx, uid: int) -> tuple[str, Kb]:
    orders = await ctx.db.orders_by_tg(uid)
    if not orders:
        return (
            "🗂 <b>Мои записи</b>\n\nУ вас пока нет записей. Самое время это исправить.",
            Kb([[Btn("📅 Записаться", callback_data="cl:book")], [Btn("← В меню", callback_data="cl:menu")]]),
        )
    now = datetime.now(ctx.cfg.tz)
    upcoming: list[dict] = []
    for order in orders:
        if order["status"] not in {"new", "confirmed"}:
            continue
        try:
            start = datetime.strptime(
                f"{order['date']} {order['time']}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=ctx.cfg.tz)
        except ValueError:
            continue
        if start > now:
            upcoming.append(order)
    upcoming.sort(key=lambda item: (item["date"], item["time"]))

    lines = ["🗂 <b>Мои записи</b>", ""]
    for order in orders[:10]:
        lines.append(
            f"{status_icon(order['status'])} <b>{date_label(order['date'])}, {order['time']}</b>\n"
            f"{esc(order['service_name'])} · {esc(order.get('master_name') or 'любой мастер')} · "
            f"{money(order['price'])} · {status_label(order['status'])}"
        )
        lines.append("")
    if upcoming:
        lines.append("Нажмите ❌ под списком, чтобы отменить будущую запись.")
        lines.append("")

    rows: list[list[Btn]] = []
    for order in upcoming[:5]:
        label = (
            f"❌ {order['date'][8:10]}.{order['date'][5:7]} {order['time']} · "
            f"{order['service_name'][:12]}"
        )
        rows.append([
            Btn("📅 Перенести", callback_data=f"cl:myresched:{order['id']}"),
            Btn(label, callback_data=f"cl:mycancel:{order['id']}"),
        ])
    rows.append([Btn("📅 Записаться", callback_data="cl:book")])
    rows.append([Btn("← В меню", callback_data="cl:menu")])
    return "\n".join(lines), Kb(rows)


async def after_client_phone(ctx: Ctx, message, uid: int, phone: str) -> None:
    data = ctx.flows.data(uid)
    draft = data.get("draft", {})
    draft["phone"] = display_phone(phone) or phone
    ctx.flows.set(uid, "cl_channel", draft=draft)
    await message.reply_text("Номер сохранён.", reply_markup=ReplyKeyboardRemove())
    await message.reply_text(
        "Куда отправить заявку и где вам удобнее получить подтверждение?",
        reply_markup=Kb([
            [Btn("Telegram", callback_data="cl:chan:telegram"), Btn("WhatsApp", callback_data="cl:chan:whatsapp")],
            [Btn("❌ Отмена", callback_data="cl:cancel")],
        ]),
    )


async def _client_reschedule_order(
    ctx: Ctx, uid: int, order_id: int
) -> tuple[Optional[dict], Optional[str]]:
    order = await ctx.db.get_order(order_id)
    if not order or int(order.get("tg_id") or 0) != int(uid):
        return None, "Запись не найдена"
    if order["status"] not in {"new", "confirmed"}:
        return None, "Эту запись уже нельзя перенести"
    try:
        start = datetime.strptime(
            f"{order['date']} {order['time']}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=ctx.cfg.tz)
    except ValueError:
        return None, "Некорректная дата записи"
    if start <= datetime.now(ctx.cfg.tz):
        return None, "Запись уже началась — позвоните в салон"
    return order, None


async def client_reschedule_dates_screen(
    ctx: Ctx, q, uid: int, order_id: int
) -> None:
    order, error = await _client_reschedule_order(ctx, uid, order_id)
    if error or not order:
        await safe_answer(q, error or "Запись не найдена", show_alert=True)
        text, kb = await client_my_orders(ctx, uid)
        await edit_q(q, text, kb)
        return
    if order.get("master_id"):
        master = await ctx.db.get_master(int(order["master_id"]))
        if not master or not int(master.get("active") or 0):
            await safe_answer(q, "Мастер сейчас недоступен — позвоните в салон", show_alert=True)
            text, kb = await client_my_orders(ctx, uid)
            await edit_q(q, text, kb)
            return
    today = datetime.now(ctx.cfg.tz).date()
    rows: list[list[Btn]] = []
    pair: list[Btn] = []
    for offset in range(14):
        day = (today + timedelta(days=offset)).isoformat()
        label = "Сегодня" if offset == 0 else ("Завтра" if offset == 1 else short_date_label(day, ctx.cfg.tz).capitalize())
        pair.append(Btn(label, callback_data=f"cl:myresched_date:{order_id}:{day}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([Btn("← Мои записи", callback_data="cl:my")])
    text = (
        "📅 <b>Перенести запись</b>\n\n"
        f"{esc(order['service_name'])} · {esc(order.get('master_name') or 'любой мастер')}\n"
        f"Сейчас: <b>{date_label(order['date'])}, {order['time']}</b>\n\n"
        "Выберите новую дату. Мастер останется тот же."
    )
    await edit_q(q, text, Kb(rows))


async def client_reschedule_times_screen(
    ctx: Ctx, q, uid: int, order_id: int, day: str
) -> None:
    order, error = await _client_reschedule_order(ctx, uid, order_id)
    iso_day = valid_iso_date(day)
    if error or not order or not iso_day:
        await safe_answer(q, error or "Запись не найдена", show_alert=True)
        return
    slots = await ctx.db.available_slots(
        iso_day,
        int(order["duration"] or 30),
        exclude_order_id=order_id,
        master_id=order.get("master_id"),
    )
    rows: list[list[Btn]] = []
    if not slots:
        text = (
            f"На {date_label(iso_day)} свободных слотов нет.\n\n"
            "Выберите другую дату."
        )
        rows = [
            [Btn("📅 Другая дата", callback_data=f"cl:myresched:{order_id}")],
            [Btn("← Мои записи", callback_data="cl:my")],
        ]
        await edit_q(q, text, Kb(rows))
        return
    row: list[Btn] = []
    for slot in slots:
        row.append(Btn(slot, callback_data=f"cl:myresched_time:{order_id}:{iso_day}:{slot}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([Btn("📅 Другая дата", callback_data=f"cl:myresched:{order_id}")])
    rows.append([Btn("← Мои записи", callback_data="cl:my")])
    text = (
        f"🕘 <b>Новое время · {date_label(iso_day)}</b>\n\n"
        f"{esc(order['service_name'])} · {esc(order.get('master_name') or 'любой мастер')}\n"
        f"Сейчас: {date_label(order['date'])}, {order['time']}\n\n"
        "Выберите новое время:"
    )
    await edit_q(q, text, Kb(rows))


async def client_reschedule_confirm_screen(
    ctx: Ctx, q, uid: int, order_id: int, day: str, slot: str
) -> None:
    order, error = await _client_reschedule_order(ctx, uid, order_id)
    iso_day = valid_iso_date(day)
    valid_slot = valid_time(slot)
    if error or not order or not iso_day or not valid_slot:
        await safe_answer(q, error or "Некорректное время", show_alert=True)
        return
    slots = await ctx.db.available_slots(
        iso_day,
        int(order["duration"] or 30),
        exclude_order_id=order_id,
        master_id=order.get("master_id"),
    )
    if valid_slot not in slots:
        await client_reschedule_times_screen(ctx, q, uid, order_id, iso_day)
        return
    text = (
        "📅 <b>Подтвердите перенос</b>\n\n"
        f"{esc(order['service_name'])} · {esc(order.get('master_name') or 'любой мастер')}\n"
        f"Было: {date_label(order['date'])}, <b>{order['time']}</b>\n"
        f"Станет: {date_label(iso_day)}, <b>{valid_slot}</b>\n\n"
        "Администратор получит уведомление."
    )
    await edit_q(
        q,
        text,
        Kb([
            [Btn("✅ Перенести", callback_data=f"cl:myresched_ok:{order_id}:{iso_day}:{valid_slot}")],
            [Btn("← Нет, назад", callback_data=f"cl:myresched:{order_id}")],
        ]),
    )


async def apply_client_reschedule(
    ctx: Ctx, q, uid: int, order_id: int, day: str, slot: str
) -> None:
    old = await ctx.db.get_order(order_id)
    if not old or int(old.get("tg_id") or 0) != int(uid):
        await safe_answer(q, "Запись не найдена", show_alert=True)
        return
    if old.get("master_id"):
        master = await ctx.db.get_master(int(old["master_id"]))
        if not master or not int(master.get("active") or 0):
            await safe_answer(q, "Мастер сейчас недоступен — позвоните в салон", show_alert=True)
            return
    updated, error = await ctx.db.reschedule_order(
        order_id, day, slot, owner_tg_id=uid
    )
    if error or not updated:
        await safe_answer(q, error or "Не удалось перенести", show_alert=True)
        text, kb = await client_my_orders(ctx, uid)
        await edit_q(q, text, kb)
        return
    admin_text = (
        "📅 <b>Клиент перенёс запись</b>\n\n"
        f"👤 {esc(updated['name'])}\n"
        f"📞 {esc(display_phone(updated['phone']) or updated['phone'])}\n"
        f"💈 {esc(updated['service_name'])} · {esc(updated.get('master_name') or 'любой мастер')}\n"
        f"Было: {date_label(old['date'])}, {old['time']}\n"
        f"Стало: <b>{date_label(updated['date'])}, {updated['time']}</b>"
    )
    await send_admins(
        ctx,
        admin_text,
        Kb([[
            Btn("📋 Открыть заказ", callback_data=f"adm:order:{order_id}"),
            Btn("💬 WhatsApp", url=order_whatsapp_url(ctx, updated)),
        ]]),
    )
    text = (
        "✅ <b>Запись перенесена</b>\n\n"
        f"{esc(updated['service_name'])} · {esc(updated.get('master_name') or 'любой мастер')}\n"
        f"Новое время: <b>{date_label(updated['date'])}, {updated['time']}</b>\n\n"
        "Если планы изменятся — отмените запись в «Моих записях» или позвоните в салон."
    )
    await edit_q(
        q,
        text,
        Kb([
            [Btn("🗂 Мои записи", callback_data="cl:my")],
            [Btn("← В меню", callback_data="cl:menu")],
        ]),
    )


async def handle_client_cb(ctx: Ctx, q, data: str) -> None:
    uid = q.from_user.id
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "menu":
        ctx.flows.clear(uid)
        await show_client_home_q(ctx, q, uid)
        return

    if action == "book":
        allowed, message = await client_booking_allowed(ctx, uid)
        if not allowed:
            await edit_q(q, message, Kb([[Btn("← В меню", callback_data="cl:menu")]]))
            return
        ctx.flows.clear(uid)
        text, kb = await client_services_screen(ctx, uid)
        await edit_q(q, text, kb)
        return

    if action == "svc_toggle" and len(parts) >= 3:
        allowed, message = await client_booking_allowed(ctx, uid)
        if not allowed:
            await edit_q(q, message, Kb([[Btn("← В меню", callback_data="cl:menu")]]))
            return
        try:
            service_id = int(parts[2])
        except ValueError:
            service_id = 0
        services = await ctx.db.list_services()
        valid_ids = {int(item["id"]) for item in services}
        if service_id not in valid_ids:
            await safe_answer(q, "Услуга больше недоступна", show_alert=True)
            return
        data_now = ctx.flows.data(uid)
        selected = data_now.get("selected_services")
        if not isinstance(selected, list):
            selected = []
        selected = [int(item) for item in selected if int(item) in valid_ids]
        if service_id in selected:
            selected.remove(service_id)
        else:
            selected.append(service_id)
        ctx.flows.set(uid, "cl_services", selected_services=selected)
        text, kb = await client_services_screen(ctx, uid)
        await edit_q(q, text, kb)
        return

    if action == "svc_done":
        allowed, message = await client_booking_allowed(ctx, uid)
        if not allowed:
            await edit_q(q, message, Kb([[Btn("← В меню", callback_data="cl:menu")]]))
            return
        data_now = ctx.flows.data(uid)
        selected = data_now.get("selected_services")
        selected = selected if isinstance(selected, list) else []
        selected = [int(item) for item in selected]
        if not selected:
            await safe_answer(q, "Выберите хотя бы одну услугу", show_alert=True)
            return
        draft = {"service_ids": selected}
        service, items, service_error = await resolve_draft_services(ctx, draft)
        if service_error or not service:
            await edit_q(
                q,
                service_error or "Услуги больше недоступны. Выберите заново.",
                Kb([[Btn("← К услугам", callback_data="cl:book")]]),
            )
            return
        draft.update({
            "service_id": service["id"],
            "service_ids": [item["id"] for item in items],
            "service_name": service["name"],
            "price": service["price"],
            "duration": service["duration"],
            "service_items": items,
        })
        ctx.flows.set(uid, "cl_master", draft=draft)
        await client_masters_screen(ctx, q, uid)
        return

    if action == "services":
        text, kb = await client_services_screen(ctx, uid)
        await edit_q(q, text, kb)
        return

    if action == "contacts":
        settings = await ctx.db.get_settings()
        wa = whatsapp_digits(settings)
        rows = []
        if wa:
            rows.append([Btn("💬 WhatsApp", url=f"https://wa.me/{wa}")])
        tgis = settings.get("twogis_url", "")
        if tgis:
            rows.append([Btn("🗺 2ГИС", url=tgis)])
        insta = settings.get("instagram", "")
        if insta:
            rows.append([Btn("🖼 Instagram", url=insta)])
        rows.append([Btn("← В меню", callback_data="cl:menu")])
        await edit_q(q, await client_contacts_text(ctx), Kb(rows))
        return

    if action == "svc" and len(parts) >= 3:
        allowed, message = await client_booking_allowed(ctx, uid)
        if not allowed:
            await edit_q(q, message, Kb([[Btn("← В меню", callback_data="cl:menu")]]))
            return
        ctx.flows.clear(uid)
        try:
            service = await ctx.db.get_service(int(parts[2]))
        except ValueError:
            service = None
        if not service:
            await edit_q(q, "Услуга не найдена.", Kb([[Btn("← К услугам", callback_data="cl:book")]]))
            return
        draft = {
            "service_id": service["id"],
            "service_ids": [service["id"]],
            "service_name": service["name"],
            "price": service["price"],
            "duration": service["duration"],
            "service_items": service_items([service]),
        }
        ctx.flows.set(uid, "cl_master", draft=draft)
        await client_masters_screen(ctx, q, uid)
        return

    if action == "master" and len(parts) >= 3:
        draft = ctx.flows.data(uid).get("draft", {})
        try:
            master_id = int(parts[2])
        except ValueError:
            master_id = 0
        if master_id:
            master = await ctx.db.get_master(master_id)
            if not master or not int(master.get("active") or 0):
                await edit_q(q, "Этот мастер сейчас недоступен. Выберите другого.", Kb([[Btn("← К мастерам", callback_data="cl:masters")]]))
                return
            draft["master_id"] = master_id
            draft["master_name"] = master["name"]
        else:
            draft["master_id"] = None
            draft["master_name"] = ""
        ctx.flows.set(uid, "cl_date", draft=draft)
        await client_dates_screen(ctx, q, uid)
        return

    if action == "masters":
        await client_masters_screen(ctx, q, uid)
        return

    if action == "dates":
        await client_dates_screen(ctx, q, uid)
        return

    if action == "date" and len(parts) >= 3:
        day = valid_iso_date(parts[2])
        if not day:
            await edit_q(q, "Некорректная дата.", Kb([[Btn("← Назад", callback_data="cl:dates")]]))
            return
        await client_times_screen(ctx, q, uid, day)
        return

    if action == "time" and len(parts) >= 4:
        slot = valid_time(":".join(parts[2:]))
        data_now = ctx.flows.data(uid)
        draft = data_now.get("draft", {})
        if not slot or not draft.get("date"):
            await edit_q(q, "Выберите время заново.", Kb([[Btn("← К датам", callback_data="cl:dates")]]))
            return
        draft["time"] = slot
        ctx.flows.set(uid, "cl_name", draft=draft)
        await edit_q(
            q,
            f"📅 {date_label(draft['date'])}, <b>{slot}</b>\n"
            f"💈 {esc(draft['service_name'])}\n\n"
            "Как вас зовут?",
            Kb([[Btn("❌ Отмена", callback_data="cl:cancel")]]),
        )
        return

    if action == "chan" and len(parts) >= 3:
        channel = parts[2]
        if channel not in {"telegram", "whatsapp"}:
            channel = "telegram"
        data_now = ctx.flows.data(uid)
        draft = data_now.get("draft", {})
        draft["channel"] = channel
        ctx.flows.set(uid, "cl_comment", draft=draft)
        await edit_q(
            q,
            "📝 Добавьте комментарий к записи — например, пожелания по стрижке.\n\n"
            "Можно пропустить.",
            Kb([
                [Btn("⏭ Пропустить", callback_data="cl:skip_comment")],
                [Btn("❌ Отмена", callback_data="cl:cancel")],
            ]),
        )
        return

    if action == "skip_comment":
        draft = ctx.flows.data(uid).get("draft", {})
        draft["comment"] = ""
        ctx.flows.set(uid, "cl_confirm", draft=draft)
        await edit_q(
            q,
            client_summary_text(ctx, draft),
            Kb([
                [Btn("✅ Подтвердить запись", callback_data="cl:confirm")],
                [Btn("❌ Отмена", callback_data="cl:cancel")],
            ]),
        )
        return

    if action == "confirm":
        allowed, message = await client_booking_allowed(ctx, uid)
        if not allowed:
            ctx.flows.clear(uid)
            await edit_q(q, message, Kb([[Btn("← В меню", callback_data="cl:menu")]]))
            return
        draft = ctx.flows.data(uid).get("draft", {})
        if not all(draft.get(k) for k in ("service_id", "date", "time", "name", "phone")):
            ctx.flows.clear(uid)
            await edit_q(q, "Данные записи потерялись. Начните заново.", Kb([[Btn("📅 Записаться", callback_data="cl:book")]]))
            return
        service, items, service_error = await resolve_draft_services(ctx, draft)
        if service_error or not service:
            ctx.flows.clear(uid)
            await edit_q(
                q,
                service_error or "Услуга больше недоступна.",
                Kb([[Btn("📅 Записаться", callback_data="cl:book")]]),
            )
            return
        slots = await ctx.db.available_slots(
            draft["date"],
            int(service["duration"]),
            master_id=draft.get("master_id"),
        )
        if draft["time"] not in slots:
            ctx.flows.set(uid, "cl_time", draft=draft)
            await edit_q(
                q,
                "Это время только что заняли. Выберите другое.",
                Kb([
                    [Btn("📅 Выбрать время", callback_data="cl:dates")],
                    [Btn("← В меню", callback_data="cl:menu")],
                ]),
            )
            return
        order, error = await ctx.db.create_order(
            name=draft["name"],
            phone=normalize_phone(draft["phone"]) or draft["phone"],
            service=service,
            day=draft["date"],
            slot=draft["time"],
            channel=draft.get("channel", "telegram"),
            comment=draft.get("comment", ""),
            source="telegram",
            tg_id=uid,
            master_id=draft.get("master_id"),
            consent_at=datetime.now(ctx.cfg.tz).isoformat(timespec="seconds"),
            service_items=items,
        )
        if error or not order:
            await edit_q(
                q,
                f"Не удалось записаться: {esc(error or 'ошибка')}.\n\n"
                "Выберите другое время или вернитесь в меню.",
                Kb([
                    [Btn("📅 Выбрать время", callback_data="cl:dates")],
                    [Btn("← В меню", callback_data="cl:menu")],
                ]),
            )
            return
        ctx.flows.clear(uid)
        if ctx.metrics:
            ctx.metrics.record_booking("telegram")
        LOG.info(
            "Новая заявка из Telegram #%s: %s %s, мастер %s",
            order["id"],
            order["date"],
            order["time"],
            order.get("master_name") or "—",
        )
        try:
            await notify_new_order(ctx, order)
        except Exception:
            LOG.exception("Заявка #%s создана, но уведомление не отправлено", order["id"])
        text, kb = await client_success_text(ctx, order)
        await edit_q(q, text, kb)
        return

    if action == "myresched" and len(parts) >= 3:
        try:
            order_id = int(parts[2])
        except ValueError:
            order_id = 0
        await client_reschedule_dates_screen(ctx, q, uid, order_id)
        return

    if action == "myresched_date" and len(parts) >= 4:
        try:
            order_id = int(parts[2])
        except ValueError:
            order_id = 0
        day = valid_iso_date(parts[3])
        if not day:
            await safe_answer(q, "Некорректная дата", show_alert=True)
            return
        await client_reschedule_times_screen(ctx, q, uid, order_id, day)
        return

    if action == "myresched_time" and len(parts) >= 5:
        try:
            order_id = int(parts[2])
        except ValueError:
            order_id = 0
        day = valid_iso_date(parts[3])
        slot = valid_time(":".join(parts[4:]))
        if not day or not slot:
            await safe_answer(q, "Некорректное время", show_alert=True)
            return
        await client_reschedule_confirm_screen(ctx, q, uid, order_id, day, slot)
        return

    if action == "myresched_ok" and len(parts) >= 5:
        try:
            order_id = int(parts[2])
        except ValueError:
            order_id = 0
        day = valid_iso_date(parts[3])
        slot = valid_time(":".join(parts[4:]))
        if not day or not slot:
            await safe_answer(q, "Некорректное время", show_alert=True)
            return
        await apply_client_reschedule(ctx, q, uid, order_id, day, slot)
        return

    if action == "mycancel" and len(parts) >= 3:
        try:
            order_id = int(parts[2])
        except ValueError:
            order_id = 0
        order = await ctx.db.get_order(order_id)
        if not order or int(order.get("tg_id") or 0) != uid:
            await safe_answer(q, "Запись не найдена", show_alert=True)
            return
        if order["status"] not in {"new", "confirmed"}:
            await safe_answer(q, "Эта запись уже неактивна", show_alert=True)
            return
        try:
            start = datetime.strptime(
                f"{order['date']} {order['time']}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=ctx.cfg.tz)
        except ValueError:
            await safe_answer(q, "Некорректная дата записи", show_alert=True)
            return
        if start <= datetime.now(ctx.cfg.tz):
            await safe_answer(q, "Запись уже началась — позвоните в салон", show_alert=True)
            return
        text = (
            "❌ <b>Отменить запись?</b>\n\n"
            f"{esc(order['service_name'])} · {esc(order.get('master_name') or 'любой мастер')}\n"
            f"📅 {date_label(order['date'])}, <b>{order['time']}</b>\n\n"
            "Слот освободится, администратор получит уведомление. "
            "Если до визита осталось меньше двух часов, лучше позвонить в салон."
        )
        await edit_q(
            q,
            text,
            Kb([
                [Btn("✅ Да, отменить", callback_data=f"cl:mycancelok:{order_id}")],
                [Btn("← Нет, назад", callback_data="cl:my")],
            ]),
        )
        return

    if action == "mycancelok" and len(parts) >= 3:
        try:
            order_id = int(parts[2])
        except ValueError:
            order_id = 0
        updated, error = await ctx.db.cancel_order_by_client(order_id, uid)
        if error or not updated:
            await safe_answer(q, error or "Не удалось отменить", show_alert=True)
            text, kb = await client_my_orders(ctx, uid)
            await edit_q(q, text, kb)
            return
        admin_text = (
            "❌ <b>Клиент отменил запись</b>\n\n"
            f"👤 {esc(updated['name'])}\n"
            f"📞 {esc(display_phone(updated['phone']) or updated['phone'])}\n"
            f"💈 {esc(updated['service_name'])} · {esc(updated.get('master_name') or 'любой мастер')}\n"
            f"📅 {date_label(updated['date'])}, <b>{updated['time']}</b>\n"
            f"💬 {channel_label(updated['channel'])}"
        )
        await send_admins(
            ctx,
            admin_text,
            Kb([[
                Btn("📋 Открыть заказ", callback_data=f"adm:order:{order_id}"),
                Btn("💬 WhatsApp", url=order_whatsapp_url(ctx, updated)),
            ]]),
        )
        text = (
            "✅ <b>Запись отменена</b>\n\n"
            f"{esc(updated['service_name'])} · {date_label(updated['date'])}, {updated['time']}\n\n"
            "Будем рады видеть вас снова."
        )
        await edit_q(
            q,
            text,
            Kb([
                [Btn("🗂 Мои записи", callback_data="cl:my")],
                [Btn("📅 Записаться", callback_data="cl:book")],
                [Btn("← В меню", callback_data="cl:menu")],
            ]),
        )
        return

    if action == "my":
        text, kb = await client_my_orders(ctx, uid)
        await edit_q(q, text, kb)
        return

    if action == "cancel":
        ctx.flows.clear(uid)
        await show_client_home_q(ctx, q, uid)
        return

    await show_client_home_q(ctx, q, uid)


async def handle_client_text(ctx: Ctx, update: Update, state: str) -> None:
    message = update.effective_message
    uid = update.effective_user.id
    data = ctx.flows.data(uid)
    draft = data.get("draft", {})
    text = (message.text or "").strip()

    if state == "cl_name":
        if text.lower() in {"отмена", "❌ отмена"}:
            ctx.flows.clear(uid)
            await message.reply_text("Запись отменена.", reply_markup=ReplyKeyboardRemove())
            await show_client_home_message(ctx, message, uid)
            return
        name = clean_text(text, 60)
        if not (2 <= len(name) <= 60):
            await message.reply_text("Имя: от 2 до 60 символов. Попробуйте ещё раз.")
            return
        draft["name"] = name
        ctx.flows.set(uid, "cl_phone", draft=draft)
        kb = ReplyKeyboardMarkup(
            [
                [KeyboardButton("📱 Отправить номер", request_contact=True)],
                [KeyboardButton("❌ Отмена")],
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await message.reply_text(
            "📞 Телефон для связи.\n\n"
            "Отправьте свой номер кнопкой ниже или введите вручную, например +7 700 123 45 67.",
            reply_markup=kb,
        )
        return

    if state == "cl_phone":
        if text == "❌ Отмена":
            ctx.flows.clear(uid)
            await message.reply_text("Запись отменена.", reply_markup=ReplyKeyboardRemove())
            await show_client_home_message(ctx, message, uid)
            return
        phone = normalize_phone(text)
        if not phone:
            await message.reply_text("Не похоже на телефон. Введите номер ещё раз или отправьте контакт.")
            return
        await after_client_phone(ctx, message, uid, phone)
        return

    if state == "cl_comment":
        draft["comment"] = "" if text == "-" else clean_text(text, 300)
        ctx.flows.set(uid, "cl_confirm", draft=draft)
        await message.reply_text(
            client_summary_text(ctx, draft),
            parse_mode=ParseMode.HTML,
            reply_markup=Kb([
                [Btn("✅ Подтвердить запись", callback_data="cl:confirm")],
                [Btn("❌ Отмена", callback_data="cl:cancel")],
            ]),
        )
        return

    if state == "cl_confirm":
        await message.reply_text(
            "Нажмите «Подтвердить запись» или «Отмена».",
            reply_markup=Kb([
                [Btn("✅ Подтвердить запись", callback_data="cl:confirm")],
                [Btn("❌ Отмена", callback_data="cl:cancel")],
            ]),
        )
        return

    ctx.flows.clear(uid)
    await show_client_home_message(ctx, message, uid)
