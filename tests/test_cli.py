"""Unit tests for venue_cli (storage, pricing, scheduler, CLI)."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from venue_cli.cli import main as cli_main
from venue_cli.pricing import AddonSpec, calculate_addon_line, calculate_booking_price
from venue_cli.scheduler import (
    BookingError,
    book_hall,
    export_bookings,
    find_free_slots,
    list_bookings,
    parse_dt,
    update_booking_status,
)
from venue_cli.storage import (
    create_addon,
    create_hall,
    get_connection,
    init_db,
    list_addons,
    list_halls,
)


class VenueCliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tmp.name) / "test_venue.db"
        init_db(self.db_path)
        self.conn = get_connection(self.db_path)
        create_hall(self.conn, "Loft-A", capacity=40, hourly_rate=100.0, turnaround_minutes=30, open_hour=9, close_hour=22)
        create_hall(self.conn, "Conf-B", capacity=15, hourly_rate=60.0, turnaround_minutes=15, open_hour=8, close_hour=20)
        create_addon(self.conn, "Projector", "flat", 50.0)
        create_addon(self.conn, "Sound", "per_hour", 20.0)
        create_addon(self.conn, "Coffee", "per_guest", 5.0)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    # --- Storage tests ---
    def test_01_list_halls(self) -> None:
        halls = list_halls(self.conn)
        self.assertEqual(len(halls), 2)
        self.assertEqual(halls[0]["name"], "Loft-A")

    def test_02_duplicate_hall_raises(self) -> None:
        with self.assertRaises(Exception):
            create_hall(self.conn, "Loft-A", 10, 50.0)

    def test_03_invalid_hall_hours_raises(self) -> None:
        with self.assertRaises(ValueError):
            create_hall(self.conn, "BadHall", 10, 50.0, open_hour=20, close_hour=18)

    def test_04_list_addons(self) -> None:
        addons = list_addons(self.conn)
        self.assertEqual(len(addons), 3)

    # --- Pricing tests ---
    def test_05_addon_flat(self) -> None:
        self.assertEqual(calculate_addon_line("flat", 50.0, hours=3, guests=20), 50.0)

    def test_06_addon_per_hour(self) -> None:
        self.assertEqual(calculate_addon_line("per_hour", 20.0, hours=2.5, guests=10), 50.0)

    def test_07_addon_per_guest(self) -> None:
        self.assertEqual(calculate_addon_line("per_guest", 5.0, hours=2, guests=25), 125.0)

    def test_08_addon_invalid_type(self) -> None:
        with self.assertRaises(ValueError):
            calculate_addon_line("per_mile", 10.0, 1, 1)

    def test_09_booking_price_breakdown(self) -> None:
        specs = [
            AddonSpec(1, "Projector", "flat", 50.0),
            AddonSpec(2, "Sound", "per_hour", 20.0),
            AddonSpec(3, "Coffee", "per_guest", 5.0),
        ]
        res = calculate_booking_price(100.0, duration_minutes=120, guests=10, addons=specs, deposit_percent=25.0)
        self.assertEqual(res.base_total, 200.0)
        self.assertEqual(res.addons_total, 50.0 + 40.0 + 50.0)
        self.assertEqual(res.grand_total, 340.0)
        self.assertEqual(res.deposit_amount, 85.0)

    def test_10_booking_price_invalid_deposit(self) -> None:
        with self.assertRaises(ValueError):
            calculate_booking_price(100.0, 60, 10, deposit_percent=120.0)

    # --- Scheduler tests ---
    def test_11_parse_dt_formats(self) -> None:
        dt1 = parse_dt("2026-06-01T10:00")
        dt2 = parse_dt("2026-06-01 10:00")
        self.assertEqual(dt1, dt2)

    def test_12_parse_dt_invalid(self) -> None:
        with self.assertRaises(BookingError):
            parse_dt("01-06-2026")

    def test_13_book_hall_success(self) -> None:
        b = book_hall(
            self.conn,
            "Loft-A",
            "Alice",
            "2026-06-01T10:00",
            "2026-06-01T12:00",
            guests=20,
            event_title="Workshop",
            addon_names=["Projector", "Coffee"],
            deposit_percent=30.0,
        )
        self.assertEqual(b["hall_name"], "Loft-A")
        self.assertEqual(b["base_total"], 200.0)
        self.assertEqual(b["addons_total"], 150.0)
        self.assertEqual(b["grand_total"], 350.0)
        self.assertEqual(b["deposit_amount"], 105.0)

    def test_14_capacity_exceeded(self) -> None:
        with self.assertRaises(BookingError):
            book_hall(self.conn, "Conf-B", "Bob", "2026-06-01T10:00", "2026-06-01T11:00", guests=16)

    def test_15_outside_operating_hours(self) -> None:
        with self.assertRaises(BookingError):
            book_hall(self.conn, "Loft-A", "Bob", "2026-06-01T08:00", "2026-06-01T10:00", guests=10)

    def test_16_end_before_start(self) -> None:
        with self.assertRaises(BookingError):
            book_hall(self.conn, "Loft-A", "Bob", "2026-06-01T12:00", "2026-06-01T11:00", guests=10)

    def test_17_turnaround_conflict_after(self) -> None:
        book_hall(self.conn, "Loft-A", "Alice", "2026-06-01T10:00", "2026-06-01T12:00", guests=10)
        # 12:15 violates 30-min turnaround
        with self.assertRaises(BookingError):
            book_hall(self.conn, "Loft-A", "Bob", "2026-06-01T12:15", "2026-06-01T14:00", guests=10)

    def test_18_turnaround_exact_boundary_allowed(self) -> None:
        book_hall(self.conn, "Loft-A", "Alice", "2026-06-01T10:00", "2026-06-01T12:00", guests=10)
        # 12:30 is exactly 30m after 12:00 -> allowed
        b2 = book_hall(self.conn, "Loft-A", "Bob", "2026-06-01T12:30", "2026-06-01T14:00", guests=10)
        self.assertEqual(b2["client_name"], "Bob")

    def test_19_cancelled_booking_frees_slot(self) -> None:
        b1 = book_hall(self.conn, "Loft-A", "Alice", "2026-06-01T10:00", "2026-06-01T12:00", guests=10)
        update_booking_status(self.conn, b1["id"], "cancelled")
        b2 = book_hall(self.conn, "Loft-A", "Bob", "2026-06-01T10:00", "2026-06-01T12:00", guests=10)
        self.assertEqual(b2["status"], "confirmed")

    def test_20_hold_and_confirm(self) -> None:
        b1 = book_hall(self.conn, "Loft-A", "Alice", "2026-06-01T10:00", "2026-06-01T12:00", guests=10, status="hold")
        self.assertEqual(b1["status"], "hold")
        b1_conf = update_booking_status(self.conn, b1["id"], "confirmed")
        self.assertEqual(b1_conf["status"], "confirmed")

    def test_21_unknown_addon_raises(self) -> None:
        with self.assertRaises(BookingError):
            book_hall(self.conn, "Loft-A", "Alice", "2026-06-01T10:00", "2026-06-01T11:00", guests=5, addon_names=["Laser"])

    def test_22_find_free_slots_empty_day(self) -> None:
        slots = find_free_slots(self.conn, "Loft-A", "2026-06-02", min_duration_minutes=60)
        self.assertEqual(slots, [("2026-06-02T09:00", "2026-06-02T22:00")])

    def test_23_find_free_slots_with_bookings(self) -> None:
        book_hall(self.conn, "Loft-A", "Alice", "2026-06-02T11:00", "2026-06-02T13:00", guests=10)
        slots = find_free_slots(self.conn, "Loft-A", "2026-06-02", min_duration_minutes=60)
        # 09:00..10:30 (90m) and 13:30..22:00
        self.assertEqual(
            slots,
            [
                ("2026-06-02T09:00", "2026-06-02T10:30"),
                ("2026-06-02T13:30", "2026-06-02T22:00"),
            ],
        )

    def test_24_list_bookings_filters(self) -> None:
        book_hall(self.conn, "Loft-A", "Alice", "2026-06-01T10:00", "2026-06-01T11:00", guests=10)
        book_hall(self.conn, "Conf-B", "Bob", "2026-06-02T10:00", "2026-06-02T11:00", guests=5)
        self.assertEqual(len(list_bookings(self.conn, hall_name="Loft-A")), 1)
        self.assertEqual(len(list_bookings(self.conn, date_str="2026-06-02")), 1)

    def test_25_export_json(self) -> None:
        book_hall(self.conn, "Loft-A", "Alice", "2026-06-01T10:00", "2026-06-01T11:00", guests=10)
        out = Path(self.tmp.name) / "out.json"
        cnt = export_bookings(self.conn, out, fmt="json")
        self.assertEqual(cnt, 1)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["client_name"], "Alice")

    def test_26_export_csv(self) -> None:
        book_hall(self.conn, "Loft-A", "Alice", "2026-06-01T10:00", "2026-06-01T11:00", guests=10)
        out = Path(self.tmp.name) / "out.csv"
        cnt = export_bookings(self.conn, out, fmt="csv")
        self.assertEqual(cnt, 1)
        with out.open("r", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hall_name"], "Loft-A")

    # --- CLI tests ---
    def test_27_cli_init_and_hall_add(self) -> None:
        cli_db = str(Path(self.tmp.name) / "cli.db")
        self.assertEqual(cli_main(["--db", cli_db, "init"]), 0)
        self.assertEqual(
            cli_main(["--db", cli_db, "hall-add", "--name", "Studio-1", "--capacity", "25", "--rate", "80"]),
            0,
        )

    def test_28_cli_book_and_slots(self) -> None:
        cli_db = str(Path(self.tmp.name) / "cli2.db")
        cli_main(["--db", cli_db, "init"])
        cli_main(["--db", cli_db, "hall-add", "--name", "Studio-1", "--capacity", "25", "--rate", "80"])
        rc = cli_main(
            [
                "--db",
                cli_db,
                "book",
                "--hall",
                "Studio-1",
                "--client",
                "Jane",
                "--guests",
                "12",
                "--start",
                "2026-07-01T10:00",
                "--end",
                "2026-07-01T12:00",
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(cli_main(["--db", cli_db, "slots", "--hall", "Studio-1", "--date", "2026-07-01"]), 0)

    def test_29_cli_conflict_returns_nonzero(self) -> None:
        rc = cli_main(
            [
                "--db",
                str(self.db_path),
                "book",
                "--hall",
                "Loft-A",
                "--client",
                "Over",
                "--guests",
                "999",
                "--start",
                "2026-07-01T10:00",
                "--end",
                "2026-07-01T12:00",
            ]
        )
        self.assertEqual(rc, 2)

    def test_30_cli_export(self) -> None:
        out = str(Path(self.tmp.name) / "cli_export.json")
        self.assertEqual(cli_main(["--db", str(self.db_path), "export", "--out", out, "--format", "json"]), 0)
        self.assertTrue(Path(out).exists())


if __name__ == "__main__":
    unittest.main()
