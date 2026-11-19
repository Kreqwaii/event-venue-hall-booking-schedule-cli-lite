"""Command-line interface for Event Venue & Hall Booking Schedule CLI."""

from __future__ import annotations

import argparse
from contextlib import closing
import json
import sys
from typing import List, Optional

from .scheduler import (
    BookingError,
    book_hall,
    export_bookings,
    find_free_slots,
    list_bookings,
    update_booking_status,
)
from .storage import (
    create_addon,
    create_hall,
    get_connection,
    init_db,
    list_addons,
    list_halls,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="venue-cli",
        description="SQLite CLI for event venue & conference hall hourly booking.",
    )
    parser.add_argument(
        "--db",
        default="venue.db",
        help="Path to SQLite database file (default: venue.db)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    sub.add_parser("init", help="Initialize SQLite database schema")

    # hall-add
    p_hall_add = sub.add_parser("hall-add", help="Register a new hall or loft")
    p_hall_add.add_argument("--name", required=True)
    p_hall_add.add_argument("--capacity", type=int, required=True)
    p_hall_add.add_argument("--rate", type=float, required=True, help="Hourly rate")
    p_hall_add.add_argument("--turnaround", type=int, default=30, help="Cleaning buffer in minutes")
    p_hall_add.add_argument("--open-hour", type=int, default=9)
    p_hall_add.add_argument("--close-hour", type=int, default=23)

    # hall-list
    sub.add_parser("hall-list", help="List all halls")

    # addon-add
    p_addon_add = sub.add_parser("addon-add", help="Register a billable add-on")
    p_addon_add.add_argument("--name", required=True)
    p_addon_add.add_argument("--type", required=True, choices=["flat", "per_hour", "per_guest"])
    p_addon_add.add_argument("--price", type=float, required=True)

    # addon-list
    sub.add_parser("addon-list", help="List all add-ons")

    # book
    p_book = sub.add_parser("book", help="Create a hall booking")
    p_book.add_argument("--hall", required=True)
    p_book.add_argument("--client", required=True)
    p_book.add_argument("--title", default="")
    p_book.add_argument("--guests", type=int, required=True)
    p_book.add_argument("--start", required=True, help="YYYY-MM-DDTHH:MM")
    p_book.add_argument("--end", required=True, help="YYYY-MM-DDTHH:MM")
    p_book.add_argument("--addons", default="", help="Comma-separated add-on names")
    p_book.add_argument("--deposit", type=float, default=30.0, help="Deposit percent (0-100)")
    p_book.add_argument("--status", default="confirmed", choices=["hold", "confirmed"])

    # cancel / confirm
    p_cancel = sub.add_parser("cancel", help="Cancel a booking by ID")
    p_cancel.add_argument("--id", type=int, required=True)

    p_confirm = sub.add_parser("confirm", help="Confirm a held booking by ID")
    p_confirm.add_argument("--id", type=int, required=True)

    # slots
    p_slots = sub.add_parser("slots", help="Find free booking windows for a hall on a date")
    p_slots.add_argument("--hall", required=True)
    p_slots.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_slots.add_argument("--min-minutes", type=int, default=60)

    # bookings
    p_bookings = sub.add_parser("bookings", help="List bookings")
    p_bookings.add_argument("--hall", default=None)
    p_bookings.add_argument("--date", default=None)
    p_bookings.add_argument("--status", default=None)

    # export
    p_export = sub.add_parser("export", help="Export bookings to JSON or CSV")
    p_export.add_argument("--out", required=True)
    p_export.add_argument("--format", default="json", choices=["json", "csv"])
    p_export.add_argument("--hall", default=None)
    p_export.add_argument("--date", default=None)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        init_db(args.db)
        print(json.dumps({"status": "ok", "db": args.db}))
        return 0

    init_db(args.db)
    with get_connection(args.db) as conn:
        try:
            if args.command == "hall-add":
                hall_id = create_hall(
                    conn,
                    name=args.name,
                    capacity=args.capacity,
                    hourly_rate=args.rate,
                    turnaround_minutes=args.turnaround,
                    open_hour=args.open_hour,
                    close_hour=args.close_hour,
                )
                print(json.dumps({"id": hall_id, "name": args.name}))
            elif args.command == "hall-list":
                print(json.dumps(list_halls(conn), indent=2))
            elif args.command == "addon-add":
                addon_id = create_addon(conn, args.name, args.type, args.price)
                print(json.dumps({"id": addon_id, "name": args.name}))
            elif args.command == "addon-list":
                print(json.dumps(list_addons(conn), indent=2))
            elif args.command == "book":
                addon_names = [x.strip() for x in args.addons.split(",") if x.strip()]
                booking = book_hall(
                    conn,
                    hall_name=args.hall,
                    client_name=args.client,
                    start_ts=args.start,
                    end_ts=args.end,
                    guests=args.guests,
                    event_title=args.title,
                    addon_names=addon_names,
                    deposit_percent=args.deposit,
                    status=args.status,
                )
                print(json.dumps(booking, indent=2))
            elif args.command == "cancel":
                print(json.dumps(update_booking_status(conn, args.id, "cancelled"), indent=2))
            elif args.command == "confirm":
                print(json.dumps(update_booking_status(conn, args.id, "confirmed"), indent=2))
            elif args.command == "slots":
                slots = find_free_slots(conn, args.hall, args.date, args.min_minutes)
                print(json.dumps([{"start": s, "end": e} for s, e in slots], indent=2))
            elif args.command == "bookings":
                print(
                    json.dumps(
                        list_bookings(conn, hall_name=args.hall, date_str=args.date, status=args.status),
                        indent=2,
                    )
                )
            elif args.command == "export":
                count = export_bookings(
                    conn, args.out, fmt=args.format, hall_name=args.hall, date_str=args.date
                )
                print(json.dumps({"exported": count, "path": args.out, "format": args.format}))
        except (BookingError, ValueError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
