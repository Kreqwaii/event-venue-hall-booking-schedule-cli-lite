"""Booking scheduler with turnaround buffer, capacity checks, free-slot search, and export."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .pricing import AddonSpec, calculate_booking_price
from .storage import get_addon_by_name, get_hall_by_name


ISO_FMT = "%Y-%m-%dT%H:%M"


class BookingError(ValueError):
    """Raised when a booking violates schedule, capacity, or input rules."""


def parse_dt(value: str) -> datetime:
    for fmt in (ISO_FMT, "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise BookingError(f"Invalid datetime format '{value}'. Expected YYYY-MM-DDTHH:MM")


def format_dt(dt: datetime) -> str:
    return dt.strftime(ISO_FMT)


def _overlaps_with_turnaround(
    new_start: datetime,
    new_end: datetime,
    existing_start: datetime,
    existing_end: datetime,
    turnaround_minutes: int,
) -> bool:
    buf = timedelta(minutes=turnaround_minutes)
    # Existing booking blocks [existing_start - buf, existing_end + buf)
    # Equivalently, new booking + turnaround must not overlap existing
    return new_start < (existing_end + buf) and (new_end + buf) > existing_start


def find_conflicts(
    conn: sqlite3.Connection,
    hall_id: int,
    start_dt: datetime,
    end_dt: datetime,
    turnaround_minutes: int,
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM bookings
        WHERE hall_id = ? AND status IN ('hold', 'confirmed')
        ORDER BY start_ts ASC
        """,
        (hall_id,),
    ).fetchall()

    conflicts: List[Dict[str, Any]] = []
    for row in rows:
        ex_start = parse_dt(row["start_ts"])
        ex_end = parse_dt(row["end_ts"])
        if _overlaps_with_turnaround(start_dt, end_dt, ex_start, ex_end, turnaround_minutes):
            conflicts.append(dict(row))
    return conflicts


def book_hall(
    conn: sqlite3.Connection,
    hall_name: str,
    client_name: str,
    start_ts: str,
    end_ts: str,
    guests: int,
    event_title: str = "",
    addon_names: Sequence[str] = (),
    deposit_percent: float = 30.0,
    status: str = "confirmed",
) -> Dict[str, Any]:
    if status not in ("hold", "confirmed"):
        raise BookingError("Initial booking status must be 'hold' or 'confirmed'")

    hall = get_hall_by_name(conn, hall_name)
    if not hall:
        raise BookingError(f"Hall '{hall_name}' not found")

    if guests <= 0:
        raise BookingError("guests must be positive")
    if guests > hall["capacity"]:
        raise BookingError(
            f"Guest count ({guests}) exceeds hall '{hall['name']}' capacity ({hall['capacity']})"
        )

    start_dt = parse_dt(start_ts)
    end_dt = parse_dt(end_ts)
    if end_dt <= start_dt:
        raise BookingError("end_ts must be after start_ts")

    # Check operating hours if same-day
    if start_dt.date() == end_dt.date():
        open_dt = start_dt.replace(hour=hall["open_hour"], minute=0, second=0, microsecond=0)
        if hall["close_hour"] == 24:
            close_dt = open_dt + timedelta(hours=24 - hall["open_hour"])
        else:
            close_dt = start_dt.replace(hour=hall["close_hour"], minute=0, second=0, microsecond=0)
        if start_dt < open_dt or end_dt > close_dt:
            raise BookingError(
                f"Booking {format_dt(start_dt)}..{format_dt(end_dt)} is outside hall hours "
                f"({hall['open_hour']:02d}:00..{hall['close_hour']:02d}:00)"
            )

    conflicts = find_conflicts(
        conn=conn,
        hall_id=hall["id"],
        start_dt=start_dt,
        end_dt=end_dt,
        turnaround_minutes=hall["turnaround_minutes"],
    )
    if conflicts:
        c = conflicts[0]
        raise BookingError(
            f"Schedule conflict with booking #{c['id']} ({c['start_ts']}..{c['end_ts']}) "
            f"including {hall['turnaround_minutes']}m turnaround buffer"
        )

    addon_specs: List[AddonSpec] = []
    for raw_name in addon_names:
        name = raw_name.strip()
        if not name:
            continue
        addon = get_addon_by_name(conn, name)
        if not addon:
            raise BookingError(f"Addon '{name}' not found")
        addon_specs.append(
            AddonSpec(
                addon_id=addon["id"],
                name=addon["name"],
                pricing_type=addon["pricing_type"],
                price=addon["price"],
                quantity=1,
            )
        )

    duration_minutes = int((end_dt - start_dt).total_seconds() // 60)
    price = calculate_booking_price(
        hourly_rate=hall["hourly_rate"],
        duration_minutes=duration_minutes,
        guests=guests,
        addons=addon_specs,
        deposit_percent=deposit_percent,
    )

    cur = conn.execute(
        """
        INSERT INTO bookings (
            hall_id, client_name, event_title, guests,
            start_ts, end_ts, status,
            base_total, addons_total, grand_total,
            deposit_percent, deposit_amount
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            hall["id"],
            client_name.strip(),
            event_title.strip(),
            guests,
            format_dt(start_dt),
            format_dt(end_dt),
            status,
            price.base_total,
            price.addons_total,
            price.grand_total,
            price.deposit_percent,
            price.deposit_amount,
        ),
    )
    booking_id = int(cur.lastrowid)

    for addon_id, _name, qty, line_total in price.addon_lines:
        conn.execute(
            """
            INSERT INTO booking_addons (booking_id, addon_id, quantity, line_total)
            VALUES (?, ?, ?, ?)
            """,
            (booking_id, addon_id, qty, line_total),
        )
    conn.commit()

    return get_booking(conn, booking_id)  # type: ignore[return-value]


def get_booking(conn: sqlite3.Connection, booking_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT b.*, h.name AS hall_name
        FROM bookings b
        JOIN halls h ON h.id = b.hall_id
        WHERE b.id = ?
        """,
        (booking_id,),
    ).fetchone()
    return dict(row) if row else None


def update_booking_status(conn: sqlite3.Connection, booking_id: int, new_status: str) -> Dict[str, Any]:
    if new_status not in ("hold", "confirmed", "cancelled"):
        raise BookingError(f"Invalid status: {new_status}")
    existing = get_booking(conn, booking_id)
    if not existing:
        raise BookingError(f"Booking #{booking_id} not found")
    conn.execute("UPDATE bookings SET status = ? WHERE id = ?", (new_status, booking_id))
    conn.commit()
    return get_booking(conn, booking_id)  # type: ignore[return-value]


def list_bookings(
    conn: sqlite3.Connection,
    hall_name: Optional[str] = None,
    date_str: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    query = """
        SELECT b.*, h.name AS hall_name
        FROM bookings b
        JOIN halls h ON h.id = b.hall_id
        WHERE 1=1
    """
    params: List[Any] = []
    if hall_name:
        query += " AND h.name = ?"
        params.append(hall_name.strip())
    if date_str:
        query += " AND substr(b.start_ts, 1, 10) = ?"
        params.append(date_str.strip())
    if status:
        query += " AND b.status = ?"
        params.append(status.strip())
    query += " ORDER BY b.start_ts ASC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def find_free_slots(
    conn: sqlite3.Connection,
    hall_name: str,
    date_str: str,
    min_duration_minutes: int = 60,
) -> List[Tuple[str, str]]:
    hall = get_hall_by_name(conn, hall_name)
    if not hall:
        raise BookingError(f"Hall '{hall_name}' not found")

    try:
        day = datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except ValueError as exc:
        raise BookingError(f"Invalid date '{date_str}'. Expected YYYY-MM-DD") from exc

    day_start = day.replace(hour=hall["open_hour"], minute=0, second=0, microsecond=0)
    if hall["close_hour"] == 24:
        day_end = day_start + timedelta(hours=24 - hall["open_hour"])
    else:
        day_end = day.replace(hour=hall["close_hour"], minute=0, second=0, microsecond=0)

    buf = timedelta(minutes=hall["turnaround_minutes"])
    rows = conn.execute(
        """
        SELECT start_ts, end_ts FROM bookings
        WHERE hall_id = ? AND status IN ('hold', 'confirmed')
          AND substr(start_ts, 1, 10) = ?
        ORDER BY start_ts ASC
        """,
        (hall["id"], date_str.strip()),
    ).fetchall()

    busy_intervals: List[Tuple[datetime, datetime]] = []
    for r in rows:
        b_start = max(day_start, parse_dt(r["start_ts"]) - buf)
        b_end = min(day_end, parse_dt(r["end_ts"]) + buf)
        if b_end > b_start:
            busy_intervals.append((b_start, b_end))

    # Merge overlapping busy intervals
    merged: List[Tuple[datetime, datetime]] = []
    for start, end in sorted(busy_intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    free_slots: List[Tuple[str, str]] = []
    cursor = day_start
    min_delta = timedelta(minutes=min_duration_minutes)

    for b_start, b_end in merged:
        if b_start - cursor >= min_delta:
            free_slots.append((format_dt(cursor), format_dt(b_start)))
        cursor = max(cursor, b_end)

    if day_end - cursor >= min_delta:
        free_slots.append((format_dt(cursor), format_dt(day_end)))

    return free_slots


def export_bookings(
    conn: sqlite3.Connection,
    output_path: str | Path,
    fmt: str = "json",
    hall_name: Optional[str] = None,
    date_str: Optional[str] = None,
) -> int:
    rows = list_bookings(conn, hall_name=hall_name, date_str=date_str)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    fmt_lower = fmt.lower()
    if fmt_lower == "json":
        out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    elif fmt_lower == "csv":
        fieldnames = [
            "id",
            "hall_id",
            "hall_name",
            "client_name",
            "event_title",
            "guests",
            "start_ts",
            "end_ts",
            "status",
            "base_total",
            "addons_total",
            "grand_total",
            "deposit_percent",
            "deposit_amount",
            "created_at",
        ]
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
    else:
        raise BookingError(f"Unsupported export format: {fmt}")

    return len(rows)
