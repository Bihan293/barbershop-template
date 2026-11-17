from __future__ import annotations
from .deps import *
from .masters_ui import (
    master_break_screen,
    master_day_screen,
    master_days_screen,
    master_schedule_screen,
    master_weekoff_screen,
    masters_screen,
    show_master_detail,
)
from .master_text import master_add_preview
from .masters_ui import WEEKDAY_TITLES
from .master_notifications import notify_master_orders

# ============================================================
# Мастера: callback-и
# ============================================================


async def _orders_for_master_weekday(
    ctx: Ctx, master_id: int, weekday: int
) -> list[dict]:
    orders = await ctx.db.future_orders_for_master(master_id)
    result = []
    for order in orders:
        try:
            day = datetime.strptime(str(order["date"]), "%Y-%m-%d")
        except (TypeError, ValueError):
            continue
        if day.weekday() == int(weekday):
            result.append(order)
    return result


async def handle_master_cb(ctx: Ctx, q, data: str) -> bool:
    uid = q.from_user.id
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action not in {"masters", "mst"} and not action.startswith("mst_"):
        return False

    if action in {
        "mst_sched", "mst_day", "mst_day_toggle", "mst_day_edit",
        "mst_sched_save", "mst_day_nolunch", "mst_break_add",
        "mst_break_save", "mst_break_del", "mst_break_delok",
    }:
        await safe_answer(
            q,
            "Часы и обед теперь общие: Настройки → Часы работы / Обед.",
            show_alert=True,
        )
        return True

    if action == "masters":
        ctx.flows.clear(uid)
        text, kb = await masters_screen(ctx)
        await edit_q(q, text, kb)
        return True

    if action == "mst" and len(parts) >= 3:
        ctx.flows.clear(uid)
        await show_master_detail(ctx, q, int(parts[2]))
        return True

    # ---------- общий перерыв мастера ----------
    if action == "mst_break" and len(parts) >= 3:
        ctx.flows.clear(uid)
        text, kb = await master_break_screen(ctx, int(parts[2]))
        await edit_q(q, text, kb)
        return True

    if action == "mst_break_edit" and len(parts) >= 3:
        master_id = int(parts[2])
        master = await ctx.db.get_master(master_id)
        if not master:
            await safe_answer(q, "Мастер не найден", show_alert=True)
            return True
        ctx.flows.set(uid, "mst_common_break_value", master_id=master_id)
        await edit_q(
            q,
            "🍽 Введите перерыв в формате <b>13:00-14:00</b>.\n\n"
            "Он будет действовать у этого мастера каждый день.\n"
            "Отправьте «-», чтобы убрать перерыв.",
            cancel_row(f"adm:mst_break:{master_id}"),
        )
        return True

    if action == "mst_break_clear" and len(parts) >= 3:
        master_id = int(parts[2])
        master = await ctx.db.get_master(master_id)
        if not master:
            await safe_answer(q, "Мастер не найден", show_alert=True)
            return True
        await edit_q(
            q,
            f"🗑 <b>Убрать перерыв у мастера {esc(master['name'])}?</b>\n\n"
            "Слоты в это время снова станут доступны.",
            Kb([
                [Btn("✅ Да, убрать", callback_data=f"adm:mst_break_clearok:{master_id}")],
                [Btn("← Нет, назад", callback_data=f"adm:mst_break:{master_id}")],
            ]),
        )
        return True

    if action == "mst_break_clearok" and len(parts) >= 3:
        master_id = int(parts[2])
        await ctx.db.update_master(master_id, break_start="", break_end="")
        ctx.flows.clear(uid)
        text, kb = await master_break_screen(ctx, master_id)
        await edit_q(q, "✅ Перерыв убран.\n\n" + text, kb)
        return True

    if action == "mst_break_common_save":
        data_now = ctx.flows.data(uid)
        master_id = int(data_now.get("master_id", 0))
        start = data_now.get("start", "")
        end = data_now.get("end", "")
        await ctx.db.update_master(master_id, break_start=start, break_end=end)
        ctx.flows.clear(uid)
        text, kb = await master_break_screen(ctx, master_id)
        await edit_q(q, f"✅ Перерыв {start}–{end} сохранён на все дни.\n\n" + text, kb)
        return True

    # ---------- добавление ----------
    if action == "mst_add":
        remove_photo(ctx, ctx.flows.data(uid).get("photo_tmp", ""))
        ctx.flows.set(uid, "mst_add_name", draft={})
        await edit_q(
            q,
            "➕ <b>Новый мастер</b>\n\nШаг 1 из 3. Введите имя мастера:",
            cancel_row("adm:mst_add_cancel"),
        )
        return True

    if action == "mst_add_cancel":
        draft = ctx.flows.data(uid).get("draft", {})
        remove_photo(ctx, draft.get("photo_tmp", ""))
        ctx.flows.clear(uid)
        text, kb = await masters_screen(ctx)
        await edit_q(q, "Добавление мастера отменено.\n\n" + text, kb)
        return True

    if action == "mst_add_skip":
        draft = ctx.flows.data(uid).get("draft", {})
        ctx.flows.set(uid, "mst_add_save", draft=draft)
        await edit_q(
            q,
            master_add_preview(draft),
            Kb([
                [Btn("✅ Сохранить", callback_data="adm:mst_add_save")],
                [Btn("❌ Отмена", callback_data="adm:mst_add_cancel")],
            ]),
        )
        return True

    if action == "mst_add_save":
        draft = ctx.flows.data(uid).get("draft", {})
        if not draft.get("name"):
            await safe_answer(q, "Заполните имя мастера", show_alert=True)
            return True
        photo = move_photo(ctx, draft.get("photo_tmp", ""), "masters")
        master_id = await ctx.db.add_master(
            name=draft["name"],
            description=draft.get("description", ""),
            photo=photo,
        )
        ctx.flows.clear(uid)
        await show_master_detail(
            ctx,
            q,
            master_id,
            suffix="✅ Мастер добавлен. Часы работы и обед — общие, из «Настроек».",
        )
        return True

    # ---------- имя и описание ----------
    if action == "mst_edit" and len(parts) >= 4:
        master_id = int(parts[2])
        field = parts[3]
        if field not in {"name", "description"}:
            await safe_answer(q, "Неизвестное поле", show_alert=True)
            return True
        master = await ctx.db.get_master(master_id)
        if not master:
            await safe_answer(q, "Мастер не найден", show_alert=True)
            return True
        ctx.flows.set(uid, "mst_edit_value", master_id=master_id, field=field)
        label = "имя" if field == "name" else "описание (можно отправить «-», чтобы очистить)"
        current = master.get(field) or "—"
        await edit_q(
            q,
            f"✏️ Введите {label}.\n\nСейчас: <b>{esc(current)}</b>",
            cancel_row(f"adm:mst:{master_id}"),
        )
        return True

    if action == "mst_edit_save":
        data_now = ctx.flows.data(uid)
        master_id = int(data_now.get("master_id", 0))
        field = data_now.get("field", "")
        value = data_now.get("value")
        if field in {"name", "description"}:
            await ctx.db.update_master(master_id, **{field: value})
        ctx.flows.clear(uid)
        await show_master_detail(ctx, q, master_id, suffix="✅ Изменения сохранены.")
        return True

    # ---------- фото ----------
    if action == "mst_photo" and len(parts) >= 3:
        master_id = int(parts[2])
        master = await ctx.db.get_master(master_id)
        if not master:
            await safe_answer(q, "Мастер не найден", show_alert=True)
            return True
        ctx.flows.set(uid, "mst_photo", master_id=master_id)
        await edit_q(
            q,
            f"🖼 Отправьте фото мастера «{esc(master['name'])}».\n\n"
            "Лучше вертикальное фото, где видно лицо.",
            cancel_row(f"adm:mst:{master_id}"),
        )
        return True

    if action == "mst_photo_save":
        data_now = ctx.flows.data(uid)
        master_id = int(data_now.get("master_id", 0))
        master = await ctx.db.get_master(master_id)
        if not master:
            remove_photo(ctx, data_now.get("photo_tmp", ""))
            ctx.flows.clear(uid)
            await safe_answer(q, "Мастер не найден", show_alert=True)
            return True
        new_photo = move_photo(ctx, data_now.get("photo_tmp", ""), "masters")
        if not new_photo:
            ctx.flows.clear(uid)
            await edit_q(
                q,
                "Фото не найдено. Откройте мастера и загрузите изображение заново.",
                Kb([[Btn("← К мастеру", callback_data=f"adm:mst:{master_id}")]]),
            )
            return True
        await ctx.db.update_master(master_id, photo=new_photo)
        if master.get("photo"):
            remove_photo(ctx, master["photo"])
        ctx.flows.clear(uid)
        await show_master_detail(ctx, q, master_id, suffix="✅ Фото мастера обновлено.")
        return True

    if action == "mst_photo_del" and len(parts) >= 3:
        master_id = int(parts[2])
        master = await ctx.db.get_master(master_id)
        if not master:
            await safe_answer(q, "Мастер не найден", show_alert=True)
            return True
        if not master.get("photo"):
            await safe_answer(q, "У мастера уже нет фото", show_alert=True)
            return True
        await edit_q(
            q,
            f"🗑 <b>Удалить фото мастера?</b>\n\n{esc(master['name'])}\n\n"
            "Фото исчезнет с сайта. Имя, описание и перерыв останутся.",
            Kb([
                [Btn("✅ Да, удалить", callback_data=f"adm:mst_photo_delok:{master_id}")],
                [Btn("← Нет, назад", callback_data=f"adm:mst:{master_id}")],
            ]),
        )
        return True

    if action == "mst_photo_delok" and len(parts) >= 3:
        master_id = int(parts[2])
        master = await ctx.db.get_master(master_id)
        if master and master.get("photo"):
            remove_photo(ctx, master["photo"])
            await ctx.db.update_master(master_id, photo="")
        ctx.flows.clear(uid)
        await show_master_detail(ctx, q, master_id, suffix="✅ Фото удалено.")
        return True

    # ---------- вкл / выкл ----------
    if action == "mst_active" and len(parts) >= 3:
        master_id = int(parts[2])
        master = await ctx.db.get_master(master_id)
        if not master:
            await safe_answer(q, "Мастер не найден", show_alert=True)
            return True
        active = bool(int(master.get("active") or 0))
        if active:
            today = datetime.now(ctx.cfg.tz).date().isoformat()
            row = await ctx.db.fetchone(
                "SELECT COUNT(*) AS c FROM orders WHERE master_id=? "
                "AND status IN ('new','confirmed') AND date>=?",
                (master_id, today),
            )
            upcoming = int(row["c"]) if row else 0
            text = (
                f"⚪️ <b>Отключить мастера?</b>\n\n{esc(master['name'])}\n\n"
                "Новые записи к нему перестанут приниматься, он исчезнет с сайта. "
                "Существующие записи останутся в календаре."
            )
            if upcoming:
                text += f"\n\n⚠️ У него {upcoming} активных записей — их нужно будет перенести или отменить."
        else:
            text = (
                f"🟢 <b>Включить мастера?</b>\n\n{esc(master['name'])}\n\n"
                "Он снова появится на сайте и в записи согласно графику."
            )
        await edit_q(
            q,
            text,
            Kb([
                [Btn("✅ Да", callback_data=f"adm:mst_active_ok:{master_id}")],
                [Btn("← Нет, назад", callback_data=f"adm:mst:{master_id}")],
            ]),
        )
        return True

    if action == "mst_active_ok" and len(parts) >= 3:
        master_id = int(parts[2])
        master = await ctx.db.get_master(master_id)
        if not master:
            await safe_answer(q, "Мастер не найден", show_alert=True)
            return True
        active = 0 if int(master.get("active") or 0) else 1
        await ctx.db.update_master(master_id, active=active)
        if not active:
            orders = await ctx.db.future_orders_for_master(master_id)
            await notify_master_orders(
                ctx,
                master,
                orders,
                "отключён и не сможет принять запись",
            )
        ctx.flows.clear(uid)
        suffix = "✅ Мастер включён." if active else "⚪️ Мастер отключён."
        await show_master_detail(ctx, q, master_id, suffix=suffix)
        return True

    if action == "mst_todayoff" and len(parts) >= 3:
        master_id = int(parts[2])
        today = datetime.now(ctx.cfg.tz).date().isoformat()
        is_off = await ctx.db.toggle_day_off(master_id, today, "выходной")
        if is_off:
            master = await ctx.db.get_master(master_id)
            orders = await ctx.db.orders_for_master_date(master_id, today)
            if master:
                await notify_master_orders(
                    ctx,
                    master,
                    orders,
                    f"не работает сегодня ({date_label(today)})",
                )
        suffix = (
            "🌙 Сегодня отмечен как выходной. Новые записи на сегодня закрыты."
            if is_off
            else "🟢 Отметка выходного на сегодня снята. Дальше действует график недели."
        )
        if is_off:
            row = await ctx.db.fetchone(
                "SELECT COUNT(*) AS c FROM orders WHERE master_id=? AND date=? "
                "AND status IN ('new','confirmed')",
                (master_id, today),
            )
            count = int(row["c"]) if row else 0
            if count:
                suffix += f"\n\n⚠️ На сегодня у него {count} записей — свяжитесь с клиентами или перенесите их."
        await show_master_detail(ctx, q, master_id, suffix=suffix)
        return True

    # ---------- график ----------
    if action == "mst_sched" and len(parts) >= 3:
        ctx.flows.clear(uid)
        master_id = int(parts[2])
        text, kb = await master_schedule_screen(ctx, master_id)
        await edit_q(q, text, kb)
        return True

    if action == "mst_day" and len(parts) >= 4:
        ctx.flows.clear(uid)
        master_id = int(parts[2])
        weekday = int(parts[3])
        text, kb = await master_day_screen(ctx, master_id, weekday)
        await edit_q(q, text, kb)
        return True

    if action == "mst_day_toggle" and len(parts) >= 4:
        master_id = int(parts[2])
        weekday = int(parts[3])
        schedule = await ctx.db.get_master_schedule_day(master_id, weekday)
        if not schedule:
            await safe_answer(q, "День не найден", show_alert=True)
            return True
        enabled = 0 if int(schedule.get("enabled") or 0) else 1
        await ctx.db.save_master_schedule(
            master_id,
            weekday,
            enabled=enabled,
            start=schedule["work_start"],
            end=schedule["work_end"],
            lunch_start="",
            lunch_end="",
        )
        if not enabled:
            master = await ctx.db.get_master(master_id)
            orders = await _orders_for_master_weekday(ctx, master_id, weekday)
            if master:
                await notify_master_orders(
                    ctx,
                    master,
                    orders,
                    f"не работает по {WEEKDAY_TITLES[weekday].lower()} каждую неделю",
                )
        text, kb = await master_day_screen(ctx, master_id, weekday)
        prefix = "✅ День включён.\n\n" if enabled else (
            "🌙 День выключен. Существующие записи не отменяются.\n\n"
        )
        await edit_q(q, prefix + text, kb)
        return True

    if action == "mst_day_edit" and len(parts) >= 5:
        master_id = int(parts[2])
        weekday = int(parts[3])
        field = parts[4]
        if field not in {"work_start", "work_end"}:
            await safe_answer(q, "Неизвестное поле", show_alert=True)
            return True
        schedule = await ctx.db.get_master_schedule_day(master_id, weekday)
        if not schedule:
            await safe_answer(q, "День не найден", show_alert=True)
            return True
        labels = {
            "work_start": "начало рабочего дня",
            "work_end": "конец рабочего дня",
        }
        ctx.flows.set(
            uid,
            "mst_sched_value",
            master_id=master_id,
            weekday=weekday,
            field=field,
        )
        current = schedule.get(field) or "не задано"
        await edit_q(
            q,
            f"🕘 Введите {labels[field]} в формате ЧЧ:ММ.\n\n"
            f"Сейчас: <b>{esc(current)}</b>",
            cancel_row(f"adm:mst_day:{master_id}:{weekday}"),
        )
        return True

    if action == "mst_sched_save":
        data_now = ctx.flows.data(uid)
        master_id = int(data_now.get("master_id", 0))
        weekday = int(data_now.get("weekday", 0))
        field = data_now.get("field", "")
        value = data_now.get("value", "")
        schedule = await ctx.db.get_master_schedule_day(master_id, weekday)
        if schedule and field in {"work_start", "work_end"}:
            updated = dict(schedule)
            updated[field] = value
            await ctx.db.save_master_schedule(
                master_id,
                weekday,
                enabled=int(schedule.get("enabled") or 0),
                start=updated["work_start"],
                end=updated["work_end"],
                lunch_start="",
                lunch_end="",
            )
        ctx.flows.clear(uid)
        text, kb = await master_day_screen(ctx, master_id, weekday)
        await edit_q(q, "✅ График обновлён.\n\n" + text, kb)
        return True

    if action == "mst_day_nolunch" and len(parts) >= 4:
        master_id = int(parts[2])
        weekday = int(parts[3])
        schedule = await ctx.db.get_master_schedule_day(master_id, weekday)
        if schedule:
            await ctx.db.save_master_schedule(
                master_id,
                weekday,
                enabled=int(schedule.get("enabled") or 0),
                start=schedule["work_start"],
                end=schedule["work_end"],
                lunch_start="",
                lunch_end="",
            )
        text, kb = await master_day_screen(ctx, master_id, weekday)
        await edit_q(q, "✅ Обед убран.\n\n" + text, kb)
        return True

    # ---------- перерывы ----------
    if action == "mst_break_add" and len(parts) >= 4:
        master_id = int(parts[2])
        weekday = int(parts[3])
        if weekday not in range(7):
            await safe_answer(q, "Некорректный день недели", show_alert=True)
            return True
        if not await ctx.db.get_master(master_id):
            await safe_answer(q, "Мастер не найден", show_alert=True)
            return True
        ctx.flows.set(uid, "mst_break_value", master_id=master_id, weekday=weekday)
        await edit_q(
            q,
            "➕ <b>Новый перерыв</b>\n\n"
            "Введите начало и конец, например: <b>12:00-13:00</b>.\n"
            "Перерывов может быть несколько.",
            cancel_row(f"adm:mst_day:{master_id}:{weekday}"),
        )
        return True

    if action == "mst_break_save":
        data_now = ctx.flows.data(uid)
        master_id = int(data_now.get("master_id", 0))
        weekday = int(data_now.get("weekday", 0))
        start = data_now.get("start", "")
        end = data_now.get("end", "")
        if not await ctx.db.get_master(master_id):
            ctx.flows.clear(uid)
            await safe_answer(q, "Мастер не найден", show_alert=True)
            return True
        await ctx.db.add_master_break(master_id, weekday, start, end)
        ctx.flows.clear(uid)
        text, kb = await master_day_screen(ctx, master_id, weekday)
        await edit_q(q, f"✅ Перерыв {start}–{end} добавлен.\n\n" + text, kb)
        return True

    if action == "mst_break_del" and len(parts) >= 5:
        break_id = int(parts[2])
        master_id = int(parts[3])
        weekday = int(parts[4])
        item = await ctx.db.get_master_break(break_id)
        if not item:
            await safe_answer(q, "Перерыв не найден", show_alert=True)
            return True
        await edit_q(
            q,
            f"🗑 <b>Удалить перерыв {item['break_start']}–{item['break_end']}?</b>\n\n"
            "Слоты внутри этого времени снова станут доступны.",
            Kb([
                [Btn("✅ Да, удалить", callback_data=f"adm:mst_break_delok:{break_id}:{master_id}:{weekday}")],
                [Btn("← Нет, назад", callback_data=f"adm:mst_day:{master_id}:{weekday}")],
            ]),
        )
        return True

    if action == "mst_break_delok" and len(parts) >= 5:
        break_id = int(parts[2])
        master_id = int(parts[3])
        weekday = int(parts[4])
        await ctx.db.delete_master_break(break_id)
        text, kb = await master_day_screen(ctx, master_id, weekday)
        await edit_q(q, "✅ Перерыв удалён.\n\n" + text, kb)
        return True

    # ---------- выходные ----------
    if action == "mst_weekoff" and len(parts) >= 3:
        ctx.flows.clear(uid)
        master_id = int(parts[2])
        text, kb = await master_weekoff_screen(ctx, master_id)
        await edit_q(q, text, kb)
        return True

    if action == "mst_week_toggle" and len(parts) >= 4:
        ctx.flows.clear(uid)
        master_id = int(parts[2])
        weekday = int(parts[3])
        if weekday not in range(7):
            await safe_answer(q, "Некорректный день недели", show_alert=True)
            return True
        if not await ctx.db.get_master(master_id):
            await safe_answer(q, "Мастер не найден", show_alert=True)
            return True
        schedule = await ctx.db.get_master_schedule_day(master_id, weekday)
        if not schedule:
            await safe_answer(q, "День не найден", show_alert=True)
            return True
        enabled = 0 if int(schedule.get("enabled") or 0) else 1
        await ctx.db.save_master_schedule(
            master_id,
            weekday,
            enabled=enabled,
            start=schedule["work_start"],
            end=schedule["work_end"],
            lunch_start="",
            lunch_end="",
        )
        if not enabled:
            master = await ctx.db.get_master(master_id)
            orders = await _orders_for_master_weekday(ctx, master_id, weekday)
            if master:
                await notify_master_orders(
                    ctx,
                    master,
                    orders,
                    f"не работает по {WEEKDAY_TITLES[weekday].lower()} каждую неделю",
                )
        suffix = ""
        if not enabled:
            suffix = " ⚠️ Существующие записи на этот день недели не отменяются — проверьте «Заказы»."
        else:
            suffix = " 🟢 День снова рабочий каждую неделю."
        text, kb = await master_weekoff_screen(ctx, master_id)
        prefix = (
            f"🌙 <b>{WEEKDAY_TITLES[weekday]} теперь выходной каждую неделю.</b>"
            if not enabled
            else f"🟢 <b>{WEEKDAY_TITLES[weekday]} снова рабочий каждую неделю.</b>"
        )
        await edit_q(q, prefix + suffix + "\n\n" + text, kb)
        return True

    if action == "mst_days" and len(parts) >= 3:
        ctx.flows.clear(uid)
        master_id = int(parts[2])
        text, kb = await master_days_screen(ctx, master_id)
        await edit_q(q, text, kb)
        return True

    if action == "mst_dayoff" and len(parts) >= 4:
        master_id = int(parts[2])
        day = valid_iso_date(parts[3])
        if not day:
            await safe_answer(q, "Некорректная дата", show_alert=True)
            return True
        is_off = await ctx.db.toggle_day_off(master_id, day, "выходной")
        if is_off:
            master = await ctx.db.get_master(master_id)
            orders = await ctx.db.orders_for_master_date(master_id, day)
            if master:
                await notify_master_orders(
                    ctx,
                    master,
                    orders,
                    f"не работает {date_label(day)}",
                )
        text, kb = await master_days_screen(ctx, master_id)
        prefix = (
            f"🌙 {date_label(day)} — выходной.\n\n"
            if is_off
            else f"🟢 {date_label(day)} — снова рабочий день.\n\n"
        )
        if is_off:
            row = await ctx.db.fetchone(
                "SELECT COUNT(*) AS c FROM orders WHERE master_id=? AND date=? "
                "AND status IN ('new','confirmed')",
                (master_id, day),
            )
            count = int(row["c"]) if row else 0
            if count:
                prefix += f"⚠️ На этот день есть {count} записей — свяжитесь с клиентами или перенесите их.\n\n"
        await edit_q(q, prefix + text, kb)
        return True

    # ---------- удаление ----------
    if action == "mst_del" and len(parts) >= 3:
        master_id = int(parts[2])
        master = await ctx.db.get_master(master_id)
        if not master:
            await safe_answer(q, "Мастер не найден", show_alert=True)
            return True
        today = datetime.now(ctx.cfg.tz).date().isoformat()
        row = await ctx.db.fetchone(
            "SELECT COUNT(*) AS c FROM orders WHERE master_id=? "
            "AND status IN ('new','confirmed') AND date>=?",
            (master_id, today),
        )
        upcoming = int(row["c"]) if row else 0
        if upcoming:
            await edit_q(
                q,
                f"⚠️ <b>Нельзя удалить мастера</b>\n\n"
                f"У «{esc(master['name'])}» {upcoming} активных записей. "
                "Сначала перенесите или отмените их. Если мастер просто уходит — "
                "отключите его, история сохранится.",
                Kb([[Btn("← К мастеру", callback_data=f"adm:mst:{master_id}")]]),
            )
            return True
        await edit_q(
            q,
            f"🗑 <b>Удалить мастера?</b>\n\n<b>{esc(master['name'])}</b>\n\n"
            "График и выходные тоже удалятся. Фото будет удалено с диска. "
            "Старые заказы сохранят имя мастера.",
            Kb([
                [Btn("✅ Да, удалить", callback_data=f"adm:mst_delok:{master_id}")],
                [Btn("← Нет, назад", callback_data=f"adm:mst:{master_id}")],
            ]),
        )
        return True

    if action == "mst_delok" and len(parts) >= 3:
        master_id = int(parts[2])
        master, error = await ctx.db.delete_master(master_id)
        if error:
            await edit_q(
                q,
                f"⚠️ {esc(error)}",
                Kb([[Btn("← К мастеру", callback_data=f"adm:mst:{master_id}")]]),
            )
            return True
        if master and master.get("photo"):
            remove_photo(ctx, master["photo"])
        ctx.flows.clear(uid)
        text, kb = await masters_screen(ctx)
        await edit_q(q, "✅ Мастер удалён.\n\n" + text, kb)
        return True

    await safe_answer(q, "Действие не найдено", show_alert=True)
    return True
