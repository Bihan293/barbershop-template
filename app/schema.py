from __future__ import annotations
"""DDL для SQLite и PostgreSQL.

Схемы намеренно повторяют друг друга по смыслу: текстовые поля и даты
хранятся строками, чтобы код бизнес-логики был одинаковым для обеих баз.
"""

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL DEFAULT 0,
    duration INTEGER NOT NULL DEFAULT 60,
    photo TEXT NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gallery (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    rating INTEGER NOT NULL DEFAULT 5,
    source TEXT NOT NULL DEFAULT '2ГИС',
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS why (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    icon TEXT NOT NULL DEFAULT '✂️',
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS masters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    photo TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    sort INTEGER NOT NULL DEFAULT 0,
    break_start TEXT NOT NULL DEFAULT '',
    break_end TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS master_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    master_id INTEGER NOT NULL,
    weekday INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    work_start TEXT NOT NULL DEFAULT '10:00',
    work_end TEXT NOT NULL DEFAULT '21:00',
    lunch_start TEXT NOT NULL DEFAULT '',
    lunch_end TEXT NOT NULL DEFAULT '',
    UNIQUE(master_id, weekday)
);

CREATE TABLE IF NOT EXISTS master_breaks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    master_id INTEGER NOT NULL,
    weekday INTEGER NOT NULL,
    break_start TEXT NOT NULL,
    break_end TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT 'Перерыв',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS master_days_off (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    master_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(master_id, date)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    service_id INTEGER,
    service_name TEXT NOT NULL,
    price INTEGER NOT NULL DEFAULT 0,
    duration INTEGER NOT NULL DEFAULT 60,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'telegram',
    comment TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    source TEXT NOT NULL DEFAULT 'site',
    tg_id INTEGER,
    master_id INTEGER,
    master_name TEXT NOT NULL DEFAULT '',
    consent_at TEXT NOT NULL DEFAULT '',
    public_token TEXT NOT NULL DEFAULT '',
    reminded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_master_breaks ON master_breaks(master_id, weekday);
CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(date, time);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_tg ON orders(tg_id);

CREATE TABLE IF NOT EXISTS order_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    service_id INTEGER,
    service_name TEXT NOT NULL,
    price INTEGER NOT NULL DEFAULT 0,
    duration INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_services_order ON order_services(order_id);

CREATE TABLE IF NOT EXISTS site_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    value TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',
    plus INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL DEFAULT 0,
    duration INTEGER NOT NULL DEFAULT 60,
    photo TEXT NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gallery (
    id BIGSERIAL PRIMARY KEY,
    image TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    rating INTEGER NOT NULL DEFAULT 5,
    source TEXT NOT NULL DEFAULT '2ГИС',
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS why (
    id BIGSERIAL PRIMARY KEY,
    icon TEXT NOT NULL DEFAULT '✂️',
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS masters (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    photo TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    sort INTEGER NOT NULL DEFAULT 0,
    break_start TEXT NOT NULL DEFAULT '',
    break_end TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS master_schedules (
    id BIGSERIAL PRIMARY KEY,
    master_id BIGINT NOT NULL,
    weekday INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    work_start TEXT NOT NULL DEFAULT '10:00',
    work_end TEXT NOT NULL DEFAULT '21:00',
    lunch_start TEXT NOT NULL DEFAULT '',
    lunch_end TEXT NOT NULL DEFAULT '',
    UNIQUE(master_id, weekday)
);

CREATE TABLE IF NOT EXISTS master_breaks (
    id BIGSERIAL PRIMARY KEY,
    master_id BIGINT NOT NULL,
    weekday INTEGER NOT NULL,
    break_start TEXT NOT NULL,
    break_end TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT 'Перерыв',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS master_days_off (
    id BIGSERIAL PRIMARY KEY,
    master_id BIGINT NOT NULL,
    date TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(master_id, date)
);

CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    service_id BIGINT,
    service_name TEXT NOT NULL,
    price INTEGER NOT NULL DEFAULT 0,
    duration INTEGER NOT NULL DEFAULT 60,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'telegram',
    comment TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    source TEXT NOT NULL DEFAULT 'site',
    tg_id BIGINT,
    master_id BIGINT,
    master_name TEXT NOT NULL DEFAULT '',
    consent_at TEXT NOT NULL DEFAULT '',
    public_token TEXT NOT NULL DEFAULT '',
    reminded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_master_breaks ON master_breaks(master_id, weekday);
CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(date, time);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_tg ON orders(tg_id);

CREATE TABLE IF NOT EXISTS order_services (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL,
    service_id BIGINT,
    service_name TEXT NOT NULL,
    price INTEGER NOT NULL DEFAULT 0,
    duration INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_services_order ON order_services(order_id);

CREATE TABLE IF NOT EXISTS site_stats (
    id BIGSERIAL PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',
    plus INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
