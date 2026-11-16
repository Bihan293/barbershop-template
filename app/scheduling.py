from __future__ import annotations
"""Расчёт свободных слотов.

Модуль намеренно не знает про SQL: на вход получает уже загруженные
мастера, графики, выходные и заказы. Так его легко тестировать отдельно
от базы и одинаково использовать для SQLite и PostgreSQL.
"""
from datetime import date as Date, datetime
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from .core import hhmm_to_min, min_to_hhmm, overlaps, WEEKDAYS

ACTIVE_STATUSES = ("new", "confirmed")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _schedule_index(schedules: Iterable[dict]) -> dict[tuple[int, int], dict]:
    index: dict[tuple[int, int], dict] = {}
    for row in schedules:
        try:
            key = (int(row["master_id"]), int(row["weekday"]))
        except (KeyError, TypeError, ValueError):
            continue
        index[key] = row
    return index


def _break_index(breaks: Iterable[dict]) -> dict[tuple[int, int], list[dict]]:
    index: dict[tuple[int, int], list[dict]] = {}
    for row in breaks:
        try:
            key = (int(row["master_id"]), int(row["weekday"]))
        except (KeyError, TypeError, ValueError):
            continue
        index.setdefault(key, []).append(row)
    return index


def _orders_by_master(orders: Iterable[dict]) -> dict[Optional[int], list[dict]]:
    grouped: dict[Optional[int], list[dict]] = {}
    for order in orders:
        master_id = order.get("master_id")
        try:
            key: Optional[int] = int(master_id) if master_id is not None else None
        except (TypeError, ValueError):
            key = None
        grouped.setdefault(key, []).append(order)
    return grouped


def master_slots(
    *,
    master: dict,
    schedule: Optional[dict],
    breaks: list[dict],
    day_off: bool,
    orders: list[dict],
    day: str,
    duration: int,
    step: int,
    last_slot: int,
    now: datetime,
    exclude_order_id: Optional[int] = None,
) -> list[str]:
    """Слоты одного мастера с учётом графика, обеда и его заказов."""
    if not _as_int(master.get("active"), 1):
        return []
    if day_off or not schedule:
        return []
    if not _as_int(schedule.get("enabled"), 1):
        return []

    start = hhmm_to_min(schedule.get("work_start", ""), -1)
    end = hhmm_to_min(schedule.get("work_end", ""), -1)
    if start < 0 or end < 0 or end <= start:
        return []

    break_windows: list[tuple[int, int]] = []
    for item in breaks:
        break_start = hhmm_to_min(item.get("break_start", ""), -1)
        break_end = hhmm_to_min(item.get("break_end", ""), -1)
        if break_start >= 0 and break_end > break_start:
            break_windows.append((break_start, break_end))
    # Совместимость со старыми базами, где обед хранился в расписании.
    lunch_start = hhmm_to_min(schedule.get("lunch_start", ""), -1)
    lunch_end = hhmm_to_min(schedule.get("lunch_end", ""), -1)
    if lunch_start >= 0 and lunch_end > lunch_start:
        break_windows.append((lunch_start, lunch_end))

    max_start = end - duration
    if 0 <= last_slot < end:
        max_start = min(max_start, last_slot)
    if max_start < start:
        return []

    today = now.date().isoformat()
    now_minutes = now.hour * 60 + now.minute
    lead = now_minutes + 15 if day == today else -1

    busy = []
    for order in orders:
        if exclude_order_id is not None and _as_int(order.get("id"), -1) == _as_int(exclude_order_id, -2):
            continue
        order_start = hhmm_to_min(order.get("time", ""), -1)
        if order_start < 0:
            continue
        busy.append((order_start, max(5, _as_int(order.get("duration"), step))))

    result: list[str] = []
    cursor = start
    while cursor <= max_start:
        if cursor <= lead:
            cursor += step
            continue
        if any(overlaps(cursor, duration, break_start, break_end - break_start) for break_start, break_end in break_windows):
            cursor += step
            continue
        if any(overlaps(cursor, duration, order_start, order_duration) for order_start, order_duration in busy):
            cursor += step
            continue
        result.append(min_to_hhmm(cursor))
        cursor += step
    return result


def compute_slots(
    *,
    day: str,
    duration: int,
    settings: dict[str, str],
    masters: list[dict],
    schedules: list[dict],
    days_off: set[tuple[int, str]],
    orders: list[dict],
    tz: ZoneInfo,
    breaks: Iterable[dict] = (),
    master_id: Optional[int] = None,
    exclude_order_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> list[str]:
    """Свободные слоты на день.

    master_id=None — объединение по всем активным мастерам («любой»).
    Если активных мастеров нет, слотов нет: записывать не к кому.
    """
    now = now or datetime.now(tz)
    try:
        selected = Date.fromisoformat(day)
    except (TypeError, ValueError):
        return []
    if selected < now.date():
        return []

    try:
        duration = max(5, min(480, int(duration or 30)))
    except (TypeError, ValueError):
        duration = 30
    try:
        step = max(5, min(120, int(settings.get("slot_step", "30") or 30)))
    except (TypeError, ValueError):
        step = 30
    last_slot = hhmm_to_min(settings.get("last_slot", ""), -1)

    weekday = selected.weekday()
    if not masters:
        # Нет ни одного мастера — записывать не к кому.
        return []

    active_masters = [m for m in masters if _as_int(m.get("active"), 1)]
    if not active_masters:
        return []

    if master_id is not None:
        wanted = _as_int(master_id, -1)
        active_masters = [m for m in active_masters if _as_int(m.get("id"), -2) == wanted]
        if not active_masters:
            return []

    # Часы работы и обед — единые для всех мастеров, из настроек.
    # Индивидуальные часы/перерывы мастеров больше не участвуют в расчёте.
    work_start = settings.get("work_start", "10:00")
    work_end = settings.get("work_end", "21:00")
    work_start_min = hhmm_to_min(work_start, -1)
    work_end_min = hhmm_to_min(work_end, -1)
    if work_start_min < 0 or work_end_min <= work_start_min:
        return []

    lunch_start = settings.get("lunch_start", "")
    lunch_end = settings.get("lunch_end", "")
    lunch_start_min = hhmm_to_min(lunch_start, -1)
    lunch_end_min = hhmm_to_min(lunch_end, -1)
    common_breaks: list[dict] = []
    if (
        lunch_start_min >= work_start_min
        and lunch_end_min > lunch_start_min
        and lunch_end_min <= work_end_min
    ):
        common_breaks = [
            {"break_start": lunch_start, "break_end": lunch_end}
        ]

    schedule_index = _schedule_index(schedules)
    orders_index = _orders_by_master(orders)
    result: set[str] = set()

    for master in active_masters:
        mid = _as_int(master.get("id"), -1)
        if mid < 0:
            continue
        schedule = schedule_index.get((mid, weekday))
        if not schedule:
            continue
        effective_schedule = dict(schedule)
        effective_schedule["work_start"] = work_start
        effective_schedule["work_end"] = work_end
        effective_schedule["lunch_start"] = ""
        effective_schedule["lunch_end"] = ""
        slots = master_slots(
            master=master,
            schedule=effective_schedule,
            breaks=common_breaks,
            day_off=(mid, day) in days_off,
            orders=orders_index.get(mid, []),
            day=day,
            duration=duration,
            step=step,
            last_slot=last_slot,
            now=now,
            exclude_order_id=exclude_order_id,
        )
        result.update(slots)
    return sorted(result)


def master_works(
    *,
    master_id: int,
    day: str,
    weekday: int,
    schedules: Iterable[dict],
    days_off: set[tuple[int, str]],
) -> bool:
    """Работает ли мастер в этот день по недельному графику."""
    mid = _as_int(master_id, -1)
    if mid < 0 or (mid, day) in days_off:
        return False
    row = _schedule_index(schedules).get((mid, weekday))
    return bool(row and _as_int(row.get("enabled"), 1))


def schedule_label(schedule: dict) -> str:
    """Короткая подпись дня графика для админки."""
    if not _as_int(schedule.get("enabled"), 1):
        return "выходной"
    start = schedule.get("work_start", "10:00")
    end = schedule.get("work_end", "21:00")
    return f"{start}–{end}"


def week_schedule_text(schedules: Iterable[dict]) -> str:
    by_day = {_as_int(row.get("weekday"), -1): row for row in schedules}
    parts = []
    for index, name in enumerate(WEEKDAYS):
        row = by_day.get(index)
        parts.append(f"{name}: {schedule_label(row) if row else 'не задан'}")
    return " · ".join(parts)


def public_schedule_label(
    schedules: Iterable[dict],
    *,
    work_start: str = "10:00",
    work_end: str = "21:00",
    lunch_start: str = "",
    lunch_end: str = "",
) -> str:
    """Компактная подпись графика для сайта: «пн–сб 10:00–21:00 · вс выходной»."""
    by_day = {_as_int(row.get("weekday"), -1): row for row in schedules}
    labels = []
    for index in range(7):
        row = by_day.get(index)
        working = bool(row and _as_int(row.get("enabled"), 1))
        labels.append(f"{work_start}–{work_end}" if working else "выходной")

    groups: list[tuple[int, int, str]] = []
    start = 0
    for index in range(1, 7):
        if labels[index] != labels[start]:
            groups.append((start, index - 1, labels[start]))
            start = index
    groups.append((start, 6, labels[start]))

    parts = []
    for first, last, label in groups:
        day_label = WEEKDAYS[first] if first == last else f"{WEEKDAYS[first]}–{WEEKDAYS[last]}"
        parts.append(f"{day_label} {label}")
    result = " · ".join(parts)
    if lunch_start and lunch_end:
        result += f" · обед {lunch_start}–{lunch_end}"
    return result

