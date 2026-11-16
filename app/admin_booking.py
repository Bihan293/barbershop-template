from __future__ import annotations
from .deps import *
from .services import combine_services, service_items
from .admin_ui import order_detail_screen, orders_screen

# ============================================================
# Ручная запись клиента администратором
# ============================================================


def _draft(ctx: Ctx, uid: int) -> dict:
    return ctx.flows.data(uid).get("draft", {}) or {}


def _set_draft(ctx: Ctx, uid: int, state: str, **values: Any) -> dict:
    draft = dict(_draft(ctx, uid))
    draft.update(values)
    ctx.flows.set(uid, state, draft=draft)
    return draft


def _cancel_kb() -> Kb:
    return Kb([[Btn("❌ Отмена", callback_data="adm:ab_cancel")]])


def _ab_selected_ids(draft: dict) -> list[int]:
    raw = draft.get("service_ids")
    if not isinstance(raw, list):
        raw = [draft.get("service_id")] if draft.get("service_id") else []
    result: list[int] = []
    for value in raw:
        try:
            service_id = int(value)
        except (TypeError, ValueError):
            continue
        if service_id and service_id not in result:
            result.append(service_id)
    return result


async def _ab_resolve_services(
    ctx: Ctx, draft: dict
) -> tuple[Optional[dict], list[dict], Optional[str]]:
    services: list[dict] = []
    for service_id in _ab_selected_ids(draft)[:10]:
        service = await ctx.db.get_service(service_id)
        if not service:
            return None, [], "Одна из услуг больше недоступна. Выберите заново."
        services.append(service)
    if not services:
        return None, [], "Выберите хотя бы одну услугу"
    return combine_services(services), service_items(services), None


async def _ab_apply_services(
    ctx: Ctx, uid: int, state: str, service_ids: list[int]
) -> tuple[Optional[dict], list[dict], Optional[str]]:
    draft = _set_draft(ctx, uid, state, service_ids=service_ids)
    service, items, error = await _ab_resolve_services(ctx, draft)
    if error or not service:
        return None, [], error
    return _set_draft(
        ctx,
        uid,
        state,
        service_id=service["id"],
        service_ids=[item["id"] for item in items],
        service_name=service["name"],
        price=service["price"],
        duration=service["duration"],
        service_items=items,
        master_id=None,
        master_name="",
        master_choice=False,
        date="",
        time="",
    ), items, None


async def ab_ask_name(ctx: Ctx, q, uid: int) -> None:
    ctx.flows.set(uid, "ab_name", draft=_draft(ctx, uid))
    await edit_q(
        q,
        "➕ <b>Новая запись</b>\n\n"
        "Шаг 1 из 6. Введите имя клиента.\n\n"
        "Дальше: телефон → услуга → мастер → дата → время.",
        _cancel_kb(),
    )


async def ab_ask_phone(ctx: Ctx, q, uid: int) -> None:
    ctx.flows.set(uid, "ab_phone", draft=_draft(ctx, uid))
    await edit_q(
        q,
        "📞 Шаг 2 из 6. Введите телефон клиента.\n\n"
        "Например: +7 701 234 56 78",
        Kb([
            [Btn("← Имя", callback_data="adm:ab_ask_name")],
            [Btn("❌ Отмена", callback_data="adm:ab_cancel")],
        ]),
    )


async def ab_show_services(ctx: Ctx, q, uid: int) -> None:
    services = await ctx.db.list_services()
    if not services:
        ctx.flows.clear(uid)
        await edit_q(
            q,
            "Сначала добавьте хотя бы одну услугу в разделе «Услуги».",
            Kb([[Btn("💈 К услугам", callback_data="adm:services")]]),
        )
        return
    draft = _set_draft(ctx, uid, "ab_service")
    selected = _ab_selected_ids(draft)
    valid_ids = {int(item["id"]) for item in services}
    selected = [item for item in selected if item in valid_ids]
    draft = _set_draft(ctx, uid, "ab_service", service_ids=selected)
    selected_set = set(selected)
    total_price = 0
    total_duration = 0
    rows: list[list[Btn]] = []
    for service in services:
        sid = int(service["id"])
        chosen = sid in selected_set
        if chosen:
            total_price += int(service["price"] or 0)
            total_duration += int(service["duration"] or 0)
        rows.append([
            Btn(
                f"{'✅' if chosen else '➕'} {service['name'][:20]} · {money(service['price'])}",
                callback_data=f"adm:ab_svc_toggle:{sid}",
            )
        ])
    text = (
        "💈 Шаг 3 из 6. Выберите услуги (можно несколько).\n\n"
        f"Клиент: <b>{esc(draft.get('name', ''))}</b> · {esc(draft.get('phone', ''))}\n"
    )
    if selected:
        text += f"\nВыбрано: <b>{len(selected)}</b> · {total_duration} мин · <b>{money(total_price)}</b>\n"
        rows.append([Btn("➡️ Продолжить", callback_data="adm:ab_svc_done")])
    rows.append([Btn("← Телефон", callback_data="adm:ab_ask_phone")])
    rows.append([Btn("❌ Отмена", callback_data="adm:ab_cancel")])
    await edit_q(q, text, Kb(rows))


async def ab_show_masters(ctx: Ctx, q, uid: int) -> None:
    draft = _draft(ctx, uid)
    if not draft.get("service_id"):
        await ab_show_services(ctx, q, uid)
        return
    masters = await ctx.db.list_masters(active_only=True)
    draft = _set_draft(ctx, uid, "ab_master")
    text = (
        "👨‍💈 Шаг 4 из 6. Выберите мастера.\n\n"
        f"Клиент: <b>{esc(draft.get('name', ''))}</b>\n"
        f"Услуга: <b>{esc(draft.get('service_name', ''))}</b>\n\n"
        "Можно выбрать «любой» — сервер назначит свободного."
    )
    rows = [[Btn("👥 Любой свободный", callback_data="adm:ab_master:0")]]
    for master in masters:
        rows.append([
            Btn(
                f"👨‍💈 {master['name'][:22]}",
                callback_data=f"adm:ab_master:{master['id']}",
            )
        ])
    rows.append([Btn("← Услуга", callback_data="adm:ab_ask_service")])
    rows.append([Btn("❌ Отмена", callback_data="adm:ab_cancel")])
    await edit_q(q, text, Kb(rows))


def _ab_dates(ctx: Ctx) -> list[str]:
    today = datetime.now(ctx.cfg.tz).date()
    return [(today + timedelta(days=offset)).isoformat() for offset in range(14)]


async def ab_show_dates(ctx: Ctx, q, uid: int) -> None:
    draft = _draft(ctx, uid)
    if not draft.get("service_id"):
        await ab_show_services(ctx, q, uid)
        return
    if draft.get("master_id") is None and not draft.get("master_choice"):
        await ab_show_masters(ctx, q, uid)
        return
    _set_draft(ctx, uid, "ab_date")
    text = (
        "📅 Шаг 5 из 6. Выберите дату.\n\n"
        f"Клиент: <b>{esc(draft.get('name', ''))}</b>\n"
        f"Услуга: <b>{esc(draft.get('service_name', ''))}</b> · {esc(draft.get('master_name') or 'любой свободный')}\n\n"
        "Время покажем на следующем шаге."
    )
    rows: list[list[Btn]] = []
    pair: list[Btn] = []
    for day in _ab_dates(ctx):
        label = short_date_label(day, ctx.cfg.tz).capitalize()
        pair.append(Btn(label, callback_data=f"adm:ab_date:{day}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([Btn("← Мастер", callback_data="adm:ab_ask_master")])
    rows.append([Btn("❌ Отмена", callback_data="adm:ab_cancel")])
    await edit_q(q, text, Kb(rows))


async def ab_show_times(ctx: Ctx, q, uid: int) -> None:
    draft = _draft(ctx, uid)
    day = draft.get("date")
    if not day:
        await ab_show_dates(ctx, q, uid)
        return
    service, items, service_error = await _ab_resolve_services(ctx, draft)
    if service_error or not service:
        ctx.flows.clear(uid)
        await edit_q(
            q,
            service_error or "Услуга не найдена.",
            Kb([[Btn("💈 К услугам", callback_data="adm:services")]]),
        )
        return
    draft = _set_draft(
        ctx,
        uid,
        "ab_time",
        service_id=service["id"],
        service_ids=[item["id"] for item in items],
        service_name=service["name"],
        price=service["price"],
        duration=service["duration"],
        service_items=items,
    )
    master_id = draft.get("master_id")
    slots = await ctx.db.available_slots(
        day,
        int(service["duration"] or 30),
        master_id=master_id,
    )
    _set_draft(ctx, uid, "ab_time")
    text = (
        f"🕘 Шаг 6 из 6. Время на {date_label(day)}.\n\n"
        f"{esc(service['name'])} · {esc(draft.get('master_name') or 'любой свободный')}\n\n"
    )
    if not slots:
        text += (
            "Свободных слотов нет. Выберите другую дату или другого мастера.\n"
            "Если сегодня уже поздно — на другую дату слоты будут с начала дня."
        )
        rows = [
            [Btn("📅 Другая дата", callback_data="adm:ab_ask_date")],
            [Btn("👨‍💈 Другой мастер", callback_data="adm:ab_ask_master")],
            [Btn("❌ Отмена", callback_data="adm:ab_cancel")],
        ]
        await edit_q(q, text, Kb(rows))
        return
    text += "Выберите время:"
    rows = []
    row: list[Btn] = []
    for slot in slots:
        row.append(Btn(slot, callback_data=f"adm:ab_time:{slot}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([Btn("📅 Другая дата", callback_data="adm:ab_ask_date")])
    rows.append([Btn("❌ Отмена", callback_data="adm:ab_cancel")])
    await edit_q(q, text, Kb(rows))


async def ab_ask_comment(ctx: Ctx, q, uid: int) -> None:
    ctx.flows.set(uid, "ab_comment", draft=_draft(ctx, uid))
    await edit_q(
        q,
        "📝 Комментарий к записи.\n\n"
        "Например: «просил не трогать длину сверху». Можно пропустить.",
        Kb([
            [Btn("⏭ Пропустить", callback_data="adm:ab_skip_comment")],
            [Btn("← Время", callback_data="adm:ab_ask_time")],
            [Btn("❌ Отмена", callback_data="adm:ab_cancel")],
        ]),
    )


def ab_summary_text(ctx: Ctx, draft: dict) -> str:
    lines = [
        "📋 <b>Проверьте запись</b>",
        "",
        f"👤 <b>{esc(draft.get('name', ''))}</b>",
        f"📞 {esc(draft.get('phone', ''))}",
        f"💈 {esc(draft.get('service_name', ''))} · {money(draft.get('price', 0))} · {draft.get('duration', 0)} мин",
    ]
    items = draft.get("service_items")
    if isinstance(items, list) and len(items) > 1:
        for item in items:
            lines.append(
                f"• {esc(item.get('name', ''))} · {money(item.get('price', 0))} · {item.get('duration', 0)} мин"
            )
    lines += [
        f"👨‍💈 {esc(draft.get('master_name') or 'любой свободный')}",
        f"📅 {date_label(draft.get('date', ''))}, <b>{esc(draft.get('time', ''))}</b>",
    ]
    if draft.get("comment"):
        lines.append(f"📝 {esc(draft['comment'])}")
    lines += [
        "",
        "Создавая запись, вы подтверждаете, что клиент согласен "
        "с политикой обработки персональных данных.",
    ]
    return "\n".join(lines)


async def ab_show_confirm(ctx: Ctx, q, uid: int) -> None:
    draft = _draft(ctx, uid)
    missing = [key for key in ("name", "phone", "service_id", "date", "time") if not draft.get(key)]
    if missing:
        ctx.flows.clear(uid)
        await edit_q(
            q,
            "Данные записи потерялись. Начните заново.",
            Kb([[Btn("➕ Новая запись", callback_data="adm:ab_start")]]),
        )
        return
    _set_draft(ctx, uid, "ab_confirm")
    await edit_q(
        q,
        ab_summary_text(ctx, draft),
        Kb([
            [Btn("✅ Создать", callback_data="adm:ab_save:new")],
            [Btn("✅ Создать и подтвердить", callback_data="adm:ab_save:confirmed")],
            [Btn("← Комментарий", callback_data="adm:ab_ask_comment")],
            [Btn("❌ Отмена", callback_data="adm:ab_cancel")],
        ]),
    )


async def handle_admin_booking_text(ctx: Ctx, update: Update, state: str) -> bool:
    if not state.startswith("ab_"):
        return False
    message = update.effective_message
    uid = update.effective_user.id
    text = (message.text or "").strip()
    draft = _draft(ctx, uid)

    if state == "ab_name":
        name = clean_text(text, 60)
        if not (2 <= len(name) <= 60):
            await message.reply_text(
                "Имя: от 2 до 60 символов.",
                reply_markup=_cancel_kb(),
            )
            return True
        _set_draft(ctx, uid, "ab_phone", name=name)
        await ab_ask_phone_message(ctx, message, uid)
        return True

    if state == "ab_phone":
        phone = normalize_phone(text)
        if not phone:
            await message.reply_text(
                "Не похоже на телефон. Введите номер ещё раз.",
                reply_markup=_cancel_kb(),
            )
            return True
        _set_draft(ctx, uid, "ab_service", phone=display_phone(phone) or phone)
        await ab_show_services_message(ctx, message, uid)
        return True

    if state == "ab_comment":
        draft = _set_draft(
            ctx,
            uid,
            "ab_confirm",
            comment="" if text == "-" else clean_text(text, 300),
        )
        await message.reply_text(
            ab_summary_text(ctx, draft),
            parse_mode=ParseMode.HTML,
            reply_markup=Kb([
                [Btn("✅ Создать", callback_data="adm:ab_save:new")],
                [Btn("✅ Создать и подтвердить", callback_data="adm:ab_save:confirmed")],
                [Btn("← Комментарий", callback_data="adm:ab_ask_comment")],
                [Btn("❌ Отмена", callback_data="adm:ab_cancel")],
            ]),
        )
        return True

    if state == "ab_confirm":
        await message.reply_text(
            "Нажмите «Создать» или «Отмена».",
            reply_markup=Kb([
                [Btn("✅ Создать", callback_data="adm:ab_save:new")],
                [Btn("❌ Отмена", callback_data="adm:ab_cancel")],
            ]),
        )
        return True

    return False


async def ab_ask_phone_message(ctx: Ctx, message, uid: int) -> None:
    await message.reply_text(
        "📞 Телефон клиента.\n\nНапример: +7 701 234 56 78",
        reply_markup=Kb([
            [Btn("← Имя", callback_data="adm:ab_ask_name")],
            [Btn("❌ Отмена", callback_data="adm:ab_cancel")],
        ]),
    )


async def ab_show_services_message(ctx: Ctx, message, uid: int) -> None:
    services = await ctx.db.list_services()
    draft = _draft(ctx, uid)
    if not services:
        ctx.flows.clear(uid)
        await message.reply_text(
            "Сначала добавьте услугу в разделе «Услуги».",
            reply_markup=Kb([[Btn("💈 К услугам", callback_data="adm:services")]]),
        )
        return
    selected = _ab_selected_ids(draft)
    valid_ids = {int(item["id"]) for item in services}
    selected = [item for item in selected if item in valid_ids]
    _set_draft(ctx, uid, "ab_service", service_ids=selected)
    selected_set = set(selected)
    total_price = 0
    total_duration = 0
    rows = []
    for service in services:
        sid = int(service["id"])
        chosen = sid in selected_set
        if chosen:
            total_price += int(service["price"] or 0)
            total_duration += int(service["duration"] or 0)
        rows.append([
            Btn(
                f"{'✅' if chosen else '➕'} {service['name'][:20]} · {money(service['price'])}",
                callback_data=f"adm:ab_svc_toggle:{sid}",
            )
        ])
    if selected:
        rows.append([Btn("➡️ Продолжить", callback_data="adm:ab_svc_done")])
    rows.append([Btn("← Телефон", callback_data="adm:ab_ask_phone")])
    rows.append([Btn("❌ Отмена", callback_data="adm:ab_cancel")])
    text = (
        "💈 Выберите услуги (можно несколько).\n\n"
        f"Клиент: <b>{esc(draft.get('name', ''))}</b> · {esc(draft.get('phone', ''))}"
    )
    if selected:
        text += f"\n\nВыбрано: <b>{len(selected)}</b> · {total_duration} мин · <b>{money(total_price)}</b>"
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=Kb(rows))


async def ab_create(ctx: Ctx, q, uid: int, status: str) -> None:
    draft = _draft(ctx, uid)
    service, items, service_error = await _ab_resolve_services(ctx, draft)
    if service_error or not service:
        ctx.flows.clear(uid)
        await edit_q(
            q,
            service_error or "Услуга не найдена.",
            Kb([[Btn("💈 К услугам", callback_data="adm:services")]]),
        )
        return
    order, error = await ctx.db.create_order(
        name=draft.get("name", ""),
        phone=normalize_phone(draft.get("phone", "")) or draft.get("phone", ""),
        service=service,
        day=draft.get("date", ""),
        slot=draft.get("time", ""),
        channel="admin",
        comment=draft.get("comment", ""),
        source="admin",
        tg_id=None,
        master_id=draft.get("master_id"),
        consent_at=datetime.now(ctx.cfg.tz).isoformat(timespec="seconds"),
        service_items=items,
    )
    if error or not order:
        await edit_q(
            q,
            f"Не удалось создать запись: {esc(error or 'ошибка')}.\n\n"
            "Вернитесь к выбору времени.",
            Kb([
                [Btn("🕘 Выбрать время", callback_data="adm:ab_ask_time")],
                [Btn("❌ Отмена", callback_data="adm:ab_cancel")],
            ]),
        )
        return
    if status == "confirmed":
        updated = await ctx.db.set_order_status(order["id"], "confirmed", allowed_from={"new"})
        if updated:
            order = updated
    ctx.flows.clear(uid)
    detail, kb = await order_detail_screen(ctx, order["id"])
    suffix = "\n\n✅ Запись создана вручную."
    if order["status"] == "confirmed":
        suffix += " Статус: подтверждена."
    await edit_q(q, detail + suffix, kb)


async def handle_admin_booking_cb(ctx: Ctx, q, data: str) -> bool:
    uid = q.from_user.id
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    if not action.startswith("ab_"):
        return False

    if action == "ab_start":
        old = ctx.flows.data(uid)
        remove_photo(ctx, old.get("photo_tmp", ""))
        old_draft = old.get("draft") or {}
        if isinstance(old_draft, dict):
            remove_photo(ctx, old_draft.get("photo_tmp", ""))
        ctx.flows.set(uid, "ab_name", draft={})
        await ab_ask_name(ctx, q, uid)
        return True
    if action == "ab_cancel":
        ctx.flows.clear(uid)
        text, kb = await orders_screen(ctx, "upcoming", 0)
        await edit_q(q, "Создание записи отменено.\n\n" + text, kb)
        return True
    if action == "ab_ask_name":
        await ab_ask_name(ctx, q, uid)
        return True
    if action == "ab_ask_phone":
        await ab_ask_phone(ctx, q, uid)
        return True
    if action == "ab_ask_service":
        await ab_show_services(ctx, q, uid)
        return True
    if action == "ab_ask_master":
        await ab_show_masters(ctx, q, uid)
        return True
    if action == "ab_ask_date":
        await ab_show_dates(ctx, q, uid)
        return True
    if action == "ab_ask_time":
        await ab_show_times(ctx, q, uid)
        return True
    if action == "ab_ask_comment":
        await ab_ask_comment(ctx, q, uid)
        return True

    if action == "ab_svc_toggle" and len(parts) >= 3:
        try:
            service_id = int(parts[2])
        except ValueError:
            service_id = 0
        services = await ctx.db.list_services()
        valid_ids = {int(item["id"]) for item in services}
        if service_id not in valid_ids:
            await safe_answer(q, "Услуга не найдена", show_alert=True)
            return True
        draft = _draft(ctx, uid)
        selected = _ab_selected_ids(draft)
        if service_id in selected:
            selected.remove(service_id)
        else:
            selected.append(service_id)
        _set_draft(ctx, uid, "ab_service", service_ids=selected)
        await ab_show_services(ctx, q, uid)
        return True

    if action == "ab_svc_done":
        draft = _draft(ctx, uid)
        selected = _ab_selected_ids(draft)
        if not selected:
            await safe_answer(q, "Выберите хотя бы одну услугу", show_alert=True)
            return True
        service, items, service_error = await _ab_apply_services(
            ctx, uid, "ab_master", selected
        )
        if service_error or not service:
            await edit_q(
                q,
                service_error or "Услуги больше недоступны. Выберите заново.",
                Kb([[Btn("← К услугам", callback_data="adm:ab_ask_service")]]),
            )
            return True
        await ab_show_masters(ctx, q, uid)
        return True

    if action == "ab_svc" and len(parts) >= 3:
        service = await ctx.db.get_service(int(parts[2]))
        if not service:
            await safe_answer(q, "Услуга не найдена", show_alert=True)
            return True
        _set_draft(
            ctx,
            uid,
            "ab_master",
            service_id=service["id"],
            service_ids=[service["id"]],
            service_name=service["name"],
            price=service["price"],
            duration=service["duration"],
            service_items=service_items([service]),
            master_id=None,
            master_name="",
            master_choice=False,
            date="",
            time="",
        )
        await ab_show_masters(ctx, q, uid)
        return True

    if action == "ab_master" and len(parts) >= 3:
        try:
            master_id = int(parts[2])
        except ValueError:
            master_id = 0
        if master_id:
            master = await ctx.db.get_master(master_id)
            if not master or not int(master.get("active") or 0):
                await safe_answer(q, "Мастер недоступен", show_alert=True)
                return True
            _set_draft(
                ctx,
                uid,
                "ab_date",
                master_id=master_id,
                master_name=master["name"],
                master_choice=True,
                date="",
                time="",
            )
        else:
            _set_draft(
                ctx,
                uid,
                "ab_date",
                master_id=None,
                master_name="",
                master_choice=True,
                date="",
                time="",
            )
        await ab_show_dates(ctx, q, uid)
        return True

    if action == "ab_date" and len(parts) >= 3:
        day = valid_iso_date(parts[2])
        if not day:
            await safe_answer(q, "Некорректная дата", show_alert=True)
            return True
        _set_draft(ctx, uid, "ab_time", date=day, time="")
        await ab_show_times(ctx, q, uid)
        return True

    if action == "ab_time" and len(parts) >= 3:
        slot = valid_time(":".join(parts[2:]))
        draft = _draft(ctx, uid)
        if not slot or not draft.get("date"):
            await safe_answer(q, "Некорректное время", show_alert=True)
            return True
        service, items, service_error = await _ab_resolve_services(ctx, draft)
        if service_error or not service:
            await safe_answer(q, service_error or "Услуга не найдена", show_alert=True)
            return True
        slots = await ctx.db.available_slots(
            draft["date"],
            int(service["duration"] or 30),
            master_id=draft.get("master_id"),
        )
        if slot not in slots:
            await safe_answer(q, "Это время уже занято", show_alert=True)
            await ab_show_times(ctx, q, uid)
            return True
        _set_draft(ctx, uid, "ab_comment", time=slot)
        await ab_ask_comment(ctx, q, uid)
        return True

    if action == "ab_skip_comment":
        _set_draft(ctx, uid, "ab_confirm", comment="")
        await ab_show_confirm(ctx, q, uid)
        return True

    if action == "ab_save" and len(parts) >= 3:
        status = "confirmed" if parts[2] == "confirmed" else "new"
        await ab_create(ctx, q, uid, status)
        return True

    await safe_answer(q, "Действие не найдено", show_alert=True)
    return True
