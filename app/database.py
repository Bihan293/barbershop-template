from __future__ import annotations
"""Репозиторий данных.

Все SQL-запросы собраны здесь. Для SQLite и PostgreSQL используется один
и тот же код: различия диалектов скрыты в app/db_backend.py.
"""
import asyncio
import logging
import secrets
from datetime import date as Date, datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .core import hhmm_to_min, overlaps, valid_iso_date
from .db_backend import PostgresBackend, SqliteBackend
from .scheduling import compute_slots, master_works

LOG = logging.getLogger("lezvie.db")

DEFAULT_SETTINGS = {
    "brand": "ЛЕЗВИЕ",
    "city": "Алматы",
    "address": "пр. Достык, 132",
    "address_note": "Алматы, уг. ул. Кабанбай батыра",
    "hours": "Ежедневно, 10:00–21:00",
    "hours_note": "Последняя запись — в 20:00",
    "phone": "+7 700 000 00 00",
    "whatsapp": "77000000000",
    "twogis_url": "https://2gis.kz/almaty/search/%D0%94%D0%BE%D1%81%D1%82%D1%8B%D0%BA%20132",
    "instagram": "https://instagram.com/lezvie.barber",
    "booking_enabled": "1",
    "slot_step": "30",
    "work_start": "10:00",
    "work_end": "21:00",
    "last_slot": "20:00",
    "reminder_minutes": "120",
    "privacy_updated": "15.11.2026",
    "stat_years": "5",
    "stat_clients": "3000",
    "stat_rating": "4.9",
    "stat_years_label": "лет|в ремесле",
    "stat_clients_label": "клиентов|за 5 лет",
    "stat_rating_label": "рейтинг|в 2ГИС",
    "stat_years_plus": "0",
    "stat_clients_plus": "1",
}

SEED_SERVICES = [
    ("Стрижка", "Консультация, работа машинкой и ножницами, мытьё и укладка. Форма, которая держится до следующего визита.", 4000, 60),
    ("Борода", "Коррекция формы, чистые контуры, горячее полотенце и масло. Борода, за которой видно уход.", 2500, 40),
    ("Комплекс", "Стрижка и борода за один визит. Полный образ и время, которое работает на вас.", 6000, 90),
    ("Детская стрижка", "Для гостей до 12 лет: спокойный темп, мультики и мастер, который умеет договариваться.", 3000, 40),
]

SEED_GALLERY = [
    "фото · интерьер",
    "фото · процесс",
    "фото · детали",
    "фото · инструмент",
    "фото · гости",
    "фото · вечер",
]

SEED_REVIEWS = [
    ("Арман К.", "Хожу третий год и ни разу не пожалел. Влад слышит с полуслова: «как в прошлый раз, но чуть короче» — и попадание стопроцентное. Отдельное спасибо за кофе.", 5, "2ГИС · март 2026"),
    ("Данияр Ж.", "Наконец-то место, где бороду не подравнивают, а строят форму. Видно, что мастеру не всё равно. Записываюсь за неделю — и это того стоит.", 5, "2ГИС · февраль 2026"),
    ("Тимур А.", "Привёл сына на первую стрижку: думал, будет скандал. Через сорок минут ребёнок не хотел уходить. Себе тоже записался.", 5, "Google · январь 2026"),
]

SEED_WHY = [
    ("✂️", "Мастера, а не исполнители", "Каждый барбер работает в ЛЕЗВИЕ минимум три года. Мы не берём «на поток» — только тех, кому доверили бы свою голову."),
    ("⏱️", "Ваше время уважают", "Работаем строго по записи. Никаких очередей в коридоре и «подождите двадцать минут»."),
    ("🧴", "Косметика без компромиссов", "American Crew, Uppercut и Reuzel. То, чем пользуемся сами, а не то, что выгодно продавать."),
    ("☕", "Атмосфера, за которую возвращаются", "Кофе, виски, винил и разговоры без спешки. Сюда приходят не только за стрижкой."),
]

SEED_MASTER = (
    "Михаил",
    "Барбер с восьмилетним опытом. Классика, фейд, работа с бородой. "
    "Любит точные линии и спокойный разговор без спешки.",
)


async def load_slot_context(executor: Any, day: str) -> dict[str, Any]:
    """Загружает всё, что нужно для расчёта слотов на один день."""
    settings_rows = await executor.fetchall("SELECT key, value FROM settings")
    settings = {row["key"]: row["value"] for row in settings_rows}
    masters = await executor.fetchall(
        "SELECT * FROM masters WHERE active=1 ORDER BY sort, id"
    )
    schedules = await executor.fetchall("SELECT * FROM master_schedules")
    # Индивидуальные перерывы мастеров больше не используются: обед общий из настроек.
    breaks: list[dict] = []
    days_off_rows = await executor.fetchall(
        "SELECT master_id, date FROM master_days_off WHERE date=?", (day,)
    )
    days_off = {
        (int(row["master_id"]), str(row["date"]))
        for row in days_off_rows
    }
    orders = await executor.fetchall(
        "SELECT id, time, duration, master_id, status FROM orders "
        "WHERE date=? AND status IN ('new','confirmed')",
        (day,),
    )
    return {
        "settings": settings,
        "masters": masters,
        "schedules": schedules,
        "breaks": breaks,
        "days_off": days_off,
        "orders": orders,
    }


class Database:
    def __init__(self, path: Path, tz: ZoneInfo, database_url: str = "") -> None:
        self.path = path
        self.tz = tz
        self.database_url = (database_url or "").strip()
        self.is_postgres = bool(self.database_url)
        self.backend: SqliteBackend | PostgresBackend = (
            PostgresBackend(self.database_url) if self.is_postgres else SqliteBackend(path)
        )
        self._lock = asyncio.Lock()

    @property
    def label(self) -> str:
        if self.is_postgres:
            return "PostgreSQL (DATABASE_URL)"
        return str(self.path)

    async def connect(self) -> None:
        await self.backend.connect()
        await self._migrate_legacy_lunches()
        await self._seed()
        await self._migrate_master_common_break()

    async def close(self) -> None:
        await self.backend.close()

    # ---------- низкий уровень ----------

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        return await self.backend.fetchall(sql, params)

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        return await self.backend.fetchone(sql, params)

    async def execute(self, sql: str, params: tuple = ()) -> int:
        return await self.backend.execute(sql, params)

    async def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        await self.backend.execute_many(sql, params_list)

    async def insert(self, table: str, data: dict[str, Any]) -> int:
        return await self.backend.insert(table, data)

    def transaction(self):
        return self.backend.transaction()

    async def database_size(self) -> int:
        return await self.backend.database_size()

    # ---------- первичное заполнение и миграции ----------

    async def _migrate_legacy_lunches(self) -> None:
        """Старый один обед из master_schedules → несколько перерывов."""
        rows = await self.fetchall(
            "SELECT master_id, weekday, lunch_start, lunch_end FROM master_schedules "
            "WHERE lunch_start<>'' AND lunch_end<>''"
        )
        migrated = 0
        for row in rows:
            master_id = int(row["master_id"])
            weekday = int(row["weekday"])
            start = str(row["lunch_start"])
            end = str(row["lunch_end"])
            if hhmm_to_min(start, -1) < 0 or hhmm_to_min(end, -1) <= hhmm_to_min(start, -1):
                continue
            existing = await self.fetchone(
                "SELECT id FROM master_breaks WHERE master_id=? AND weekday=? "
                "AND break_start=? AND break_end=?",
                (master_id, weekday, start, end),
            )
            if existing:
                continue
            now = datetime.now(self.tz).isoformat(timespec="seconds")
            await self.insert(
                "master_breaks",
                {
                    "master_id": master_id,
                    "weekday": weekday,
                    "break_start": start,
                    "break_end": end,
                    "title": "Обед",
                    "created_at": now,
                },
            )
            migrated += 1
        if migrated:
            LOG.info("Миграция обедов в перерывы: %s", migrated)
        # Старые поля больше не используются в расчёте слотов.
        await self.execute(
            "UPDATE master_schedules SET lunch_start='', lunch_end='' "
            "WHERE lunch_start<>'' OR lunch_end<>''"
        )

    async def _migrate_master_common_break(self) -> None:
        """Старые перерывы по дням → один общий перерыв мастера на все дни."""
        done = await self.fetchone(
            "SELECT value FROM meta WHERE key='master_common_break_migrated'"
        )
        if done:
            return
        masters = await self.list_masters()
        for master in masters:
            if str(master.get("break_start") or "") or str(master.get("break_end") or ""):
                continue
            row = await self.fetchone(
                "SELECT break_start, break_end FROM master_breaks "
                "WHERE master_id=? AND break_start<>'' AND break_end<>'' "
                "ORDER BY weekday, id LIMIT 1",
                (int(master["id"]),),
            )
            if not row:
                continue
            start = str(row["break_start"] or "")
            end = str(row["break_end"] or "")
            if hhmm_to_min(start, -1) >= 0 and hhmm_to_min(end, -1) > hhmm_to_min(start, -1):
                await self.execute(
                    "UPDATE masters SET break_start=?, break_end=? WHERE id=?",
                    (start, end, int(master["id"])),
                )
        await self.execute(
            "INSERT INTO meta(key, value) VALUES('master_common_break_migrated', '1') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )

    async def _seed(self) -> None:
        now = datetime.now(self.tz).isoformat(timespec="seconds")
        for key, value in DEFAULT_SETTINGS.items():
            await self.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO NOTHING",
                (key, value),
            )

        stats_seeded = await self.fetchone(
            "SELECT value FROM meta WHERE key='site_stats_seeded'"
        )
        if not stats_seeded:
            stats_count = await self.fetchone("SELECT COUNT(*) AS c FROM site_stats")
            if stats_count and int(stats_count["c"]) == 0:
                for index, (value_key, label_key, plus_key) in enumerate(
                    (
                        ("stat_years", "stat_years_label", "stat_years_plus"),
                        ("stat_clients", "stat_clients_label", "stat_clients_plus"),
                        ("stat_rating", "stat_rating_label", None),
                    ),
                    start=1,
                ):
                    value = await self.get_setting(value_key, "")
                    label = await self.get_setting(label_key, "")
                    plus = 0
                    if plus_key:
                        plus = 1 if await self.get_setting(plus_key, "0") == "1" else 0
                    if not value and not label:
                        continue
                    await self.insert(
                        "site_stats",
                        {
                            "value": value,
                            "label": label,
                            "plus": plus,
                            "sort": index,
                            "created_at": now,
                        },
                    )
            await self.execute(
                "INSERT INTO meta(key, value) VALUES('site_stats_seeded', '1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )

        why_seeded = await self.fetchone("SELECT value FROM meta WHERE key='why_seeded'")
        if not why_seeded:
            count_row = await self.fetchone("SELECT COUNT(*) AS c FROM why")
            if count_row and int(count_row["c"]) == 0:
                for index, (icon, title, text) in enumerate(SEED_WHY, start=1):
                    await self.insert(
                        "why",
                        {
                            "icon": icon,
                            "title": title,
                            "text": text,
                            "sort": index,
                            "created_at": now,
                        },
                    )
            await self.execute(
                "INSERT INTO meta(key, value) VALUES('why_seeded', '1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )

        seeded = await self.fetchone("SELECT value FROM meta WHERE key='seeded'")
        if not seeded:
            for index, (name, description, price, duration) in enumerate(SEED_SERVICES, start=1):
                await self.insert(
                    "services",
                    {
                        "name": name,
                        "description": description,
                        "price": price,
                        "duration": duration,
                        "sort": index,
                        "created_at": now,
                    },
                )
            for index, caption in enumerate(SEED_GALLERY, start=1):
                await self.insert(
                    "gallery",
                    {"image": "", "caption": caption, "sort": index, "created_at": now},
                )
            for index, (name, text, rating, source) in enumerate(SEED_REVIEWS, start=1):
                await self.insert(
                    "reviews",
                    {
                        "name": name,
                        "text": text,
                        "rating": rating,
                        "source": source,
                        "sort": index,
                        "created_at": now,
                    },
                )
            await self.execute(
                "INSERT INTO meta(key, value) VALUES('seeded', '1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )

        await self._seed_masters(now)
        await self._normalize_contact_settings()
        await self.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', '2') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )

    async def _normalize_contact_settings(self) -> None:
        """Если WhatsApp остался старым placeholder — ставим номер телефона."""
        settings = await self.get_settings()
        wa = str(settings.get("whatsapp", "")).replace(" ", "")
        phone = str(settings.get("phone", "")).replace(" ", "")
        phone_digits = "".join(ch for ch in phone if ch.isdigit())
        wa_digits = "".join(ch for ch in wa if ch.isdigit())
        if phone_digits and (not wa_digits or wa_digits == "77000000000"):
            await self.set_setting("whatsapp", phone_digits)

    async def _seed_masters(self, now: str) -> None:
        settings = await self.get_settings()
        seeded = await self.fetchone("SELECT value FROM meta WHERE key='masters_seeded'")
        master_row = await self.fetchone("SELECT * FROM masters ORDER BY sort, id LIMIT 1")
        if not master_row:
            if seeded:
                # Админ сознательно удалил всех мастеров — не воскрешаем.
                return
            name, description = SEED_MASTER
            master_id = await self.add_master(
                name=name,
                description=description,
            )
            master_row = await self.get_master(master_id)

        if not master_row:
            return

        await self._ensure_master_schedules()

        # Старые заказы не знали про мастеров — привязываем их к первому.
        await self.execute(
            "UPDATE orders SET master_id=?, master_name=? "
            "WHERE master_id IS NULL OR master_id=0",
            (int(master_row["id"]), master_row["name"]),
        )
        await self.execute(
            "UPDATE orders SET master_name=COALESCE("
            "(SELECT name FROM masters WHERE masters.id=orders.master_id), '') "
            "WHERE master_name='' AND master_id IS NOT NULL"
        )
        await self.execute(
            "INSERT INTO meta(key, value) VALUES('masters_seeded', '1') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )
        if not settings.get("work_start"):
            await self.set_setting("work_start", "10:00")

    async def _ensure_master_schedules(self) -> None:
        """У импортированных мастеров может не быть строк графика."""
        masters = await self.list_masters()
        if not masters:
            return
        rows = await self.fetchall("SELECT master_id, weekday FROM master_schedules")
        have = {(int(row["master_id"]), int(row["weekday"])) for row in rows}
        settings = await self.get_settings()
        start = settings.get("work_start", "10:00")
        end = settings.get("work_end", "21:00")
        for master in masters:
            mid = int(master["id"])
            for weekday in range(7):
                if (mid, weekday) in have:
                    continue
                await self.execute(
                    "INSERT INTO master_schedules"
                    "(master_id, weekday, enabled, work_start, work_end, lunch_start, lunch_end) "
                    "VALUES(?,?,?,?,?,?,?) ON CONFLICT(master_id, weekday) DO NOTHING",
                    (mid, weekday, 1, start, end, "", ""),
                )

    # ---------- настройки ----------

    async def get_settings(self) -> dict[str, str]:
        rows = await self.fetchall("SELECT key, value FROM settings")
        return {row["key"]: row["value"] for row in rows}

    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self.fetchone("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    async def set_setting(self, key: str, value: Any) -> None:
        await self.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    # ---------- услуги ----------

    async def list_services(self) -> list[dict]:
        return await self.fetchall("SELECT * FROM services ORDER BY sort, id")

    async def get_service(self, service_id: int) -> Optional[dict]:
        return await self.fetchone("SELECT * FROM services WHERE id=?", (service_id,))

    async def find_service_by_name(self, name: str) -> Optional[dict]:
        return await self.fetchone(
            "SELECT * FROM services WHERE lower(name)=lower(?) ORDER BY id LIMIT 1",
            (name.strip(),),
        )

    async def add_service(self, *, name: str, description: str, price: int, duration: int, photo: str = "") -> int:
        row = await self.fetchone("SELECT COALESCE(MAX(sort),0)+1 AS next FROM services")
        sort = int(row["next"]) if row else 1
        now = datetime.now(self.tz).isoformat(timespec="seconds")
        return await self.insert(
            "services",
            {
                "name": name,
                "description": description,
                "price": price,
                "duration": duration,
                "photo": photo,
                "sort": sort,
                "created_at": now,
            },
        )

    async def update_service(self, service_id: int, **fields: Any) -> None:
        allowed = {"name", "description", "price", "duration", "photo"}
        data = {key: value for key, value in fields.items() if key in allowed}
        if not data:
            return
        assignments = ", ".join(f"{key}=?" for key in data)
        await self.execute(
            f"UPDATE services SET {assignments} WHERE id=?",
            (*data.values(), service_id),
        )
        if "name" in data:
            today = datetime.now(self.tz).date().isoformat()
            await self.execute(
                "UPDATE orders SET service_name=? WHERE service_id=? "
                "AND status IN ('new','confirmed') AND date>=?",
                (data["name"], service_id, today),
            )
            await self.execute(
                "UPDATE order_services SET service_name=? WHERE service_id=? "
                "AND order_id IN (SELECT id FROM orders WHERE status IN ('new','confirmed') "
                "AND date>=?)",
                (data["name"], service_id, today),
            )
            # У составной записи в orders хранится общее название — собираем заново.
            affected = await self.fetchall(
                "SELECT DISTINCT order_id FROM order_services WHERE service_id=? "
                "AND order_id IN (SELECT id FROM orders WHERE status IN ('new','confirmed') "
                "AND date>=?)",
                (service_id, today),
            )
            for row in affected:
                order_id = int(row["order_id"])
                items = await self.fetchall(
                    "SELECT service_name FROM order_services WHERE order_id=? "
                    "ORDER BY sort, id",
                    (order_id,),
                )
                names = [str(item["service_name"] or "") for item in items]
                if len(names) > 1:
                    await self.execute(
                        "UPDATE orders SET service_name=? WHERE id=?",
                        (" + ".join(names), order_id),
                    )

    async def delete_service(self, service_id: int) -> Optional[dict]:
        service = await self.get_service(service_id)
        if service:
            await self.execute("DELETE FROM services WHERE id=?", (service_id,))
        return service

    # ---------- цифры и достижения на сайте ----------

    async def list_site_stats(self) -> list[dict]:
        return await self.fetchall(
            "SELECT * FROM site_stats ORDER BY sort, id"
        )

    async def get_site_stat(self, stat_id: int) -> Optional[dict]:
        return await self.fetchone("SELECT * FROM site_stats WHERE id=?", (stat_id,))

    async def add_site_stat(self, *, value: str, label: str, plus: int = 0) -> int:
        row = await self.fetchone("SELECT COALESCE(MAX(sort),0)+1 AS next FROM site_stats")
        sort = int(row["next"]) if row else 1
        now = datetime.now(self.tz).isoformat(timespec="seconds")
        return await self.insert(
            "site_stats",
            {
                "value": value,
                "label": label,
                "plus": 1 if plus else 0,
                "sort": sort,
                "created_at": now,
            },
        )

    async def update_site_stat(self, stat_id: int, **fields: Any) -> None:
        allowed = {"value", "label", "plus", "sort"}
        data = {key: value for key, value in fields.items() if key in allowed}
        if "plus" in data:
            data["plus"] = 1 if data["plus"] else 0
        if not data:
            return
        assignments = ", ".join(f"{key}=?" for key in data)
        await self.execute(
            f"UPDATE site_stats SET {assignments} WHERE id=?",
            (*data.values(), stat_id),
        )

    async def delete_site_stat(self, stat_id: int) -> Optional[dict]:
        item = await self.get_site_stat(stat_id)
        if item:
            await self.execute("DELETE FROM site_stats WHERE id=?", (stat_id,))
        return item

    # ---------- галерея ----------

    async def list_gallery(self) -> list[dict]:
        return await self.fetchall("SELECT * FROM gallery ORDER BY sort, id")

    async def get_gallery(self, item_id: int) -> Optional[dict]:
        return await self.fetchone("SELECT * FROM gallery WHERE id=?", (item_id,))

    async def add_gallery(self, image: str, caption: str) -> int:
        row = await self.fetchone("SELECT COALESCE(MAX(sort),0)+1 AS next FROM gallery")
        sort = int(row["next"]) if row else 1
        now = datetime.now(self.tz).isoformat(timespec="seconds")
        return await self.insert(
            "gallery",
            {"image": image, "caption": caption, "sort": sort, "created_at": now},
        )

    async def update_gallery(self, item_id: int, **fields: Any) -> None:
        allowed = {"image", "caption"}
        data = {key: value for key, value in fields.items() if key in allowed}
        if not data:
            return
        assignments = ", ".join(f"{key}=?" for key in data)
        await self.execute(
            f"UPDATE gallery SET {assignments} WHERE id=?",
            (*data.values(), item_id),
        )

    async def delete_gallery(self, item_id: int) -> Optional[dict]:
        item = await self.get_gallery(item_id)
        if item:
            await self.execute("DELETE FROM gallery WHERE id=?", (item_id,))
        return item

    # ---------- отзывы ----------

    async def list_reviews(self) -> list[dict]:
        return await self.fetchall("SELECT * FROM reviews ORDER BY sort, id")

    async def get_review(self, review_id: int) -> Optional[dict]:
        return await self.fetchone("SELECT * FROM reviews WHERE id=?", (review_id,))

    async def add_review(self, *, name: str, text: str, rating: int, source: str) -> int:
        row = await self.fetchone("SELECT COALESCE(MAX(sort),0)+1 AS next FROM reviews")
        sort = int(row["next"]) if row else 1
        now = datetime.now(self.tz).isoformat(timespec="seconds")
        return await self.insert(
            "reviews",
            {
                "name": name,
                "text": text,
                "rating": rating,
                "source": source,
                "sort": sort,
                "created_at": now,
            },
        )

    async def update_review(self, review_id: int, **fields: Any) -> None:
        allowed = {"name", "text", "rating", "source"}
        data = {key: value for key, value in fields.items() if key in allowed}
        if not data:
            return
        assignments = ", ".join(f"{key}=?" for key in data)
        await self.execute(
            f"UPDATE reviews SET {assignments} WHERE id=?",
            (*data.values(), review_id),
        )

    async def delete_review(self, review_id: int) -> Optional[dict]:
        review = await self.get_review(review_id)
        if review:
            await self.execute("DELETE FROM reviews WHERE id=?", (review_id,))
        return review

    # ---------- почему мы ----------

    async def list_why(self) -> list[dict]:
        return await self.fetchall("SELECT * FROM why ORDER BY sort, id")

    async def get_why(self, item_id: int) -> Optional[dict]:
        return await self.fetchone("SELECT * FROM why WHERE id=?", (item_id,))

    async def add_why(self, *, icon: str, title: str, text: str) -> int:
        row = await self.fetchone("SELECT COALESCE(MAX(sort),0)+1 AS next FROM why")
        sort = int(row["next"]) if row else 1
        now = datetime.now(self.tz).isoformat(timespec="seconds")
        return await self.insert(
            "why",
            {"icon": icon, "title": title, "text": text, "sort": sort, "created_at": now},
        )

    async def update_why(self, item_id: int, **fields: Any) -> None:
        allowed = {"icon", "title", "text"}
        data = {key: value for key, value in fields.items() if key in allowed}
        if not data:
            return
        assignments = ", ".join(f"{key}=?" for key in data)
        await self.execute(
            f"UPDATE why SET {assignments} WHERE id=?",
            (*data.values(), item_id),
        )

    async def delete_why(self, item_id: int) -> Optional[dict]:
        item = await self.get_why(item_id)
        if item:
            await self.execute("DELETE FROM why WHERE id=?", (item_id,))
        return item

    # ---------- мастера ----------

    async def list_masters(self, active_only: bool = False) -> list[dict]:
        where = "WHERE active=1" if active_only else ""
        return await self.fetchall(f"SELECT * FROM masters {where} ORDER BY sort, id")

    async def get_master(self, master_id: int) -> Optional[dict]:
        return await self.fetchone("SELECT * FROM masters WHERE id=?", (master_id,))

    async def add_master(
        self,
        *,
        name: str,
        description: str = "",
        photo: str = "",
        active: int = 1,
        break_start: str = "",
        break_end: str = "",
    ) -> int:
        settings = await self.get_settings()
        work_start = settings.get("work_start", "10:00")
        work_end = settings.get("work_end", "21:00")
        now = datetime.now(self.tz).isoformat(timespec="seconds")
        async with self.transaction() as conn:
            row = await conn.fetchone("SELECT COALESCE(MAX(sort),0)+1 AS next FROM masters")
            sort = int(row["next"]) if row else 1
            master_id = await conn.insert(
                "masters",
                {
                    "name": name,
                    "description": description,
                    "photo": photo,
                    "active": active,
                    "sort": sort,
                    "break_start": break_start,
                    "break_end": break_end,
                    "created_at": now,
                },
            )
            for weekday in range(7):
                await conn.insert(
                    "master_schedules",
                    {
                        "master_id": master_id,
                        "weekday": weekday,
                        "enabled": 1,
                        "work_start": work_start,
                        "work_end": work_end,
                        "lunch_start": "",
                        "lunch_end": "",
                    },
                )
        return master_id

    async def update_master(self, master_id: int, **fields: Any) -> None:
        allowed = {"name", "description", "photo", "active", "sort", "break_start", "break_end"}
        data = {key: value for key, value in fields.items() if key in allowed}
        if not data:
            return
        assignments = ", ".join(f"{key}=?" for key in data)
        await self.execute(
            f"UPDATE masters SET {assignments} WHERE id=?",
            (*data.values(), master_id),
        )
        # Чтобы будущие активные записи не показывали старое имя после переименования.
        if "name" in data:
            today = datetime.now(self.tz).date().isoformat()
            await self.execute(
                "UPDATE orders SET master_name=? WHERE master_id=? "
                "AND status IN ('new','confirmed') AND date>=?",
                (data["name"], master_id, today),
            )

    async def delete_master(self, master_id: int) -> tuple[Optional[dict], Optional[str]]:
        master = await self.get_master(master_id)
        if not master:
            return None, "Мастер не найден"
        today = datetime.now(self.tz).date().isoformat()
        row = await self.fetchone(
            "SELECT COUNT(*) AS c FROM orders WHERE master_id=? "
            "AND status IN ('new','confirmed') AND date>=?",
            (master_id, today),
        )
        if row and int(row["c"]) > 0:
            return None, "У мастера есть активные записи. Сначала перенесите или отмените их."
        async with self.transaction() as conn:
            await conn.execute("DELETE FROM master_schedules WHERE master_id=?", (master_id,))
            await conn.execute("DELETE FROM master_breaks WHERE master_id=?", (master_id,))
            await conn.execute("DELETE FROM master_days_off WHERE master_id=?", (master_id,))
            await conn.execute("DELETE FROM masters WHERE id=?", (master_id,))
        return master, None

    async def get_master_schedule(self, master_id: int) -> list[dict]:
        rows = await self.fetchall(
            "SELECT * FROM master_schedules WHERE master_id=? ORDER BY weekday",
            (master_id,),
        )
        by_day = {int(row["weekday"]): row for row in rows}
        if len(by_day) == 7 and all(index in by_day for index in range(7)):
            return [by_day[index] for index in range(7)]
        settings = await self.get_settings()
        result = []
        for weekday in range(7):
            row = by_day.get(weekday)
            if not row:
                row = {
                    "id": 0,
                    "master_id": master_id,
                    "weekday": weekday,
                    "enabled": 0,
                    "work_start": settings.get("work_start", "10:00"),
                    "work_end": settings.get("work_end", "21:00"),
                    "lunch_start": "",
                    "lunch_end": "",
                }
            result.append(row)
        return result

    async def get_master_schedule_day(self, master_id: int, weekday: int) -> Optional[dict]:
        rows = await self.get_master_schedule(master_id)
        for row in rows:
            if int(row["weekday"]) == int(weekday):
                return row
        return None

    async def save_master_schedule(
        self,
        master_id: int,
        weekday: int,
        *,
        enabled: int,
        start: str,
        end: str,
        lunch_start: str = "",
        lunch_end: str = "",
    ) -> None:
        await self.execute(
            "INSERT INTO master_schedules"
            "(master_id, weekday, enabled, work_start, work_end, lunch_start, lunch_end) "
            "VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(master_id, weekday) DO UPDATE SET "
            "enabled=excluded.enabled, work_start=excluded.work_start, "
            "work_end=excluded.work_end, "
            "lunch_start=excluded.lunch_start, lunch_end=excluded.lunch_end",
            (master_id, weekday, int(enabled), start, end, lunch_start, lunch_end),
        )

    async def list_master_breaks(
        self, master_id: int, weekday: Optional[int] = None
    ) -> list[dict]:
        if weekday is None:
            return await self.fetchall(
                "SELECT * FROM master_breaks WHERE master_id=? ORDER BY weekday, break_start",
                (master_id,),
            )
        return await self.fetchall(
            "SELECT * FROM master_breaks WHERE master_id=? AND weekday=? ORDER BY break_start",
            (master_id, int(weekday)),
        )

    async def get_master_break(self, break_id: int) -> Optional[dict]:
        return await self.fetchone("SELECT * FROM master_breaks WHERE id=?", (break_id,))

    async def add_master_break(
        self,
        master_id: int,
        weekday: int,
        start: str,
        end: str,
        title: str = "Перерыв",
    ) -> int:
        now = datetime.now(self.tz).isoformat(timespec="seconds")
        return await self.insert(
            "master_breaks",
            {
                "master_id": master_id,
                "weekday": int(weekday),
                "break_start": start,
                "break_end": end,
                "title": title,
                "created_at": now,
            },
        )

    async def delete_master_break(self, break_id: int) -> Optional[dict]:
        item = await self.get_master_break(break_id)
        if item:
            await self.execute("DELETE FROM master_breaks WHERE id=?", (break_id,))
        return item

    async def master_break_conflicts(
        self,
        master_id: int,
        weekday: int,
        start: str,
        end: str,
    ) -> list[dict]:
        """Будущие записи, которые пересекутся с новым перерывом."""
        new_start = hhmm_to_min(start, -1)
        new_end = hhmm_to_min(end, -1)
        if new_start < 0 or new_end <= new_start:
            return []
        today = datetime.now(self.tz).date().isoformat()
        rows = await self.fetchall(
            "SELECT id, date, time, duration, service_name FROM orders "
            "WHERE master_id=? AND status IN ('new','confirmed') AND date>=?",
            (master_id, today),
        )
        result = []
        for row in rows:
            try:
                day = Date.fromisoformat(str(row["date"]))
            except (TypeError, ValueError):
                continue
            if day.weekday() != int(weekday):
                continue
            order_start = hhmm_to_min(row.get("time", ""), -1)
            if order_start < 0:
                continue
            order_end = order_start + max(5, int(row.get("duration") or 30))
            if overlaps(new_start, new_end - new_start, order_start, order_end - order_start):
                result.append(dict(row))
        return result

    async def master_has_break_overlap(
        self, master_id: int, weekday: int, start: str, end: str,
        exclude_id: Optional[int] = None,
    ) -> bool:
        new_start = hhmm_to_min(start, -1)
        new_end = hhmm_to_min(end, -1)
        if new_start < 0 or new_end <= new_start:
            return True
        rows = await self.list_master_breaks(master_id, weekday)
        for row in rows:
            if exclude_id is not None and int(row["id"]) == int(exclude_id):
                continue
            old_start = hhmm_to_min(row["break_start"], -1)
            old_end = hhmm_to_min(row["break_end"], -1)
            if old_start >= 0 and old_end > old_start and new_start < old_end and old_start < new_end:
                return True
        return False

    async def master_break_conflicts_all(
        self, master_id: int, start: str, end: str
    ) -> list[dict]:
        """Будущие записи мастера, которые пересекутся с общим перерывом."""
        new_start = hhmm_to_min(start, -1)
        new_end = hhmm_to_min(end, -1)
        if new_start < 0 or new_end <= new_start:
            return []
        today = datetime.now(self.tz).date().isoformat()
        rows = await self.fetchall(
            "SELECT id, date, time, duration, service_name FROM orders "
            "WHERE master_id=? AND status IN ('new','confirmed') AND date>=?",
            (master_id, today),
        )
        result = []
        for row in rows:
            order_start = hhmm_to_min(row.get("time", ""), -1)
            if order_start < 0:
                continue
            order_end = order_start + max(5, int(row.get("duration") or 30))
            if overlaps(new_start, new_end - new_start, order_start, order_end - order_start):
                result.append(dict(row))
        return result

    async def get_day_off(self, master_id: int, day: str) -> Optional[dict]:
        return await self.fetchone(
            "SELECT * FROM master_days_off WHERE master_id=? AND date=?",
            (master_id, day),
        )

    async def add_day_off(self, master_id: int, day: str, reason: str = "") -> None:
        now = datetime.now(self.tz).isoformat(timespec="seconds")
        await self.execute(
            "INSERT INTO master_days_off(master_id, date, reason, created_at) "
            "VALUES(?,?,?,?) ON CONFLICT(master_id, date) DO UPDATE SET reason=excluded.reason",
            (master_id, day, reason, now),
        )

    async def remove_day_off(self, master_id: int, day: str) -> None:
        await self.execute(
            "DELETE FROM master_days_off WHERE master_id=? AND date=?",
            (master_id, day),
        )

    async def toggle_day_off(self, master_id: int, day: str, reason: str = "выходной") -> bool:
        existing = await self.get_day_off(master_id, day)
        if existing:
            await self.remove_day_off(master_id, day)
            return False
        await self.add_day_off(master_id, day, reason)
        return True

    async def list_days_off(
        self,
        master_id: int,
        start_day: Optional[str] = None,
        end_day: Optional[str] = None,
    ) -> list[dict]:
        today = start_day or datetime.now(self.tz).date().isoformat()
        if end_day:
            return await self.fetchall(
                "SELECT * FROM master_days_off WHERE master_id=? AND date>=? AND date<=? ORDER BY date",
                (master_id, today, end_day),
            )
        return await self.fetchall(
            "SELECT * FROM master_days_off WHERE master_id=? AND date>=? ORDER BY date",
            (master_id, today),
        )

    # ---------- заказы ----------

    async def get_order(self, order_id: int) -> Optional[dict]:
        return await self.fetchone("SELECT * FROM orders WHERE id=?", (order_id,))

    async def nearest_order(self) -> Optional[dict]:
        now = datetime.now(self.tz)
        today = now.date().isoformat()
        current = now.strftime("%H:%M")
        return await self.fetchone(
            "SELECT * FROM orders WHERE status IN ('new','confirmed') "
            "AND (date > ? OR (date = ? AND time >= ?)) "
            "ORDER BY date, time LIMIT 1",
            (today, today, current),
        )

    async def today_stats(self) -> dict:
        today = datetime.now(self.tz).date().isoformat()
        row = await self.fetchone(
            "SELECT COUNT(*) AS count, COALESCE(SUM(price),0) AS total "
            "FROM orders WHERE date=? AND status IN ('new','confirmed','completed')",
            (today,),
        )
        return {"count": int(row["count"]) if row else 0, "total": int(row["total"]) if row else 0}

    async def list_orders(self, filter_name: str = "upcoming", limit: int = 7, offset: int = 0) -> list[dict]:
        now = datetime.now(self.tz)
        today = now.date().isoformat()
        current = now.strftime("%H:%M")
        if filter_name == "new":
            sql = "SELECT * FROM orders WHERE status='new' ORDER BY date, time LIMIT ? OFFSET ?"
            params: tuple = (limit, offset)
        elif filter_name == "today":
            sql = "SELECT * FROM orders WHERE date=? ORDER BY time, id LIMIT ? OFFSET ?"
            params = (today, limit, offset)
        elif filter_name == "all":
            sql = (
                "SELECT * FROM orders WHERE status IN ('new','confirmed') "
                "ORDER BY date DESC, time DESC, id DESC LIMIT ? OFFSET ?"
            )
            params = (limit, offset)
        elif filter_name == "archive":
            sql = (
                "SELECT * FROM orders WHERE status IN ('completed','cancelled') "
                "ORDER BY date DESC, time DESC, id DESC LIMIT ? OFFSET ?"
            )
            params = (limit, offset)
        else:
            sql = (
                "SELECT * FROM orders WHERE status IN ('new','confirmed') "
                "AND (date > ? OR (date = ? AND time >= ?)) "
                "ORDER BY date, time LIMIT ? OFFSET ?"
            )
            params = (today, today, current, limit, offset)
        return await self.fetchall(sql, params)

    async def orders_by_tokens(self, tokens: list[str]) -> list[dict]:
        cleaned = [str(token).strip() for token in tokens if str(token).strip()]
        if not cleaned:
            return []
        placeholders = ", ".join("?" for _ in cleaned)
        return await self.fetchall(
            f"SELECT * FROM orders WHERE public_token IN ({placeholders}) "
            "ORDER BY date, time",
            tuple(cleaned),
        )

    async def future_orders_for_master(
        self, master_id: int, from_day: Optional[str] = None
    ) -> list[dict]:
        day = from_day or datetime.now(self.tz).date().isoformat()
        return await self.fetchall(
            "SELECT * FROM orders WHERE master_id=? AND status IN ('new','confirmed') "
            "AND date>=? ORDER BY date, time",
            (master_id, day),
        )

    async def orders_for_master_date(self, master_id: int, day: str) -> list[dict]:
        return await self.fetchall(
            "SELECT * FROM orders WHERE master_id=? AND status IN ('new','confirmed') "
            "AND date=? ORDER BY time",
            (master_id, day),
        )

    async def orders_by_tg(self, tg_id: int) -> list[dict]:
        return await self.fetchall(
            "SELECT * FROM orders WHERE tg_id=? ORDER BY date DESC, time DESC LIMIT 20",
            (tg_id,),
        )

    async def orders_for_date(self, day: str, master_id: Optional[int] = None) -> list[dict]:
        if master_id is None:
            return await self.fetchall(
                "SELECT id, time, duration, master_id FROM orders "
                "WHERE date=? AND status IN ('new','confirmed')",
                (day,),
            )
        return await self.fetchall(
            "SELECT id, time, duration, master_id FROM orders "
            "WHERE date=? AND master_id=? AND status IN ('new','confirmed')",
            (day, master_id),
        )

    async def available_slots(
        self,
        day: str,
        duration: int,
        exclude_order_id: Optional[int] = None,
        master_id: Optional[int] = None,
    ) -> list[str]:
        context = await load_slot_context(self, day)
        return compute_slots(
            day=day,
            duration=duration,
            settings=context["settings"],
            masters=context["masters"],
            schedules=context["schedules"],
            days_off=context["days_off"],
            orders=context["orders"],
            tz=self.tz,
            breaks=context["breaks"],
            master_id=master_id,
            exclude_order_id=exclude_order_id,
        )

    async def create_order(
        self,
        *,
        name: str,
        phone: str,
        service: dict,
        day: str,
        slot: str,
        channel: str,
        comment: str,
        source: str,
        tg_id: Optional[int],
        master_id: Optional[int] = None,
        consent_at: str = "",
        service_items: Optional[list[dict]] = None,
    ) -> tuple[Optional[dict], Optional[str]]:
        start = hhmm_to_min(slot)
        if not valid_iso_date(day):
            return None, "Некорректная дата"
        duration = int(service.get("duration") or 30)
        if start < 0:
            return None, "Некорректное время"
        if duration < 5 or duration > 480:
            return None, "Некорректная длительность услуги"

        async with self.transaction() as conn:
            await conn.lock(f"booking:{day}")
            context = await load_slot_context(conn, day)
            if not context["masters"]:
                return None, "Сейчас нет доступных мастеров. Позвоните нам."
            masters = context["masters"]
            chosen: Optional[dict] = None
            if master_id is not None:
                chosen = next(
                    (m for m in masters if int(m["id"]) == int(master_id)),
                    None,
                )
                if not chosen:
                    return None, "Мастер недоступен. Выберите другого."
                weekday = Date.fromisoformat(day).weekday()
                if not master_works(
                    master_id=int(master_id),
                    day=day,
                    weekday=weekday,
                    schedules=context["schedules"],
                    days_off=context["days_off"],
                ):
                    return None, "Мастер не работает в этот день. Выберите другую дату."

            available = compute_slots(
                day=day,
                duration=duration,
                settings=context["settings"],
                masters=masters,
                schedules=context["schedules"],
                days_off=context["days_off"],
                orders=context["orders"],
                tz=self.tz,
                breaks=context["breaks"],
                master_id=master_id,
            )
            if slot not in available:
                return None, "Это время уже занято. Выберите другое."

            if chosen is None and masters:
                for master in masters:
                    one = compute_slots(
                        day=day,
                        duration=duration,
                        settings=context["settings"],
                        masters=masters,
                        schedules=context["schedules"],
                        days_off=context["days_off"],
                        orders=context["orders"],
                        tz=self.tz,
                        breaks=context["breaks"],
                        master_id=int(master["id"]),
                    )
                    if slot in one:
                        chosen = master
                        break
                if not chosen:
                    return None, "Это время уже занято. Выберите другое."

            now = datetime.now(self.tz).isoformat(timespec="seconds")
            order_id = await conn.insert(
                "orders",
                {
                    "name": name,
                    "phone": phone,
                    "service_id": service.get("id"),
                    "service_name": service.get("name", ""),
                    "price": int(service.get("price") or 0),
                    "duration": duration,
                    "date": day,
                    "time": slot,
                    "channel": channel,
                    "comment": comment,
                    "status": "new",
                    "source": source,
                    "tg_id": tg_id,
                    "master_id": int(chosen["id"]) if chosen else None,
                    "master_name": chosen["name"] if chosen else "",
                    "consent_at": consent_at or now,
                    "public_token": secrets.token_hex(16),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            items = service_items or [service]
            for index, item in enumerate(items, start=1):
                await conn.insert(
                    "order_services",
                    {
                        "order_id": order_id,
                        "service_id": item.get("id"),
                        "service_name": item.get("name", ""),
                        "price": int(item.get("price") or 0),
                        "duration": int(item.get("duration") or 0),
                        "sort": index,
                        "created_at": now,
                    },
                )
            row = await conn.fetchone("SELECT * FROM orders WHERE id=?", (order_id,))
            return (dict(row) if row else None), None

    async def set_order_status(
        self,
        order_id: int,
        status: str,
        allowed_from: Optional[set[str]] = None,
    ) -> Optional[dict]:
        now = datetime.now(self.tz).isoformat(timespec="seconds")
        if allowed_from:
            placeholders = ", ".join("?" for _ in allowed_from)
            await self.execute(
                f"UPDATE orders SET status=?, updated_at=? "
                f"WHERE id=? AND status IN ({placeholders})",
                (status, now, order_id, *sorted(allowed_from)),
            )
        else:
            await self.execute(
                "UPDATE orders SET status=?, updated_at=? WHERE id=?",
                (status, now, order_id),
            )
        updated = await self.get_order(order_id)
        if updated and updated["status"] != status:
            return None
        return updated

    async def reschedule_order(
        self,
        order_id: int,
        day: str,
        slot: str,
        owner_tg_id: Optional[int] = None,
        owner_token: Optional[str] = None,
    ) -> tuple[Optional[dict], Optional[str]]:
        start = hhmm_to_min(slot)
        if not valid_iso_date(day):
            return None, "Некорректная дата"
        if Date.fromisoformat(day) < datetime.now(self.tz).date():
            return None, "Дата уже прошла"
        if start < 0:
            return None, "Некорректное время"
        async with self.transaction() as conn:
            await conn.lock(f"booking:{day}")
            row = await conn.fetchone("SELECT * FROM orders WHERE id=?", (order_id,))
            if not row:
                return None, "Заказ не найден"
            order = dict(row)
            if owner_tg_id is not None and int(order.get("tg_id") or 0) != int(owner_tg_id):
                return None, "Запись не найдена"
            if owner_token is not None and str(order.get("public_token") or "") != str(owner_token):
                return None, "Запись не найдена"
            if order["status"] not in {"new", "confirmed"}:
                return None, "Перенести можно только новый или подтверждённый заказ"
            duration = int(order["duration"] or 30)
            context = await load_slot_context(conn, day)
            if not context["masters"]:
                return None, "Сейчас нет доступных мастеров."

            current_master = order.get("master_id")
            active_ids = {int(m["id"]) for m in context["masters"]}
            try:
                current_master_id = int(current_master) if current_master is not None else None
            except (TypeError, ValueError):
                current_master_id = None
            if current_master_id not in active_ids:
                current_master_id = None
            if current_master_id is not None:
                weekday = Date.fromisoformat(day).weekday()
                if not master_works(
                    master_id=current_master_id,
                    day=day,
                    weekday=weekday,
                    schedules=context["schedules"],
                    days_off=context["days_off"],
                ):
                    return None, "Мастер не работает в этот день. Выберите другую дату."

            slots = compute_slots(
                day=day,
                duration=duration,
                settings=context["settings"],
                masters=context["masters"],
                schedules=context["schedules"],
                days_off=context["days_off"],
                orders=context["orders"],
                tz=self.tz,
                breaks=context["breaks"],
                master_id=current_master_id,
                exclude_order_id=order_id,
            )
            if slot not in slots:
                return None, "Это время уже занято. Выберите другое."

            chosen: Optional[dict] = None
            if current_master_id is not None:
                chosen = next(
                    (m for m in context["masters"] if int(m["id"]) == current_master_id),
                    None,
                )
            elif context["masters"]:
                for master in context["masters"]:
                    one = compute_slots(
                        day=day,
                        duration=duration,
                        settings=context["settings"],
                        masters=context["masters"],
                        schedules=context["schedules"],
                        days_off=context["days_off"],
                        orders=context["orders"],
                        tz=self.tz,
                        breaks=context["breaks"],
                        master_id=int(master["id"]),
                        exclude_order_id=order_id,
                    )
                    if slot in one:
                        chosen = master
                        break

            now = datetime.now(self.tz).isoformat(timespec="seconds")
            if chosen:
                await conn.execute(
                    "UPDATE orders SET date=?, time=?, master_id=?, master_name=?, "
                    "reminded=0, updated_at=? WHERE id=?",
                    (day, slot, int(chosen["id"]), chosen["name"], now, order_id),
                )
            else:
                await conn.execute(
                    "UPDATE orders SET date=?, time=?, reminded=0, updated_at=? WHERE id=?",
                    (day, slot, now, order_id),
                )
            updated = await conn.fetchone("SELECT * FROM orders WHERE id=?", (order_id,))
            return (dict(updated) if updated else None), None

    async def cancel_order_by_token(
        self, order_id: int, token: str
    ) -> tuple[Optional[dict], Optional[str]]:
        """Отмена записи по ссылке-токену с сайта."""
        async with self.transaction() as conn:
            row = await conn.fetchone("SELECT * FROM orders WHERE id=?", (order_id,))
            if not row:
                return None, "Запись не найдена"
            order = dict(row)
            if str(order.get("public_token") or "") != str(token):
                return None, "Запись не найдена"
            if order["status"] not in {"new", "confirmed"}:
                return None, "Запись уже нельзя отменить"
            try:
                start = datetime.strptime(
                    f"{order['date']} {order['time']}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=self.tz)
            except ValueError:
                return None, "Некорректная дата записи"
            if start <= datetime.now(self.tz):
                return None, "Запись уже началась — позвоните в салон"
            now = datetime.now(self.tz).isoformat(timespec="seconds")
            await conn.execute(
                "UPDATE orders SET status='cancelled', updated_at=? WHERE id=?",
                (now, order_id),
            )
            updated = await conn.fetchone("SELECT * FROM orders WHERE id=?", (order_id,))
            return (dict(updated) if updated else None), None

    async def cancel_order_by_client(
        self, order_id: int, tg_id: int
    ) -> tuple[Optional[dict], Optional[str]]:
        """Клиент отменяет только свою будущую запись."""
        async with self.transaction() as conn:
            row = await conn.fetchone("SELECT * FROM orders WHERE id=?", (order_id,))
            if not row:
                return None, "Запись не найдена"
            order = dict(row)
            if int(order.get("tg_id") or 0) != int(tg_id):
                return None, "Эта запись принадлежит другому клиенту"
            if order["status"] not in {"new", "confirmed"}:
                return None, "Запись уже нельзя отменить"
            try:
                start = datetime.strptime(
                    f"{order['date']} {order['time']}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=self.tz)
            except ValueError:
                return None, "Некорректная дата записи"
            if start <= datetime.now(self.tz):
                return None, "Запись уже началась — позвоните в салон"
            now = datetime.now(self.tz).isoformat(timespec="seconds")
            await conn.execute(
                "UPDATE orders SET status='cancelled', updated_at=? WHERE id=?",
                (now, order_id),
            )
            updated = await conn.fetchone("SELECT * FROM orders WHERE id=?", (order_id,))
            return (dict(updated) if updated else None), None

    async def get_order_services(self, order_id: int) -> list[dict]:
        return await self.fetchall(
            "SELECT * FROM order_services WHERE order_id=? ORDER BY sort, id",
            (order_id,),
        )

    async def pending_reminders(self) -> list[dict]:
        today = datetime.now(self.tz).date().isoformat()
        return await self.fetchall(
            "SELECT * FROM orders WHERE status='confirmed' AND reminded=0 AND date=? "
            "ORDER BY time",
            (today,),
        )

    async def mark_reminded(self, order_id: int) -> None:
        await self.execute("UPDATE orders SET reminded=1 WHERE id=?", (order_id,))

    # ---------- служебное ----------

    async def media_references(self) -> set[str]:
        references: set[str] = set()
        for table, column in (("services", "photo"), ("gallery", "image"), ("masters", "photo")):
            rows = await self.fetchall(
                f"SELECT {column} AS path FROM {table} WHERE {column}<>''"
            )
            for row in rows:
                value = str(row["path"] or "").strip().lstrip("/")
                if value:
                    references.add(value)
        return references

    async def source_counts(self) -> dict[str, int]:
        rows = await self.fetchall(
            "SELECT source, COUNT(*) AS c FROM orders GROUP BY source"
        )
        return {str(row["source"] or "unknown"): int(row["c"]) for row in rows}

    async def counts(self) -> dict[str, int]:
        today = datetime.now(self.tz).date().isoformat()
        queries = {
            "orders_total": "SELECT COUNT(*) AS c FROM orders",
            "orders_today": "SELECT COUNT(*) AS c FROM orders WHERE date=?",
            "orders_upcoming": "SELECT COUNT(*) AS c FROM orders "
            "WHERE status IN ('new','confirmed') AND date>=?",
            "orders_new": "SELECT COUNT(*) AS c FROM orders WHERE status='new'",
            "services": "SELECT COUNT(*) AS c FROM services",
            "gallery": "SELECT COUNT(*) AS c FROM gallery",
            "reviews": "SELECT COUNT(*) AS c FROM reviews",
            "masters": "SELECT COUNT(*) AS c FROM masters",
            "masters_active": "SELECT COUNT(*) AS c FROM masters WHERE active=1",
            "days_off": "SELECT COUNT(*) AS c FROM master_days_off WHERE date>=?",
            "breaks": "SELECT COUNT(*) AS c FROM master_breaks",
        }
        result: dict[str, int] = {}
        for key, sql in queries.items():
            params = (today,) if "?" in sql else ()
            row = await self.fetchone(sql, params)
            result[key] = int(row["c"]) if row else 0
        return result
