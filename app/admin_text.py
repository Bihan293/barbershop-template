from __future__ import annotations
from .deps import *
from .admin_ui import *

# ============================================================
# Текстовые сценарии админа
# ============================================================

def service_preview(draft: dict) -> str:
    return (
        "💈 <b>Проверьте услугу</b>\n\n"
        f"<b>{esc(draft.get('name', ''))}</b>\n"
        f"{esc(draft.get('description', '')) or 'Без описания'}\n\n"
        f"💰 {money(draft.get('price', 0))} · ⏱ {draft.get('duration', 60)} мин\n"
        f"🖼 Фото: {'прикреплено' if draft.get('photo_tmp') else 'нет'}"
    )


def review_preview(draft: dict) -> str:
    rating = int(draft.get("rating", 5))
    return (
        "⭐ <b>Проверьте отзыв</b>\n\n"
        f"{'★' * rating}{'☆' * (5 - rating)}\n"
        f"<b>{esc(draft.get('name', ''))}</b> · {esc(draft.get('source', '2ГИС'))}\n\n"
        f"<i>{esc(draft.get('text', ''))}</i>"
    )


def contact_validate(key: str, raw: str) -> tuple[Optional[str], Optional[str]]:
    text = clean_text(raw, 500)
    if key == "brand":
        return (text, None) if 2 <= len(text) <= 24 else (None, "Название: от 2 до 24 символов — коротко, как на вывеске.")
    if key == "city":
        return (text, None) if 2 <= len(text) <= 40 else (None, "Город: от 2 до 40 символов.")
    if key == "address":
        return (text, None) if 3 <= len(text) <= 120 else (None, "Адрес: от 3 до 120 символов.")
    if key == "address_note":
        if text == "-":
            text = ""
        return (text[:120], None)
    if key == "hours":
        return (text, None) if 3 <= len(text) <= 100 else (None, "Часы: от 3 до 100 символов.")
    if key == "hours_note":
        if text == "-":
            text = ""
        return (text[:100], None)
    if key == "phone":
        normalized = normalize_phone(text)
        if not normalized:
            return None, "Телефон: минимум 10 цифр."
        return display_phone(normalized) or normalized, None
    if key == "whatsapp":
        digits = phone_digits(text)
        if len(digits) < 10 or len(digits) > 15:
            return None, "WhatsApp: укажите номер, например 77001234567."
        return digits, None
    if key == "twogis_url":
        if text == "-":
            return "", None
        url = valid_url(text)
        return (url, None) if url else (None, "Ссылка должна начинаться с http:// или https://")
    if key == "instagram":
        if text == "-":
            return "", None
        url = normalize_instagram(text)
        return (url, None) if url else (None, "Укажите @ник или ссылку на Instagram.")
    return None, "Неизвестное поле."


def contact_preview(key: str, old: str, new: str) -> str:
    label = CONTACT_MAP.get(key, (key, ""))[0]
    return (
        f"📍 <b>Изменить «{esc(label)}»</b>\n\n"
        f"Было: {esc(old) or '—'}\n"
        f"Станет: <b>{esc(new) or '—'}</b>"
    )


def setting_validate(ctx: Ctx, key: str, raw: str, settings: dict) -> tuple[Optional[str], Optional[str]]:
    text = clean_text(raw, 40)
    if key == "privacy_updated":
        return (text, None) if 4 <= len(text) <= 20 else (None, "Дата: от 4 до 20 символов, например 15.11.2026.")
    if key == "reminder_minutes":
        number = int_in_range(text, 15, 720)
        if number is None:
            return None, "Напоминание: от 15 до 720 минут."
        return str(number), None
    value = valid_time(text)
    if not value:
        return None, "Время в формате ЧЧ:ММ, например 10:00."
    minutes = hhmm_to_min(value)
    work_start = hhmm_to_min(settings.get("work_start", "10:00"))
    last_slot = hhmm_to_min(settings.get("last_slot", "20:00"))
    work_end = hhmm_to_min(settings.get("work_end", "21:00"))
    lunch_start = hhmm_to_min(settings.get("lunch_start", "13:00"))
    lunch_end = hhmm_to_min(settings.get("lunch_end", "14:00"))
    if key == "work_start":
        if not (
            minutes < min(last_slot, work_end)
            and (lunch_start < 0 or minutes <= lunch_start)
        ):
            return None, "Открытие должно быть раньше обеда, последнего слота и закрытия."
    elif key == "last_slot":
        if not (work_start < minutes < work_end):
            return None, "Последний старт должен быть между открытием и закрытием."
    elif key == "work_end":
        boundary = max(last_slot, lunch_end if lunch_end >= 0 else last_slot)
        if not (minutes > boundary):
            return None, "Закрытие должно быть позже обеда и последнего старта."
    elif key == "lunch_start":
        if not (work_start <= minutes < lunch_end <= work_end):
            return None, "Начало обеда должно быть между открытием и концом обеда."
    elif key == "lunch_end":
        if not (work_start <= lunch_start < minutes <= work_end):
            return None, "Конец обеда должен быть позже начала обеда и не позже закрытия."
    return value, None


SETTING_LABELS = {
    "work_start": "Открытие салона",
    "work_end": "Закрытие салона",
    "lunch_start": "Начало общего обеда",
    "lunch_end": "Конец общего обеда",
    "last_slot": "Последний старт записи",
    "reminder_minutes": "Напоминание, минут",
    "privacy_updated": "Дата редакции политики",
}


async def handle_admin_text(ctx: Ctx, update: Update, state: str) -> None:
    message = update.effective_message
    uid = update.effective_user.id
    await clear_admin_media(ctx, uid)
    text = (message.text or "").strip()
    data = ctx.flows.data(uid)

    # ---------- добавление услуги ----------
    if state == "svc_add_name":
        name = clean_text(text, 80)
        if not (2 <= len(name) <= 80):
            await message.reply_text("Название: от 2 до 80 символов.", reply_markup=cancel_row("adm:svc_add_cancel"))
            return
        draft = data.get("draft", {})
        draft["name"] = name
        ctx.flows.set(uid, "svc_add_desc", draft=draft)
        await message.reply_text(
            "Описание услуги. Отправьте «-», чтобы оставить пустым.",
            reply_markup=cancel_row("adm:svc_add_cancel"),
        )
        return

    if state == "svc_add_desc":
        draft = data.get("draft", {})
        draft["description"] = "" if text == "-" else clean_text(text, 400)
        ctx.flows.set(uid, "svc_add_price", draft=draft)
        await message.reply_text(
            "Цена в тенге, только число. Например: 4000",
            reply_markup=cancel_row("adm:svc_add_cancel"),
        )
        return

    if state == "svc_add_price":
        price = money_number(text)
        if price is None:
            await message.reply_text("Цена: число от 0 до 10 000 000.", reply_markup=cancel_row("adm:svc_add_cancel"))
            return
        draft = data.get("draft", {})
        draft["price"] = price
        ctx.flows.set(uid, "svc_add_duration", draft=draft)
        await message.reply_text(
            "Длительность в минутах (15–240). Например: 60",
            reply_markup=cancel_row("adm:svc_add_cancel"),
        )
        return

    if state == "svc_add_duration":
        duration = int_in_range(text, 15, 240)
        if duration is None:
            await message.reply_text("Длительность: от 15 до 240 минут.", reply_markup=cancel_row("adm:svc_add_cancel"))
            return
        draft = data.get("draft", {})
        draft["duration"] = duration
        ctx.flows.set(uid, "svc_add_photo", draft=draft)
        await message.reply_text(
            "Отправьте фото услуги или нажмите «Пропустить». Фото появится на сайте.",
            reply_markup=Kb([
                [Btn("⏭ Пропустить", callback_data="adm:svc_add_skip")],
                [Btn("❌ Отмена", callback_data="adm:svc_add_cancel")],
            ]),
        )
        return

    if state == "svc_add_photo":
        if text == "-":
            await send_service_add_preview(ctx, message, uid)
            return
        await message.reply_text("Здесь нужно фото. Отправьте изображение или нажмите «Пропустить».")
        return

    # ---------- редактирование услуги ----------
    if state == "svc_edit_value":
        service_id = int(data.get("service_id", 0))
        field = data.get("field", "")
        value: Any = None
        if field == "name":
            candidate = clean_text(text, 80)
            value = candidate if 2 <= len(candidate) <= 80 else None
        elif field == "description":
            value = "" if text == "-" else clean_text(text, 400)
        elif field == "price":
            value = money_number(text)
        elif field == "duration":
            value = int_in_range(text, 15, 240)
        if value is None:
            await message.reply_text("Некорректное значение. Попробуйте ещё раз.", reply_markup=cancel_row(f"adm:svc:{service_id}"))
            return
        ctx.flows.set(uid, "svc_edit_save", service_id=service_id, field=field, value=value)
        old = await ctx.db.get_service(service_id)
        if not old:
            ctx.flows.clear(uid)
            await message.reply_text("Услуга не найдена.", reply_markup=Kb([[Btn("← К услугам", callback_data="adm:services")]]))
            return
        label = {"name": "Название", "description": "Описание", "price": "Цена", "duration": "Длительность"}[field]
        new_text = value if field != "price" else money(value)
        await message.reply_text(
            f"💈 <b>Проверьте изменение</b>\n\n{label}\n"
            f"Было: {esc(old.get(field))}\nСтанет: <b>{esc(new_text)}</b>",
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:svc_edit_save")],
                [Btn("❌ Отмена", callback_data=f"adm:svc:{service_id}")],
            ]),
        )
        return

    if state == "svc_edit_photo":
        await message.reply_text("Отправьте новое фото услуги.")
        return

    # ---------- галерея ----------
    if state == "gal_add_caption":
        draft = data.get("draft", {})
        draft["caption"] = "" if text == "-" else clean_text(text, 100)
        ctx.flows.set(uid, "gal_add_save", draft=draft)
        await send_gallery_preview(ctx, message, uid, draft, "Новое фото")
        return

    if state == "gal_add_photo":
        await message.reply_text("Здесь нужно фото. Отправьте изображение.")
        return

    if state == "gal_edit_caption":
        item_id = int(data.get("item_id", 0))
        caption = "" if text == "-" else clean_text(text, 100)
        ctx.flows.set(uid, "gal_caption_save", item_id=item_id, caption=caption)
        item = await ctx.db.get_gallery(item_id)
        if not item:
            ctx.flows.clear(uid)
            await message.reply_text("Фото не найдено.", reply_markup=Kb([[Btn("← К галерее", callback_data="adm:gallery")]]))
            return
        await message.reply_text(
            f"🖼 <b>Изменить подпись</b>\n\nБыло: {esc(item['caption']) or '—'}\n"
            f"Станет: <b>{esc(caption) or 'без подписи'}</b>",
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:gal_caption_save")],
                [Btn("❌ Отмена", callback_data=f"adm:gal:{item_id}")],
            ]),
        )
        return

    if state == "gal_edit_photo":
        await message.reply_text("Отправьте новое фото для галереи.")
        return

    # ---------- отзывы ----------
    if state == "rev_add_name":
        name = clean_text(text, 60)
        if not (2 <= len(name) <= 60):
            await message.reply_text("Имя: от 2 до 60 символов.", reply_markup=cancel_row("adm:rev_add_cancel"))
            return
        draft = data.get("draft", {})
        draft["name"] = name
        ctx.flows.set(uid, "rev_add_text", draft=draft)
        await message.reply_text("Текст отзыва:", reply_markup=cancel_row("adm:rev_add_cancel"))
        return

    if state == "rev_add_text":
        if len(text) < 5:
            await message.reply_text("Текст отзыва: минимум 5 символов.", reply_markup=cancel_row("adm:rev_add_cancel"))
            return
        draft = data.get("draft", {})
        draft["text"] = clean_text(text, 500)
        ctx.flows.set(uid, "rev_add_rating", draft=draft)
        await message.reply_text(
            "Оцените отзыв:",
            reply_markup=Kb([
                [Btn("1", callback_data="adm:rev_rating:1"), Btn("2", callback_data="adm:rev_rating:2"),
                 Btn("3", callback_data="adm:rev_rating:3"), Btn("4", callback_data="adm:rev_rating:4"),
                 Btn("5", callback_data="adm:rev_rating:5")],
                [Btn("❌ Отмена", callback_data="adm:rev_add_cancel")],
            ]),
        )
        return

    if state == "rev_add_source":
        draft = data.get("draft", {})
        draft["source"] = clean_text(text, 60) or "2ГИС"
        ctx.flows.set(uid, "rev_add_save", draft=draft)
        await message.reply_text(
            review_preview(draft),
            parse_mode=ParseMode.HTML,
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:rev_add_save")],
                [Btn("❌ Отмена", callback_data="adm:rev_add_cancel")],
            ]),
        )
        return

    if state == "rev_edit_value":
        review_id = int(data.get("review_id", 0))
        field = data.get("field", "")
        value: Any = None
        if field == "name":
            candidate = clean_text(text, 60)
            value = candidate if 2 <= len(candidate) <= 60 else None
        elif field == "text":
            value = clean_text(text, 500) if len(text) >= 5 else None
        elif field == "rating":
            value = int_in_range(text, 1, 5)
        elif field == "source":
            value = clean_text(text, 60) or "2ГИС"
        if value is None:
            await message.reply_text("Некорректное значение. Попробуйте ещё раз.", reply_markup=cancel_row(f"adm:rev:{review_id}"))
            return
        ctx.flows.set(uid, "rev_edit_save", review_id=review_id, field=field, value=value)
        old = await ctx.db.get_review(review_id)
        if not old:
            ctx.flows.clear(uid)
            await message.reply_text("Отзыв не найден.", reply_markup=Kb([[Btn("← К отзывам", callback_data="adm:reviews")]]))
            return
        new_text = value if field != "rating" else f"{value}/5"
        await message.reply_text(
            f"⭐ <b>Проверьте изменение</b>\n\n{esc(old.get(field))}\n→ <b>{esc(new_text)}</b>",
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:rev_edit_save")],
                [Btn("❌ Отмена", callback_data=f"adm:rev:{review_id}")],
            ]),
        )
        return

    # ---------- почему мы ----------
    if state == "why_add_icon":
        icon = text.strip()
        if not (1 <= len(icon) <= 8):
            await message.reply_text("Иконка: 1–8 символов, например ✂️.", reply_markup=cancel_row("adm:why_add_cancel"))
            return
        draft = data.get("draft", {})
        draft["icon"] = icon
        ctx.flows.set(uid, "why_add_title", draft=draft)
        await message.reply_text(
            "Заголовок карточки. Например: «Мастера, а не исполнители».",
            reply_markup=cancel_row("adm:why_add_cancel"),
        )
        return

    if state == "why_add_title":
        title = clean_text(text, 80)
        if not (3 <= len(title) <= 80):
            await message.reply_text("Заголовок: от 3 до 80 символов.", reply_markup=cancel_row("adm:why_add_cancel"))
            return
        draft = data.get("draft", {})
        draft["title"] = title
        ctx.flows.set(uid, "why_add_text", draft=draft)
        await message.reply_text(
            "Текст карточки: 10–300 символов.",
            reply_markup=cancel_row("adm:why_add_cancel"),
        )
        return

    if state == "why_add_text":
        body = clean_text(text, 300)
        if not (10 <= len(body) <= 300):
            await message.reply_text("Текст: от 10 до 300 символов.", reply_markup=cancel_row("adm:why_add_cancel"))
            return
        draft = data.get("draft", {})
        draft["text"] = body
        ctx.flows.set(uid, "why_add_save", draft=draft)
        await message.reply_text(
            why_preview(draft),
            parse_mode=ParseMode.HTML,
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:why_add_save")],
                [Btn("❌ Отмена", callback_data="adm:why_add_cancel")],
            ]),
        )
        return

    if state == "why_edit_value":
        item_id = int(data.get("item_id", 0))
        field = data.get("field", "")
        value: Any = None
        if field == "icon":
            candidate = text.strip()
            value = candidate if 1 <= len(candidate) <= 8 else None
        elif field == "title":
            candidate = clean_text(text, 80)
            value = candidate if 3 <= len(candidate) <= 80 else None
        elif field == "text":
            candidate = clean_text(text, 300)
            value = candidate if 10 <= len(candidate) <= 300 else None
        if value is None:
            await message.reply_text("Некорректное значение. Попробуйте ещё раз.", reply_markup=cancel_row(f"adm:why:{item_id}"))
            return
        ctx.flows.set(uid, "why_edit_save", item_id=item_id, field=field, value=value)
        old = await ctx.db.get_why(item_id)
        if not old:
            ctx.flows.clear(uid)
            await message.reply_text("Карточка не найдена.", reply_markup=Kb([[Btn("← К «Почему мы»", callback_data="adm:whys")]]))
            return
        await message.reply_text(
            f"💡 <b>Проверьте изменение</b>\n\n"
            f"Было: {esc(old.get(field))}\n"
            f"Станет: <b>{esc(value)}</b>",
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:why_edit_save")],
                [Btn("❌ Отмена", callback_data=f"adm:why:{item_id}")],
            ]),
        )
        return

    # ---------- цифры и достижения на сайте ----------
    if state == "stat_add_value":
        value = clean_text(text, 24)
        if not (1 <= len(value) <= 24):
            await message.reply_text(
                "Значение: от 1 до 24 символов. Например 50, 3000, 4.9 или ЗНАМЕНИТОСТИ.",
                reply_markup=cancel_row("adm:stat_add_cancel"),
            )
            return
        draft = data.get("draft", {})
        draft["value"] = value
        ctx.flows.set(uid, "stat_add_label", draft=draft)
        await message.reply_text(
            "Шаг 2 из 3. Подпись под значением.\n\n"
            "Например: «точек|по всему миру» или «стригутся|у нас». "
            "Символ «|» переносит строку.",
            reply_markup=cancel_row("adm:stat_add_cancel"),
        )
        return

    if state == "stat_add_label":
        label = clean_text(text, 80)
        if not (1 <= len(label) <= 80):
            await message.reply_text(
                "Подпись: от 1 до 80 символов.",
                reply_markup=cancel_row("adm:stat_add_cancel"),
            )
            return
        draft = data.get("draft", {})
        draft["label"] = label
        ctx.flows.set(uid, "stat_add_save", draft=draft)
        await message.reply_text(
            stat_add_preview_text(draft),
            parse_mode=ParseMode.HTML,
            reply_markup=stat_add_preview_kb(draft),
        )
        return

    if state == "stat_edit_value":
        stat_id = int(data.get("stat_id", 0))
        field = data.get("field", "")
        value: Any = None
        if field == "value":
            candidate = clean_text(text, 24)
            value = candidate if 1 <= len(candidate) <= 24 else None
        elif field == "label":
            candidate = clean_text(text, 80)
            value = candidate if 1 <= len(candidate) <= 80 else None
        if value is None:
            await message.reply_text(
                "Некорректное значение. Попробуйте ещё раз.",
                reply_markup=cancel_row(f"adm:stat:{stat_id}"),
            )
            return
        item = await ctx.db.get_site_stat(stat_id)
        if not item:
            ctx.flows.clear(uid)
            await message.reply_text(
                "Достижение не найдено.",
                reply_markup=Kb([[Btn("← К цифрам", callback_data="adm:site_stats")]]),
            )
            return
        old = item.get(field, "")
        old_display = stat_display_label(old) if field == "label" else old
        new_display = stat_display_label(value) if field == "label" else value
        ctx.flows.set(uid, "stat_edit_save", stat_id=stat_id, field=field, value=value)
        await message.reply_text(
            "🏆 <b>Проверьте изменение</b>\n\n"
            f"Было: {esc(old_display)}\n"
            f"Станет: <b>{esc(new_display)}</b>",
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:stat_edit_save")],
                [Btn("❌ Отмена", callback_data=f"adm:stat:{stat_id}")],
            ]),
        )
        return

    # ---------- цифры на сайте ----------
    if state == "stat_value":
        key = data.get("key", "")
        value: Any = None
        if key in {"stat_years", "stat_clients"}:
            value = int_in_range(text, 0, 10_000_000)
        elif key == "stat_rating":
            try:
                rating = float(text.replace(",", "."))
                value = f"{rating:.1f}" if 0 <= rating <= 5 else None
            except ValueError:
                value = None
        elif key in {"stat_years_label", "stat_clients_label", "stat_rating_label"}:
            candidate = clean_text(text, 60)
            value = candidate if 1 <= len(candidate) <= 60 else None
        if value is None:
            await message.reply_text(
                "Некорректное значение. Для рейтинга — число от 0 до 5, "
                "для подписи — текст до 60 символов.",
                reply_markup=cancel_row("adm:site_stats"),
            )
            return
        ctx.flows.set(uid, "stat_save", key=key, value=value)
        settings = await ctx.db.get_settings()
        old = settings.get(key, "")
        await message.reply_text(
            "🏆 <b>Проверьте цифру</b>\n\n"
            f"Было: {esc(stat_display_label(old))}\n"
            f"Станет: <b>{esc(stat_display_label(value))}</b>",
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:stat_save")],
                [Btn("❌ Отмена", callback_data="adm:site_stats")],
            ]),
        )
        return

    # ---------- контакты ----------
    if state == "con_value":
        key = data.get("key", "")
        value, error = contact_validate(key, text)
        if error:
            await message.reply_text(error, reply_markup=cancel_row("adm:contacts"))
            return
        settings = await ctx.db.get_settings()
        old = settings.get(key, "")
        if key == "whatsapp":
            old = display_phone(old)
        ctx.flows.set(uid, "con_save", key=key, value=value)
        await message.reply_text(
            contact_preview(key, old, value or ""),
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:con_save")],
                [Btn("❌ Отмена", callback_data="adm:contacts")],
            ]),
        )
        return

    # ---------- настройки ----------
    if state == "set_value":
        key = data.get("key", "")
        settings = await ctx.db.get_settings()
        value, error = setting_validate(ctx, key, text, settings)
        if error:
            await message.reply_text(error, reply_markup=cancel_row("adm:settings"))
            return
        ctx.flows.set(uid, "set_save", key=key, value=value)
        await message.reply_text(
            f"⚙️ <b>Проверьте изменение</b>\n\n"
            f"{SETTING_LABELS.get(key, key)}\n"
            f"Было: {esc(settings.get(key, ''))}\n"
            f"Станет: <b>{esc(value)}</b>",
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:set_save")],
                [Btn("❌ Отмена", callback_data="adm:settings")],
            ]),
        )
        return

    # Если это состояние сохранения — текст не требуется.
    await message.reply_text(
        "Используйте кнопки ниже или отправьте /cancel, чтобы выйти.",
        reply_markup=Kb([[Btn("← В админ-панель", callback_data="adm:home")]]),
    )


async def send_service_add_preview(ctx: Ctx, message, uid: int) -> None:
    draft = ctx.flows.data(uid).get("draft", {})
    ctx.flows.set(uid, "svc_add_save", draft=draft)
    await message.reply_text(
        service_preview(draft),
        parse_mode=ParseMode.HTML,
        reply_markup=Kb([
            [Btn("✅ Сохранить", callback_data="adm:svc_add_save")],
            [Btn("❌ Отмена", callback_data="adm:svc_add_cancel")],
        ]),
    )


async def send_gallery_preview(ctx: Ctx, message, uid: int, draft: dict, title: str) -> None:
    temp = draft.get("photo_tmp", "")
    path = photo_path(ctx, temp)
    if not path:
        await message.reply_text("Фото не найдено. Начните добавление заново.")
        ctx.flows.clear(uid)
        return
    caption = (
        f"<b>{esc(title)}</b>\n"
        f"{esc(draft.get('caption', '')) or 'Без подписи'}"
    )
    with open(path, "rb") as photo_file:
        sent = await message.reply_photo(
            photo=photo_file,
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
    register_admin_media(ctx, uid, message.chat_id, sent)
    await message.reply_text(
        "Сохранить это фото в галерею?",
        reply_markup=Kb([
            [Btn("✅ Сохранить", callback_data="adm:gal_add_save")],
            [Btn("❌ Отмена", callback_data="adm:gal_add_cancel")],
        ]),
    )
