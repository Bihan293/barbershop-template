from __future__ import annotations
from .deps import *
from .scheduling import schedule_label

# ============================================================
# Мастера: экраны админки
# ============================================================

WEEKDAY_TITLES = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")


async def master_today_state(ctx: Ctx, master: dict) -> str:
    if not int(master.get("active") or 0):
        return "отключён"
    now = datetime.now(ctx.cfg.tz)
    day = now.date().isoformat()
    if await ctx.db.get_day_off(int(master["id"]), day):
        return "сегодня выходной"
    schedule = await ctx.db.get_master_schedule_day(int(master["id"]), now.weekday())
    if not schedule or not int(schedule.get("enabled") or 0):
        return "сегодня выходной"
    settings = await ctx.db.get_settings()
    return f"сегодня {settings.get('work_start', '10:00')}–{settings.get('work_end', '21:00')}"


async def masters_screen(ctx: Ctx) -> tuple[str, Kb]:
    masters = await ctx.db.list_masters()
    lines = ["👨‍💈 <b>Мастера</b>", f"Всего: {len(masters)}", ""]
    rows: list[list[Btn]] = []
    for master in masters:
        state = await master_today_state(ctx, master)
        marker = "🟢" if int(master.get("active") or 0) else "⚪️"
        lines.append(f"{marker} <b>{esc(master['name'])}</b> · {esc(state)}")
        if master.get("description"):
            lines.append(f"<i>{esc(master['description'])[:110]}</i>")
        lines.append("")
        rows.append([
            Btn(
                f"{marker} {master['name'][:14]} · {state[:10]}",
                callback_data=f"adm:mst:{master['id']}",
            )
        ])
    if not masters:
        lines.append("Мастеров пока нет. Добавьте первого — он появится на сайте и в записи.")
    rows.append([Btn("➕ Добавить мастера", callback_data="adm:mst_add")])
    rows.append([Btn("← В админ-панель", callback_data="adm:home")])
    return "\n".join(lines), Kb(rows)


def master_break_label(master: dict) -> str:
    start = str(master.get("break_start") or "")
    end = str(master.get("break_end") or "")
    if start and end:
        return f"{start}–{end}"
    return "нет"


def master_detail_text(
    master: dict, schedules: list[dict], days_off: list[dict], today_state: str, settings: dict
) -> str:
    weekly_off = [WEEKDAYS[int(row["weekday"])] for row in schedules if not int(row.get("enabled") or 0)]
    lines = [
        f"👨‍💈 <b>{esc(master['name'])}</b>",
        f"Статус: <b>{'работает' if int(master.get('active') or 0) else 'отключён'}</b>"
        + (f" · {esc(today_state)}" if int(master.get("active") or 0) else ""),
        "",
        f"{esc(master.get('description')) or 'Без описания'}",
        "",
        f"🖼 Фото: {'есть' if master.get('photo') else 'нет'}",
        "",
        f"🕘 Часы салона: <b>{settings.get('work_start', '10:00')}–{settings.get('work_end', '21:00')}</b>",
        f"🍽 Перерыв: <b>{master_break_label(master)}</b> · на все дни",
        f"🚫 Постоянные выходные: {', '.join(weekly_off) if weekly_off else 'нет'}",
        "",
        "Часы работы общие — из «Настроек». Перерыв у каждого мастера свой.",
        "",
    ]
    if days_off:
        lines.append("<b>Ближайшие выходные</b>")
        for item in days_off[:5]:
            lines.append(f"• {date_label(item['date'])}" + (f" · {esc(item['reason'])}" if item.get("reason") else ""))
    else:
        lines.append("Ближайших выходных нет.")
    return "\n".join(lines)


def master_detail_kb(master: dict, today_off: bool = False) -> Kb:
    mid = int(master["id"])
    active = int(master.get("active") or 0)
    rows = [
        [
            Btn("⚪️ Отключить" if active else "🟢 Включить", callback_data=f"adm:mst_active:{mid}"),
            Btn("🟢 Снять выходной" if today_off else "🌙 Сегодня выходной",
                callback_data=f"adm:mst_todayoff:{mid}"),
        ],
        [
            Btn("✏️ Имя", callback_data=f"adm:mst_edit:{mid}:name"),
            Btn("📝 Описание", callback_data=f"adm:mst_edit:{mid}:description"),
        ],
        [
            Btn("🖼 Фото", callback_data=f"adm:mst_photo:{mid}"),
            Btn("🍽 Перерыв", callback_data=f"adm:mst_break:{mid}"),
        ],
    ]
    if master.get("photo"):
        rows.append([Btn("🗑 Удалить фото", callback_data=f"adm:mst_photo_del:{mid}")])
    rows += [
        [Btn("🚫 Выходные по дням", callback_data=f"adm:mst_weekoff:{mid}")],
        [Btn("🌴 Разовые выходные", callback_data=f"adm:mst_days:{mid}")],
        [Btn("🗑 Удалить мастера", callback_data=f"adm:mst_del:{mid}")],
        [Btn("← К мастерам", callback_data="adm:masters")],
    ]
    return Kb(rows)


async def show_master_detail(ctx: Ctx, q, master_id: int, suffix: str = "") -> None:
    master = await ctx.db.get_master(master_id)
    if not master:
        await edit_q(q, "Мастер не найден.", Kb([[Btn("← К мастерам", callback_data="adm:masters")]]))
        return
    schedules = await ctx.db.get_master_schedule(master_id)
    days_off = await ctx.db.list_days_off(master_id)
    today_state = await master_today_state(ctx, master)
    today_off = bool(await ctx.db.get_day_off(master_id, datetime.now(ctx.cfg.tz).date().isoformat()))
    settings = await ctx.db.get_settings()
    text = master_detail_text(master, schedules, days_off, today_state, settings)
    if suffix:
        text += "\n\n" + suffix
    await replace_admin_screen(
        ctx,
        q,
        text,
        master_detail_kb(master, today_off=today_off),
        photo_rel=master.get("photo", ""),
        caption=f"{esc(master['name'])} · мастер",
        photo_caption=text,
        user_id=q.from_user.id,
    )


async def master_break_screen(ctx: Ctx, master_id: int) -> tuple[str, Kb]:
    master = await ctx.db.get_master(master_id)
    if not master:
        return "Мастер не найден.", Kb([[Btn("← К мастерам", callback_data="adm:masters")]])
    settings = await ctx.db.get_settings()
    current = master_break_label(master)
    text = (
        f"🍽 <b>Перерыв · {esc(master['name'])}</b>\n\n"
        f"Сейчас: <b>{current}</b>\n\n"
        f"Рабочие часы салона: <b>{settings.get('work_start', '10:00')}–{settings.get('work_end', '21:00')}</b>\n"
        "Один перерыв действует на все дни недели.\n"
        "Если перерыва нет — слоты идут без обеда."
    )
    rows: list[list[Btn]] = [
        [Btn("✏️ Изменить перерыв", callback_data=f"adm:mst_break_edit:{master_id}")],
    ]
    if master.get("break_start") or master.get("break_end"):
        rows.append([
            Btn("🗑 Убрать перерыв", callback_data=f"adm:mst_break_clear:{master_id}")
        ])
    rows.append([Btn("← К мастеру", callback_data=f"adm:mst:{master_id}")])
    return text, Kb(rows)


async def master_schedule_screen(ctx: Ctx, master_id: int) -> tuple[str, Kb]:
    master = await ctx.db.get_master(master_id)
    if not master:
        return "Мастер не найден.", Kb([[Btn("← К мастерам", callback_data="adm:masters")]])
    schedules = await ctx.db.get_master_schedule(master_id)
    lines = [
        f"📅 <b>График · {esc(master['name'])}</b>",
        "",
        "Нажмите на день, чтобы изменить часы, перерывы или сделать его выходным.",
        "Постоянные выходные по дням недели — в разделе «Выходные по дням».",
        "Изменения графика не отменяют уже созданные записи — проверьте «Заказы».",
        "",
    ]
    rows: list[list[Btn]] = []
    for row in schedules:
        weekday = int(row["weekday"])
        lines.append(f"{WEEKDAY_TITLES[weekday]}: <b>{esc(schedule_label(row))}</b>")
        rows.append([
            Btn(
                f"{WEEKDAYS[weekday]} · {schedule_label(row)}",
                callback_data=f"adm:mst_day:{master_id}:{weekday}",
            )
        ])
    rows.append([Btn("← К мастеру", callback_data=f"adm:mst:{master_id}")])
    return "\n".join(lines), Kb(rows)


async def master_day_screen(ctx: Ctx, master_id: int, weekday: int) -> tuple[str, Kb]:
    master = await ctx.db.get_master(master_id)
    schedule = await ctx.db.get_master_schedule_day(master_id, weekday)
    if not master or not schedule:
        return "День графика не найден.", Kb([[Btn("← К графику", callback_data=f"adm:mst_sched:{master_id}")]])
    enabled = bool(int(schedule.get("enabled") or 0))
    breaks = await ctx.db.list_master_breaks(master_id, weekday)
    break_lines = [
        f"• {esc(item.get('title') or 'Перерыв')} {item['break_start']}–{item['break_end']}"
        for item in breaks
    ] or ["нет"]
    text = (
        f"📅 <b>{WEEKDAY_TITLES[weekday]} · {esc(master['name'])}</b>\n\n"
        f"Рабочий день: <b>{'да' if enabled else 'нет'}</b>\n"
        f"Часы: <b>{schedule['work_start']}–{schedule['work_end']}</b>\n"
        f"Перерывы и обеды: <b>{', '.join(break_lines)}</b>\n\n"
        "Если день выключен, он выходной каждую неделю — запись недоступна. "
        "Перерывов может быть несколько."
    )
    rows = [
        [
            Btn("⚪️ Сделать выходным" if enabled else "🟢 Сделать рабочим",
                callback_data=f"adm:mst_day_toggle:{master_id}:{weekday}"),
        ],
        [
            Btn("🕘 Начало", callback_data=f"adm:mst_day_edit:{master_id}:{weekday}:work_start"),
            Btn("🕘 Конец", callback_data=f"adm:mst_day_edit:{master_id}:{weekday}:work_end"),
        ],
    ]
    for item in breaks:
        rows.append([
            Btn(
                f"🗑 {item['break_start']}–{item['break_end']}",
                callback_data=f"adm:mst_break_del:{item['id']}:{master_id}:{weekday}",
            )
        ])
    rows.append([Btn("➕ Добавить перерыв", callback_data=f"adm:mst_break_add:{master_id}:{weekday}")])
    rows.append([Btn("← К графику", callback_data=f"adm:mst_sched:{master_id}")])
    return text, Kb(rows)


async def master_weekoff_screen(ctx: Ctx, master_id: int) -> tuple[str, Kb]:
    master = await ctx.db.get_master(master_id)
    if not master:
        return "Мастер не найден.", Kb([[Btn("← К мастерам", callback_data="adm:masters")]])
    schedules = await ctx.db.get_master_schedule(master_id)
    by_day = {int(row["weekday"]): row for row in schedules}
    off_days = [WEEKDAYS[index] for index in range(7) if not int(by_day.get(index, {}).get("enabled") or 0)]
    lines = [
        f"🚫 <b>Постоянные выходные · {esc(master['name'])}</b>",
        "",
        "Нажмите день, чтобы сделать его выходным навсегда. "
        "Например, суббота — и мастер больше не принимает в субботу.",
        "",
        f"Сейчас выходные: <b>{', '.join(off_days) if off_days else 'нет'}</b>",
        "",
    ]
    rows = []
    for index, title in enumerate(WEEKDAY_TITLES):
        row = by_day.get(index)
        working = bool(row and int(row.get("enabled") or 0))
        lines.append(f"{title}: {'рабочий' if working else 'выходной'}")
        rows.append([
            Btn(
                f"{WEEKDAYS[index]} · {'🟢 рабочий' if working else '🌙 выходной'}",
                callback_data=f"adm:mst_week_toggle:{master_id}:{index}",
            )
        ])
    rows.append([Btn("← К мастеру", callback_data=f"adm:mst:{master_id}")])
    return "\n".join(lines), Kb(rows)


async def master_days_screen(ctx: Ctx, master_id: int) -> tuple[str, Kb]:
    master = await ctx.db.get_master(master_id)
    if not master:
        return "Мастер не найден.", Kb([[Btn("← К мастерам", callback_data="adm:masters")]])
    today = datetime.now(ctx.cfg.tz).date()
    end = (today + timedelta(days=14)).isoformat()
    days_off = await ctx.db.list_days_off(master_id, today.isoformat(), end)
    off_map = {str(item["date"]): item for item in days_off}
    lines = [
        f"🌴 <b>Разовые выходные · {esc(master['name'])}</b>",
        "",
        "Нажмите на дату, чтобы отметить выходной или вернуть мастера в график.",
        "Например, если он заболел сегодня — нажмите «Сегодня».",
        "",
    ]
    rows: list[list[Btn]] = []
    pair: list[Btn] = []
    for offset in range(15):
        day = today + timedelta(days=offset)
        iso = day.isoformat()
        marker = "🌙" if iso in off_map else "•"
        label = "Сегодня" if offset == 0 else ("Завтра" if offset == 1 else f"{day.day} {MONTHS_GEN[day.month - 1][:3]}, {WEEKDAYS[day.weekday()]}")
        pair.append(Btn(f"{marker} {label}", callback_data=f"adm:mst_dayoff:{master_id}:{iso}"))
        if len(pair) == 3:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    if days_off:
        lines.append("<b>Отмечено</b>")
        for item in days_off:
            lines.append(f"• {date_label(item['date'])}" + (f" · {esc(item['reason'])}" if item.get("reason") else ""))
    else:
        lines.append("Выходных пока нет.")
    rows.append([Btn("← К мастеру", callback_data=f"adm:mst:{master_id}")])
    return "\n".join(lines), Kb(rows)
