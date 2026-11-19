# Event Venue & Hall Booking Schedule CLI (Lite)

Zero-dependency Python 3.9+ SQLite CLI for lofts, event spaces, and conference halls: hourly booking with cleaning turnaround buffers, capacity validation, add-on & deposit pricing, free-slot search, and JSON/CSV export.

## Features (Lite)

- **Pure Python 3.9+ stdlib** (`sqlite3`, `argparse`, `csv`, `json`, `datetime`).
- **Turnaround Buffer**: Automatically enforces `turnaround_minutes` between bookings for cleaning/reset.
- **Capacity & Hours Validation**: Blocks over-capacity events and out-of-hours bookings.
- **Add-on & Deposit Calculator**: Supports `flat`, `per_hour`, and `per_guest` add-ons plus configurable deposit percentage.
- **Free Slot Finder**: Lists available windows on any date considering existing holds/confirmations and turnaround buffers.
- **Export**: Dump schedules to `JSON` or `CSV`.

## Quick Start

```bash
# Initialize database
python -m venue_cli.cli --db venue.db init

# Add a hall (capacity 50, $120/hr, 30m turnaround, 09:00-23:00)
python -m venue_cli.cli --db venue.db hall-add --name "Loft-A" --capacity 50 --rate 120 --turnaround 30

# Add billable add-ons
python -m venue_cli.cli --db venue.db addon-add --name "Projector" --type flat --price 40
python -m venue_cli.cli --db venue.db addon-add --name "Catering" --type per_guest --price 15

# Book a slot
python -m venue_cli.cli --db venue.db book --hall "Loft-A" --client "Acme Corp" --title "Tech Meetup" \
  --guests 30 --start 2026-05-10T14:00 --end 2026-05-10T17:00 --addons "Projector,Catering" --deposit 30

# Find free windows on 2026-05-10
python -m venue_cli.cli --db venue.db slots --hall "Loft-A" --date 2026-05-10 --min-minutes 60

# Export schedule
python -m venue_cli.cli --db venue.db export --out schedule.csv --format csv
```

## Lite vs Pro

| Feature | Lite (Open-Source CLI) | Pro (Full Automation) |
| --- | --- | --- |
| Hourly booking + turnaround buffer | Yes | Yes |
| Capacity & operating hours check | Yes | Yes |
| Add-ons (`flat` / `per_hour` / `per_guest`) & deposit | Yes | Yes |
| Free-slot search & JSON/CSV export | Yes | Yes |
| **Telegram Booking Bot** | - | **Yes** |
| **Web Hall Timeline & Calendar UI** | - | **Yes** |
| **Auto-expiring Holds & Revenue Analytics** | - | **Yes** |

Get **Pro** or custom venue automation: https://funpay.com/users/20096179/

---

## Русский (RU)

Лёгкий CLI-инструмент на чистом Python 3.9+ и SQLite для лофтов и конференц-залов: почасовое бронирование с учётом буфера уборки `turnaround_minutes`, проверка вместимости и часов работы зала, калькулятор допов (`flat` / `per_hour` / `per_guest`) и предоплаты, поиск свободных окон на дату, экспорт в JSON/CSV.

### Возможности Pro-версии
- **Telegram-бот бронирования** для клиентов и менеджеров
- **Web-таймлайн залов** с визуальной сеткой занятости
- **Автоистечение холдов** и аналитика выручки/загрузки

Заказать Pro-версию или доработку под ваш зал: https://funpay.com/users/20096179/
