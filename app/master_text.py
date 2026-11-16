from __future__ import annotations
from .deps import *
from .masters_ui import WEEKDAY_TITLES

# ============================================================
# Мастера: текстовые сценарии
# ============================================================


def master_add_preview(draft: dict) -> str:
    return (
        "👨‍💈 <b>Проверьте мастера</b>\n\n"
        f"<b>{esc(draft.get('name', ''))}</b>\n"
        f"{esc(draft.get('description', '')) or 'Без описания'}\n\n"
        f"🖼 Фото: {'прикреплено' if draft.get('photo_tmp') else 'нет'}\n\n"
        "Часы работы и обед общие для всех мастеров — они задаются в «Настройках»."
    )


async def handle_master_text(ctx: Ctx, update: Update, state: str) -> None:
    message = update.effective_message
    uid = update.effective_user.id
    await clear_admin_media(ctx, uid)
    text = (message.text or "").strip()
    data = ctx.flows.data(uid)

    # ---------- добавление мастера ----------
    if state == "mst_add_name":
        name = clean_text(text, 60)
        if not (2 <= len(name) <= 60):
            await message.reply_text(
                "Имя мастера: от 2 до 60 символов.",
                reply_markup=cancel_row("adm:mst_add_cancel"),
            )
            return
        draft = data.get("draft", {})
        draft["name"] = name
        ctx.flows.set(uid, "mst_add_desc", draft=draft)
        await message.reply_text(
            "Описание: специализация, опыт, стиль работы. Отправьте «-», чтобы пропустить.",
            reply_markup=cancel_row("adm:mst_add_cancel"),
        )
        return

    if state == "mst_add_desc":
        draft = data.get("draft", {})
        draft["description"] = "" if text == "-" else clean_text(text, 400)
        ctx.flows.set(uid, "mst_add_photo", draft=draft)
        await message.reply_text(
            "Отправьте фото мастера или пропустите этот шаг. Фото появится на сайте.",
            reply_markup=Kb([
                [Btn("⏭ Пропустить", callback_data="adm:mst_add_skip")],
                [Btn("❌ Отмена", callback_data="adm:mst_add_cancel")],
            ]),
        )
        return

    if state == "mst_add_photo":
        if text == "-":
            draft = data.get("draft", {})
            ctx.flows.set(uid, "mst_add_save", draft=draft)
            await message.reply_text(
                master_add_preview(draft),
                parse_mode=ParseMode.HTML,
                reply_markup=Kb([
                    [Btn("✅ Сохранить", callback_data="adm:mst_add_save")],
                    [Btn("❌ Отмена", callback_data="adm:mst_add_cancel")],
                ]),
            )
            return
        await message.reply_text("Здесь нужно фото. Отправьте изображение или нажмите «Пропустить».")
        return

    if state == "mst_photo":
        await message.reply_text("Здесь нужно фото. Отправьте изображение или нажмите «Отмена».")
        return

    # ---------- перерывы ----------
    if state == "mst_break_value":
        master_id = int(data.get("master_id", 0))
        weekday = int(data.get("weekday", 0))
        match = re.search(r"(\d{1,2}:\d{2})\s*(?:[-–—]|до)\s*(\d{1,2}:\d{2})", text)
        if not match:
            await message.reply_text(
                "Введите два времени через дефис, например 12:00-13:00.",
                reply_markup=cancel_row(f"adm:mst_day:{master_id}:{weekday}"),
            )
            return
        start = valid_time(match.group(1))
        end = valid_time(match.group(2))
        if not start or not end or hhmm_to_min(end) <= hhmm_to_min(start):
            await message.reply_text(
                "Конец перерыва должен быть позже начала.",
                reply_markup=cancel_row(f"adm:mst_day:{master_id}:{weekday}"),
            )
            return
        schedule = await ctx.db.get_master_schedule_day(master_id, weekday)
        if schedule:
            work_start = hhmm_to_min(schedule.get("work_start", ""), -1)
            work_end = hhmm_to_min(schedule.get("work_end", ""), -1)
            if work_start >= 0 and work_end > work_start:
                if not (work_start <= hhmm_to_min(start) and hhmm_to_min(end) <= work_end):
                    await message.reply_text(
                        f"Перерыв должен быть внутри рабочего дня {schedule['work_start']}–{schedule['work_end']}.",
                        reply_markup=cancel_row(f"adm:mst_day:{master_id}:{weekday}"),
                    )
                    return
        if await ctx.db.master_has_break_overlap(master_id, weekday, start, end):
            await message.reply_text(
                "Этот перерыв пересекается с уже добавленным. Укажите другое время.",
                reply_markup=cancel_row(f"adm:mst_day:{master_id}:{weekday}"),
            )
            return
        conflicts = await ctx.db.master_break_conflicts(master_id, weekday, start, end)
        if conflicts:
            first = conflicts[0]
            await message.reply_text(
                f"⚠️ На это время уже есть запись: "
                f"{date_label(first['date'])}, {first['time']} · {esc(first['service_name'])}.\n\n"
                "Сначала перенесите или отмените её, потом добавляйте перерыв.",
                reply_markup=cancel_row(f"adm:mst_day:{master_id}:{weekday}"),
            )
            return
        ctx.flows.set(
            uid,
            "mst_break_save",
            master_id=master_id,
            weekday=weekday,
            start=start,
            end=end,
        )
        await message.reply_text(
            f"🍽 <b>Перерыв {start}–{end}</b>\n\nСохранить?",
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:mst_break_save")],
                [Btn("❌ Отмена", callback_data=f"adm:mst_day:{master_id}:{weekday}")],
            ]),
        )
        return

    # ---------- редактирование имени / описания ----------
    if state == "mst_edit_value":
        master_id = int(data.get("master_id", 0))
        field = data.get("field", "")
        value: Any = None
        if field == "name":
            candidate = clean_text(text, 60)
            value = candidate if 2 <= len(candidate) <= 60 else None
        elif field == "description":
            value = "" if text == "-" else clean_text(text, 400)
        if value is None:
            await message.reply_text(
                "Некорректное значение. Попробуйте ещё раз.",
                reply_markup=cancel_row(f"adm:mst:{master_id}"),
            )
            return
        master = await ctx.db.get_master(master_id)
        if not master:
            ctx.flows.clear(uid)
            await message.reply_text(
                "Мастер не найден.",
                reply_markup=Kb([[Btn("← К мастерам", callback_data="adm:masters")]]),
            )
            return
        ctx.flows.set(uid, "mst_edit_save", master_id=master_id, field=field, value=value)
        label = "Имя" if field == "name" else "Описание"
        await message.reply_text(
            f"👨‍💈 <b>Проверьте изменение</b>\n\n{label}\n"
            f"Было: {esc(master.get(field)) or '—'}\n"
            f"Станет: <b>{esc(value) or '—'}</b>",
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:mst_edit_save")],
                [Btn("❌ Отмена", callback_data=f"adm:mst:{master_id}")],
            ]),
        )
        return

    # ---------- часы графика ----------
    if state == "mst_sched_value":
        master_id = int(data.get("master_id", 0))
        weekday = int(data.get("weekday", 0))
        field = data.get("field", "")
        schedule = await ctx.db.get_master_schedule_day(master_id, weekday)
        if not schedule:
            ctx.flows.clear(uid)
            await message.reply_text(
                "График не найден.",
                reply_markup=Kb([[Btn("← К мастерам", callback_data="adm:masters")]]),
            )
            return
        value = valid_time(text)
        if not value:
            await message.reply_text(
                "Время в формате ЧЧ:ММ, например 10:00.",
                reply_markup=cancel_row(f"adm:mst_day:{master_id}:{weekday}"),
            )
            return
        candidate = dict(schedule)
        candidate[field] = value
        start = hhmm_to_min(candidate.get("work_start", ""), -1)
        end = hhmm_to_min(candidate.get("work_end", ""), -1)
        if field in {"work_start", "work_end"} and not (start >= 0 and end > start):
            await message.reply_text(
                "Начало дня должно быть раньше конца.",
                reply_markup=cancel_row(f"adm:mst_day:{master_id}:{weekday}"),
            )
            return
        lunch_start = hhmm_to_min(candidate.get("lunch_start", ""), -1)
        lunch_end = hhmm_to_min(candidate.get("lunch_end", ""), -1)
        if lunch_start >= 0 and lunch_end >= 0:
            if lunch_end <= lunch_start:
                await message.reply_text(
                    "Обед должен начинаться раньше, чем заканчиваться.",
                    reply_markup=cancel_row(f"adm:mst_day:{master_id}:{weekday}"),
                )
                return
            if field in {"work_start", "work_end", "lunch_start", "lunch_end"} and not (
                start <= lunch_start and lunch_end <= end
            ):
                await message.reply_text(
                    "Обед должен находиться внутри рабочего дня.",
                    reply_markup=cancel_row(f"adm:mst_day:{master_id}:{weekday}"),
                )
                return
        labels = {
            "work_start": "Начало рабочего дня",
            "work_end": "Конец рабочего дня",
            "lunch_start": "Начало обеда",
            "lunch_end": "Конец обеда",
        }
        old = schedule.get(field) or "не задано"
        ctx.flows.set(
            uid,
            "mst_sched_save",
            master_id=master_id,
            weekday=weekday,
            field=field,
            value=value,
        )
        await message.reply_text(
            f"📅 <b>{WEEKDAY_TITLES[weekday]} · {esc(labels.get(field, field))}</b>\n\n"
            f"Было: {esc(old)}\n"
            f"Станет: <b>{esc(value)}</b>",
            reply_markup=Kb([
                [Btn("✅ Сохранить", callback_data="adm:mst_sched_save")],
                [Btn("❌ Отмена", callback_data=f"adm:mst_day:{master_id}:{weekday}")],
            ]),
        )
        return

    await message.reply_text(
        "Используйте кнопки ниже или отправьте /cancel, чтобы выйти.",
        reply_markup=Kb([[Btn("← В админ-панель", callback_data="adm:home")]]),
    )
