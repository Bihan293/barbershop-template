from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.scheduling import compute_slots

TZ = ZoneInfo("Asia/Almaty")
NOW = datetime(2026, 11, 15, 9, 0, tzinfo=TZ)


def master(master_id=1, active=1):
    return {"id": master_id, "name": f"Мастер {master_id}", "active": active}


def schedule(master_id=1, **overrides):
    row = {
        "master_id": master_id,
        "weekday": 0,
        "enabled": 1,
        "work_start": "10:00",
        "work_end": "21:00",
        "lunch_start": "",
        "lunch_end": "",
    }
    row.update(overrides)
    return row


def slots(*, orders=None, masters=None, schedules=None, days_off=None, master_id=None, duration=30, breaks=None):
    return compute_slots(
        day="2026-11-16",
        duration=duration,
        settings={"slot_step": "30", "last_slot": "20:00"},
        masters=masters if masters is not None else [master()],
        schedules=schedules if schedules is not None else [schedule()],
        days_off=days_off or set(),
        orders=orders or [],
        tz=TZ,
        breaks=breaks or [],
        master_id=master_id,
        now=NOW,
    )


class SchedulingTests(unittest.TestCase):
    def test_full_duration_blocks_starts(self):
        result = slots(orders=[{"id": 1, "time": "17:00", "duration": 60, "master_id": 1}])
        self.assertNotIn("17:00", result)
        self.assertNotIn("17:30", result)
        self.assertIn("18:00", result)

    def test_thirty_minutes_leaves_next_slot(self):
        result = slots(
            duration=30,
            orders=[{"id": 1, "time": "17:00", "duration": 30, "master_id": 1}],
        )
        self.assertNotIn("17:00", result)
        self.assertIn("17:30", result)

    def test_lunch_blocks_overlapping_starts(self):
        result = slots(schedules=[schedule(lunch_start="14:00", lunch_end="15:00")])
        self.assertIn("13:30", result)
        self.assertNotIn("14:00", result)
        self.assertIn("15:00", result)

    def test_day_off_hides_master(self):
        result = slots(days_off={(1, "2026-11-16")})
        self.assertEqual(result, [])

    def test_disabled_master_has_no_slots(self):
        result = slots(masters=[master(active=0)])
        self.assertEqual(result, [])

    def test_no_masters_has_no_slots(self):
        result = slots(masters=[])
        self.assertEqual(result, [])

    def test_two_masters_can_take_same_time(self):
        result = slots(
            masters=[master(1), master(2)],
            schedules=[schedule(1), schedule(2)],
            orders=[{"id": 1, "time": "17:00", "duration": 60, "master_id": 1}],
        )
        self.assertIn("17:00", result)  # свободен у второго мастера
        self.assertIn("18:00", result)

    def test_multiple_breaks_block_all_intervals(self):
        result = slots(
            breaks=[
                {"master_id": 1, "weekday": 0, "break_start": "12:00", "break_end": "13:00"},
                {"master_id": 1, "weekday": 0, "break_start": "15:00", "break_end": "16:00"},
            ]
        )
        self.assertNotIn("12:00", result)
        self.assertIn("11:30", result)
        self.assertIn("13:00", result)
        self.assertNotIn("15:00", result)
        self.assertNotIn("15:30", result)
        self.assertIn("16:00", result)

    def test_specific_master_is_respected(self):
        result = slots(
            master_id=2,
            masters=[master(1, 0), master(2)],
            schedules=[schedule(1), schedule(2)],
        )
        self.assertTrue(result)
        result_off = slots(
            master_id=2,
            masters=[master(1), master(2)],
            schedules=[schedule(1), schedule(2)],
            days_off={(2, "2026-11-16")},
        )
        self.assertEqual(result_off, [])
