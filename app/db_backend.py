from __future__ import annotations
"""Низкоуровневые адаптеры SQLite и PostgreSQL.

Бизнес-логика в app/database.py работает через небольшой общий интерфейс:
fetchall/fetchone/execute/insert/transaction. Для PostgreSQL знаки «?»
автоматически превращаются в «$1, $2, ...».
"""
import asyncio
import contextlib
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiosqlite

from .schema import POSTGRES_SCHEMA, SQLITE_SCHEMA

LOG = logging.getLogger("lezvie.db")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def pg_placeholders(sql: str) -> str:
    """Переводит «?» в «$1, $2, ...» для asyncpg."""
    result: list[str] = []
    number = 0
    for char in sql:
        if char == "?":
            number += 1
            result.append(f"${number}")
        else:
            result.append(char)
    return "".join(result)


def _insert_sql(table: str, data: dict[str, Any], *, postgres: bool) -> tuple[str, tuple]:
    if not _IDENT.match(table):
        raise ValueError(f"Недопустимое имя таблицы: {table}")
    columns = list(data.keys())
    for column in columns:
        if not _IDENT.match(column):
            raise ValueError(f"Недопустимое имя колонки: {column}")
    placeholders = ", ".join("?" for _ in columns)
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({placeholders})"
    )
    if postgres:
        sql = pg_placeholders(sql) + " RETURNING id"
    return sql, tuple(data.values())


class SqliteConn:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = await self._db.execute(sql, params)
        try:
            rows = await cur.fetchall()
        finally:
            await cur.close()
        return [dict(row) for row in rows]

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        rows = await self.fetchall(sql, params)
        return rows[0] if rows else None

    async def execute(self, sql: str, params: tuple = ()) -> int:
        cur = await self._db.execute(sql, params)
        try:
            last_id = int(cur.lastrowid or 0) if sql.lstrip().upper().startswith("INSERT") else 0
        finally:
            await cur.close()
        return last_id

    async def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        await self._db.executemany(sql, params_list)

    async def insert(self, table: str, data: dict[str, Any]) -> int:
        sql, params = _insert_sql(table, data, postgres=False)
        return await self.execute(sql, params)

    async def lock(self, key: str) -> None:
        """SQLite сериализует записи через BEGIN IMMEDIATE."""
        return None


class PostgresConn:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        rows = await self._conn.fetch(pg_placeholders(sql), *params)
        return [dict(row) for row in rows]

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        row = await self._conn.fetchrow(pg_placeholders(sql), *params)
        return dict(row) if row else None

    async def execute(self, sql: str, params: tuple = ()) -> int:
        await self._conn.execute(pg_placeholders(sql), *params)
        return 0

    async def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        await self._conn.executemany(pg_placeholders(sql), params_list)

    async def insert(self, table: str, data: dict[str, Any]) -> int:
        sql, params = _insert_sql(table, data, postgres=True)
        value = await self._conn.fetchval(sql, *params)
        return int(value or 0)

    async def lock(self, key: str) -> None:
        # Транзакционная блокировка по дню: защищает от двойной записи
        # при нескольких репликах/процессах на PostgreSQL.
        await self._conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext($1))",
            str(key),
        )


class SqliteBackend:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.executescript(SQLITE_SCHEMA)
        await self._db.commit()
        await self._migrate()
        await self._db.commit()

    async def _columns(self, table: str) -> set[str]:
        cur = await self._db.execute(f"PRAGMA table_info({table})")
        try:
            rows = await cur.fetchall()
        finally:
            await cur.close()
        return {str(row["name"]) for row in rows}

    async def _migrate(self) -> None:
        columns = await self._columns("orders")
        additions = {
            "master_id": "INTEGER",
            "master_name": "TEXT NOT NULL DEFAULT ''",
            "consent_at": "TEXT NOT NULL DEFAULT ''",
            "public_token": "TEXT NOT NULL DEFAULT ''",
        }
        for column, ddl in additions.items():
            if column not in columns:
                LOG.info("Миграция SQLite: orders.%s", column)
                await self._db.execute(f"ALTER TABLE orders ADD COLUMN {column} {ddl}")

        schedule_columns = await self._columns("master_schedules")
        if "start" in schedule_columns and "work_start" not in schedule_columns:
            LOG.info("Миграция SQLite: master_schedules.start → work_start")
            await self._db.execute(
                "ALTER TABLE master_schedules RENAME COLUMN start TO work_start"
            )
        if "end" in schedule_columns and "work_end" not in schedule_columns:
            LOG.info("Миграция SQLite: master_schedules.end → work_end")
            await self._db.execute(
                "ALTER TABLE master_schedules RENAME COLUMN end TO work_end"
            )

        break_columns = await self._columns("master_breaks")
        if "start" in break_columns and "break_start" not in break_columns:
            LOG.info("Миграция SQLite: master_breaks.start → break_start")
            await self._db.execute(
                "ALTER TABLE master_breaks RENAME COLUMN start TO break_start"
            )
        if "end" in break_columns and "break_end" not in break_columns:
            LOG.info("Миграция SQLite: master_breaks.end → break_end")
            await self._db.execute(
                "ALTER TABLE master_breaks RENAME COLUMN end TO break_end"
            )

        # Старый индекс запрещал две записи на одно время у разных мастеров.
        cur = await self._db.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_orders_active_slot'"
        )
        try:
            row = await cur.fetchone()
        finally:
            await cur.close()
        if row and "master_id" not in (row["sql"] or ""):
            LOG.info("Миграция SQLite: пересоздаю индекс активных слотов")
            await self._db.execute("DROP INDEX IF EXISTS idx_orders_active_slot")
        await self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_active_slot "
            "ON orders(date, time, master_id) WHERE status IN ('new', 'confirmed')"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_master ON orders(master_id, date, time)"
        )
        await self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_public_token "
            "ON orders(public_token) WHERE public_token <> ''"
        )

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        async with self._lock:
            return await SqliteConn(self._db).fetchall(sql, params)

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        rows = await self.fetchall(sql, params)
        return rows[0] if rows else None

    async def execute(self, sql: str, params: tuple = ()) -> int:
        async with self._lock:
            last_id = await SqliteConn(self._db).execute(sql, params)
            await self._db.commit()
            return last_id

    async def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        async with self._lock:
            await SqliteConn(self._db).execute_many(sql, params_list)
            await self._db.commit()

    async def insert(self, table: str, data: dict[str, Any]) -> int:
        async with self._lock:
            last_id = await SqliteConn(self._db).insert(table, data)
            await self._db.commit()
            return last_id

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[SqliteConn]:
        async with self._lock:
            await self._db.execute("BEGIN IMMEDIATE")
            try:
                yield SqliteConn(self._db)
                await self._db.commit()
            except BaseException:
                await self._db.rollback()
                raise

    async def database_size(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self.path) + suffix)
            with contextlib.suppress(OSError):
                total += path.stat().st_size
        return total


class PostgresBackend:
    def __init__(self, url: str) -> None:
        self.url = self._clean_url(url)
        self._pool: Any = None

    @staticmethod
    def _clean_url(url: str) -> str:
        """Убирает параметры, которые asyncpg не понимает (Neon/Supabase)."""
        text = str(url or "").strip()
        if text.startswith("postgres://"):
            text = "postgresql://" + text[len("postgres://"):]
        parts = urlsplit(text)
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in {"channel_binding", "pgbouncer"}
        ]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    async def connect(self) -> None:
        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover - зависит от окружения
            raise RuntimeError(
                "Для DATABASE_URL нужен пакет asyncpg. Установите: pip install -r requirements-postgres.txt"
            ) from exc

        self._pool = await asyncpg.create_pool(
            dsn=self.url,
            # Не держим соединение открытым постоянно: так Neon может
            # уходить в scale-to-zero, когда бот и сайт простаивают.
            min_size=0,
            max_size=5,
            command_timeout=20,
            statement_cache_size=0,  # совместимость с PgBouncer/Neon pooler
            max_inactive_connection_lifetime=60,
            server_settings={"application_name": "lezvie-barbershop"},
        )
        async with self._pool.acquire() as conn:
            for statement in POSTGRES_SCHEMA.split(";"):
                statement = statement.strip()
                if statement:
                    await conn.execute(statement)
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS master_id BIGINT")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS master_name TEXT NOT NULL DEFAULT ''")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS consent_at TEXT NOT NULL DEFAULT ''")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS public_token TEXT NOT NULL DEFAULT ''")
            legacy_start = await conn.fetchrow(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='master_schedules' AND column_name='start'"
            )
            if legacy_start:
                await conn.execute(
                    "ALTER TABLE master_schedules RENAME COLUMN start TO work_start"
                )
            legacy_end = await conn.fetchrow(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='master_schedules' AND column_name='end'"
            )
            if legacy_end:
                await conn.execute(
                    "ALTER TABLE master_schedules RENAME COLUMN end TO work_end"
                )
            legacy_break_start = await conn.fetchrow(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='master_breaks' AND column_name='start'"
            )
            if legacy_break_start:
                await conn.execute(
                    "ALTER TABLE master_breaks RENAME COLUMN start TO break_start"
                )
            legacy_break_end = await conn.fetchrow(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='master_breaks' AND column_name='end'"
            )
            if legacy_break_end:
                await conn.execute(
                    "ALTER TABLE master_breaks RENAME COLUMN end TO break_end"
                )
            row = await conn.fetchrow(
                "SELECT indexdef FROM pg_indexes WHERE indexname='idx_orders_active_slot'"
            )
            if row and "master_id" not in (row["indexdef"] or ""):
                LOG.info("Миграция PostgreSQL: пересоздаю индекс активных слотов")
                await conn.execute("DROP INDEX IF EXISTS idx_orders_active_slot")
            await conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_active_slot "
                "ON orders(date, time, master_id) WHERE status IN ('new', 'confirmed')"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_master ON orders(master_id, date, time)"
            )
            await conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_public_token "
                "ON orders(public_token) WHERE public_token <> ''"
            )
        LOG.info("PostgreSQL подключён")

    async def close(self) -> None:
        if self._pool is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._pool.close(), timeout=5)
            self._pool = None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        async with self._pool.acquire() as conn:
            return await PostgresConn(conn).fetchall(sql, params)

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        async with self._pool.acquire() as conn:
            return await PostgresConn(conn).fetchone(sql, params)

    async def execute(self, sql: str, params: tuple = ()) -> int:
        async with self._pool.acquire() as conn:
            return await PostgresConn(conn).execute(sql, params)

    async def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        async with self._pool.acquire() as conn:
            await PostgresConn(conn).execute_many(sql, params_list)

    async def insert(self, table: str, data: dict[str, Any]) -> int:
        async with self._pool.acquire() as conn:
            return await PostgresConn(conn).insert(table, data)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[PostgresConn]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                yield PostgresConn(conn)

    async def database_size(self) -> int:
        async with self._pool.acquire() as conn:
            value = await conn.fetchval("SELECT pg_database_size(current_database())")
        return int(value or 0)
