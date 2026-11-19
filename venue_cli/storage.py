"""SQLite storage layer for event venue & hall bookings."""

from __future__ import annotations

from contextlib import closing
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS halls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    hourly_rate REAL NOT NULL CHECK (hourly_rate >= 0),
    turnaround_minutes INTEGER NOT NULL DEFAULT 30 CHECK (turnaround_minutes >= 0),
    open_hour INTEGER NOT NULL DEFAULT 9 CHECK (open_hour >= 0 AND open_hour <= 23),
    close_hour INTEGER NOT NULL DEFAULT 23 CHECK (close_hour >= 1 AND close_hour <= 24),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS addons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    pricing_type TEXT NOT NULL CHECK (pricing_type IN ('flat', 'per_hour', 'per_guest')),
    price REAL NOT NULL CHECK (price >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hall_id INTEGER NOT NULL REFERENCES halls(id) ON DELETE CASCADE,
    client_name TEXT NOT NULL,
    event_title TEXT NOT NULL DEFAULT '',
    guests INTEGER NOT NULL CHECK (guests > 0),
    start_ts TEXT NOT NULL,
    end_ts TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('hold', 'confirmed', 'cancelled')),
    base_total REAL NOT NULL DEFAULT 0.0,
    addons_total REAL NOT NULL DEFAULT 0.0,
    grand_total REAL NOT NULL DEFAULT 0.0,
    deposit_percent REAL NOT NULL DEFAULT 30.0,
    deposit_amount REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS booking_addons (
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    addon_id INTEGER NOT NULL REFERENCES addons(id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    line_total REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (booking_id, addon_id)
);

CREATE INDEX IF NOT EXISTS idx_bookings_hall_time
    ON bookings(hall_id, start_ts, end_ts);
"""


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if str(db_path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str | Path) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def create_hall(
    conn: sqlite3.Connection,
    name: str,
    capacity: int,
    hourly_rate: float,
    turnaround_minutes: int = 30,
    open_hour: int = 9,
    close_hour: int = 23,
) -> int:
    if open_hour >= close_hour:
        raise ValueError("open_hour must be less than close_hour")
    cur = conn.execute(
        """
        INSERT INTO halls (name, capacity, hourly_rate, turnaround_minutes, open_hour, close_hour)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (name.strip(), capacity, hourly_rate, turnaround_minutes, open_hour, close_hour),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_hall_by_name(conn: sqlite3.Connection, name: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM halls WHERE name = ?", (name.strip(),)).fetchone()
    return dict(row) if row else None


def get_hall_by_id(conn: sqlite3.Connection, hall_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM halls WHERE id = ?", (hall_id,)).fetchone()
    return dict(row) if row else None


def list_halls(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT * FROM halls ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


def create_addon(
    conn: sqlite3.Connection,
    name: str,
    pricing_type: str,
    price: float,
) -> int:
    cur = conn.execute(
        "INSERT INTO addons (name, pricing_type, price) VALUES (?, ?, ?)",
        (name.strip(), pricing_type, price),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_addon_by_name(conn: sqlite3.Connection, name: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM addons WHERE name = ?", (name.strip(),)).fetchone()
    return dict(row) if row else None


def list_addons(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT * FROM addons ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]
