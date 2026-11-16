#!/usr/bin/env python3
"""
Перенос данных из SQLite в PostgreSQL/Neon.

Фото не копируются: они лежат файлами в media/ и переносятся отдельно
(rsync/scp/volume). Скрипт переносит услуги, мастеров, графики, заказы,
отзывы, галерею и настройки.

Использование:
    DATABASE_URL='postgresql://...' python scripts/migrate_sqlite_to_postgres.py
    python scripts/migrate_sqlite_to_postgres.py --source data/barbershop.db --target 'postgresql://...'

Перед запуском остановите приложение, чтобы в SQLite не писались новые заказы.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db_backend import PostgresBackend  # noqa: E402
from app.schema import POSTGRES_SCHEMA  # noqa: E402

TABLES = [
    ("settings", "key"),
    ("meta", "key"),
    ("services", "id"),
    ("gallery", "id"),
    ("reviews", "id"),
    ("why", "id"),
    ("masters", "id"),
    ("master_schedules", "id"),
    ("master_days_off", "id"),
    ("orders", "id"),
    ("order_services", "id"),
    ("site_stats", "id"),
]

# Колонки, которые появились позже. Если их нет в старой SQLite — подставляем.
DEFAULTS = {
    "orders": {"master_id": None, "master_name": "", "consent_at": ""},
    "master_schedules": {"work_start": "10:00", "work_end": "21:00", "lunch_start": "", "lunch_end": ""},
}

RENAMES = {
    "master_schedules": {"start": "work_start", "end": "work_end"},
}


def sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def read_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(row) for row in rows]


async def target_columns(conn: Any, table: str) -> list[str]:
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name=$1",
        table,
    )
    return [row["column_name"] for row in rows]


async def main() -> int:
    parser = argparse.ArgumentParser(description="Перенос SQLite → PostgreSQL/Neon")
    parser.add_argument("--source", default=str(ROOT / "data" / "barbershop.db"))
    parser.add_argument("--target", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument(
        "--force",
        action="store_true",
        help="Очистить целевые таблицы и перенести заново (опасно)",
    )
    args = parser.parse_args()

    source = Path(args.source)
    target = (args.target or "").strip()
    if not source.exists():
        print(f"SQLite не найден: {source}", file=sys.stderr)
        return 1
    if not target:
        print("Укажите DATABASE_URL или --target", file=sys.stderr)
        return 1

    try:
        import asyncpg
    except ImportError:
        print(
            "Нужен драйвер PostgreSQL: pip install -r requirements-postgres.txt",
            file=sys.stderr,
        )
        return 1

    dsn = PostgresBackend._clean_url(target)
    pg = await asyncpg.connect(dsn=dsn, statement_cache_size=0)
    sqlite = sqlite3.connect(source)
    sqlite.row_factory = sqlite3.Row
    try:
        for statement in POSTGRES_SCHEMA.split(";"):
            statement = statement.strip()
            if statement:
                await pg.execute(statement)

        existing = await pg.fetchval("SELECT COUNT(*) FROM orders")
        if existing and not args.force:
            print(
                f"В PostgreSQL уже есть {existing} заказов. "
                "Остановитесь или запустите с --force, если это осознанный перенос.",
                file=sys.stderr,
            )
            return 1
        if existing and args.force:
            print("--force: очищаю целевые таблицы перед переносом", file=sys.stderr)
            await pg.execute(
                "TRUNCATE settings, meta, services, gallery, reviews, why, "
                "masters, master_schedules, master_days_off, orders, order_services, site_stats "
                "RESTART IDENTITY CASCADE"
            )

        source_tables = sqlite_tables(sqlite)
        total = 0
        for table, key in TABLES:
            if table not in source_tables:
                print(f"· {table}: в SQLite нет, пропускаю")
                continue
            rows = read_rows(sqlite, table)
            if not rows:
                print(f"· {table}: 0")
                continue

            target_cols = set(await target_columns(pg, table))
            source_cols = sqlite_columns(sqlite, table)
            rename = RENAMES.get(table, {})
            mapped = []
            for column in source_cols:
                target_name = rename.get(column, column)
                if target_name in target_cols:
                    mapped.append((column, target_name))
            for column, default in DEFAULTS.get(table, {}).items():
                if column not in {name for _, name in mapped}:
                    mapped.append((None, column))

            if not mapped:
                print(f"· {table}: нет общих колонок, пропускаю")
                continue

            columns = [name for _, name in mapped]
            placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
            sql = (
                f"INSERT INTO {table} ({', '.join(columns)}) "
                f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            )
            payload = []
            for row in rows:
                values = []
                for source_column, target_column in mapped:
                    if source_column is None:
                        values.append(DEFAULTS[table][target_column])
                    else:
                        values.append(row.get(source_column))
                payload.append(tuple(values))

            await pg.executemany(sql, payload)
            total += len(payload)
            print(f"· {table}: {len(payload)}")

        # После явных id нужно сдвинуть последовательности.
        for table, key in TABLES:
            if key != "id" or table not in source_tables:
                continue
            max_id = await pg.fetchval(f"SELECT COALESCE(MAX(id), 0) FROM {table}")
            sequence = await pg.fetchval("SELECT pg_get_serial_sequence($1, 'id')", table)
            if sequence:
                if max_id:
                    await pg.execute("SELECT setval($1::regclass, $2, true)", sequence, max_id)
                else:
                    await pg.execute("SELECT setval($1::regclass, 1, false)", sequence)

        print(f"\nГотово. Перенесено строк: {total}.")
        print("Фото не переносились: скопируйте папку media/ на новый сервер.")
        return 0
    finally:
        sqlite.close()
        await pg.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
