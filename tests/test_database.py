from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.database import Database
from app.services import combine_services, service_items


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.db", ZoneInfo("Asia/Almaty"))
        await self.db.connect()
        self.service = (await self.db.list_services())[0]
        self.master = (await self.db.list_masters())[0]
        self.day = (
            datetime.now(ZoneInfo("Asia/Almaty")).date() + timedelta(days=1)
        ).isoformat()

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()

    async def test_default_master_and_schedule(self):
        masters = await self.db.list_masters()
        self.assertEqual(len(masters), 1)
        schedule = await self.db.get_master_schedule(masters[0]["id"])
        self.assertEqual(len(schedule), 7)
        self.assertEqual(schedule[0]["work_start"], "10:00")

    async def test_booking_and_reschedule(self):
        order, error = await self.db.create_order(
            name="Тест",
            phone="+77001234567",
            service=self.service,
            day=self.day,
            slot="17:00",
            channel="telegram",
            comment="",
            source="site",
            tg_id=None,
            master_id=self.master["id"],
        )
        self.assertIsNone(error)
        self.assertEqual(order["master_name"], self.master["name"])
        self.assertTrue(order["consent_at"])

        slots = await self.db.available_slots(self.day, 30, master_id=self.master["id"])
        self.assertNotIn("17:30", slots)

        moved, error = await self.db.reschedule_order(order["id"], self.day, "18:00")
        self.assertIsNone(error)
        self.assertEqual(moved["time"], "18:00")
        slots = await self.db.available_slots(self.day, 30, master_id=self.master["id"])
        self.assertIn("17:00", slots)
        self.assertNotIn("18:00", slots)

    async def test_no_active_masters_blocks_booking(self):
        await self.db.update_master(self.master["id"], active=0)
        order, error = await self.db.create_order(
            name="Тест",
            phone="+77001234567",
            service=self.service,
            day=self.day,
            slot="17:00",
            channel="telegram",
            comment="",
            source="site",
            tg_id=None,
        )
        self.assertIsNone(order)
        self.assertIn("мастер", (error or "").lower())

    async def test_client_can_cancel_only_own_future_order(self):
        order, error = await self.db.create_order(
            name="Клиент",
            phone="+77001234567",
            service=self.service,
            day=self.day,
            slot="17:00",
            channel="telegram",
            comment="",
            source="telegram",
            tg_id=555,
        )
        self.assertIsNone(error)
        denied, denied_error = await self.db.cancel_order_by_client(order["id"], 999)
        self.assertIsNone(denied)
        self.assertIn("другому", denied_error or "")
        cancelled, cancel_error = await self.db.cancel_order_by_client(order["id"], 555)
        self.assertIsNone(cancel_error)
        self.assertEqual(cancelled["status"], "cancelled")
        slots = await self.db.available_slots(self.day, 30, master_id=self.master["id"])
        self.assertIn("17:00", slots)

    async def test_client_reschedule_requires_owner(self):
        order, error = await self.db.create_order(
            name="Клиент",
            phone="+77001234567",
            service=self.service,
            day=self.day,
            slot="17:00",
            channel="telegram",
            comment="",
            source="telegram",
            tg_id=555,
        )
        self.assertIsNone(error)
        day2 = (
            datetime.fromisoformat(self.day) + timedelta(days=1)
        ).date().isoformat()
        denied, denied_error = await self.db.reschedule_order(
            order["id"], day2, "10:00", owner_tg_id=999
        )
        self.assertIsNone(denied)
        self.assertTrue(denied_error)
        moved, move_error = await self.db.reschedule_order(
            order["id"], day2, "10:00", owner_tg_id=555
        )
        self.assertIsNone(move_error)
        self.assertEqual(moved["date"], day2)

    async def test_public_token_portal(self):
        order, error = await self.db.create_order(
            name="Портал",
            phone="+77001234567",
            service=self.service,
            day=self.day,
            slot="18:00",
            channel="telegram",
            comment="",
            source="site",
            tg_id=None,
        )
        self.assertIsNone(error)
        token = order["public_token"]
        self.assertTrue(token)
        found = await self.db.orders_by_tokens([token])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["id"], order["id"])
        denied, denied_error = await self.db.cancel_order_by_token(order["id"], "bad")
        self.assertIsNone(denied)
        self.assertTrue(denied_error)
        canceled, cancel_error = await self.db.cancel_order_by_token(order["id"], token)
        self.assertIsNone(cancel_error)
        self.assertEqual(canceled["status"], "cancelled")

    async def test_renames_update_future_orders(self):
        order, error = await self.db.create_order(
            name="Клиент",
            phone="+77001234567",
            service=self.service,
            day=self.day,
            slot="19:00",
            channel="telegram",
            comment="",
            source="site",
            tg_id=None,
            master_id=self.master["id"],
        )
        self.assertIsNone(error)
        await self.db.update_master(self.master["id"], name="Новое имя мастера")
        updated = await self.db.get_order(order["id"])
        self.assertEqual(updated["master_name"], "Новое имя мастера")
        await self.db.update_service(self.service["id"], name="Новое имя услуги")
        updated = await self.db.get_order(order["id"])
        self.assertEqual(updated["service_name"], "Новое имя услуги")

    async def test_site_stats_seed_and_crud(self):
        rows = await self.db.list_site_stats()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["value"], "5")
        self.assertEqual(rows[1]["plus"], 1)

        numeric_id = await self.db.add_site_stat(
            value="50", label="точек|по всему миру", plus=1
        )
        text_id = await self.db.add_site_stat(
            value="Знаменитости", label="стригутся|у нас", plus=0
        )
        rows = await self.db.list_site_stats()
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[-2]["label"], "точек|по всему миру")
        self.assertEqual(rows[-1]["value"], "Знаменитости")

        await self.db.update_site_stat(numeric_id, value="55", plus=0)
        updated = await self.db.get_site_stat(numeric_id)
        self.assertEqual(updated["value"], "55")
        self.assertEqual(updated["plus"], 0)

        await self.db.delete_site_stat(text_id)
        self.assertIsNone(await self.db.get_site_stat(text_id))

    async def test_multi_service_order_totals_and_items(self):
        services = (await self.db.list_services())[:2]
        combined = combine_services(services)
        items = service_items(services)
        order, error = await self.db.create_order(
            name="Комплексный клиент",
            phone="+77001234567",
            service=combined,
            day=self.day,
            slot="17:00",
            channel="telegram",
            comment="",
            source="site",
            tg_id=None,
            service_items=items,
        )
        self.assertIsNone(error)
        self.assertEqual(order["service_name"], " + ".join(item["name"] for item in services))
        self.assertEqual(order["price"], sum(int(item["price"]) for item in services))
        self.assertEqual(
            order["duration"], sum(int(item["duration"]) for item in services)
        )
        rows = await self.db.get_order_services(order["id"])
        self.assertEqual([row["service_name"] for row in rows], [item["name"] for item in services])
        slots = await self.db.available_slots(
            self.day,
            int(order["duration"]),
            master_id=self.master["id"],
        )
        self.assertNotIn("17:00", slots)

    async def test_source_counts_use_database_rows(self):
        slots = {"site": "17:00", "telegram": "18:00", "admin": "19:00"}
        for source in ("site", "telegram", "admin"):
            await self.db.create_order(
                name="Клиент",
                phone="+77001234567",
                service=self.service,
                day=self.day,
                slot=slots[source],
                channel="admin" if source == "admin" else source,
                comment="",
                source=source,
                tg_id=123 if source == "telegram" else None,
            )
        counts = await self.db.source_counts()
        self.assertEqual(counts.get("site"), 1)
        self.assertEqual(counts.get("telegram"), 1)
        self.assertEqual(counts.get("admin"), 1)

    async def test_global_hours_lunch_and_weekly_day_off(self):
        weekday = datetime.fromisoformat(self.day).weekday()
        await self.db.set_setting("work_start", "09:00")
        await self.db.set_setting("work_end", "20:00")
        await self.db.set_setting("last_slot", "19:00")
        await self.db.set_setting("lunch_start", "13:00")
        await self.db.set_setting("lunch_end", "14:00")

        # Старые индивидуальные перерывы больше не влияют на слоты.
        await self.db.add_master_break(self.master["id"], weekday, "15:00", "16:00")
        slots = await self.db.available_slots(self.day, 30, master_id=self.master["id"])
        for blocked in ("13:00", "13:30"):
            self.assertNotIn(blocked, slots)
        for free in ("12:30", "14:00", "15:00", "19:00"):
            self.assertIn(free, slots)

        # Индивидуальные часы мастера игнорируются — работают общие настройки.
        await self.db.save_master_schedule(
            self.master["id"],
            weekday,
            enabled=1,
            start="08:00",
            end="12:00",
        )
        slots = await self.db.available_slots(self.day, 30, master_id=self.master["id"])
        self.assertIn("19:00", slots)

        # Выходной по дню недели по-прежнему работает.
        await self.db.save_master_schedule(
            self.master["id"],
            weekday,
            enabled=0,
            start="10:00",
            end="21:00",
        )
        self.assertEqual(await self.db.available_slots(self.day, 30, master_id=self.master["id"]), [])
        await self.db.save_master_schedule(
            self.master["id"],
            weekday,
            enabled=1,
            start="10:00",
            end="21:00",
        )
        self.assertTrue(await self.db.available_slots(self.day, 30, master_id=self.master["id"]))


if __name__ == "__main__":
    unittest.main()
