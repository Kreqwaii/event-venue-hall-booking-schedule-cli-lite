"""Pricing calculator for hall rentals, add-ons, and deposits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple


VALID_PRICING_TYPES = ("flat", "per_hour", "per_guest")


@dataclass(frozen=True)
class AddonSpec:
    addon_id: int
    name: str
    pricing_type: str
    price: float
    quantity: int = 1


@dataclass(frozen=True)
class PriceBreakdown:
    hours: float
    base_total: float
    addons_total: float
    grand_total: float
    deposit_percent: float
    deposit_amount: float
    addon_lines: List[Tuple[int, str, int, float]]


def calculate_addon_line(
    pricing_type: str,
    price: float,
    hours: float,
    guests: int,
    quantity: int = 1,
) -> float:
    if pricing_type not in VALID_PRICING_TYPES:
        raise ValueError(f"Unsupported pricing_type: {pricing_type}")
    if price < 0 or quantity <= 0 or hours <= 0 or guests <= 0:
        raise ValueError("Invalid numeric values for addon calculation")

    if pricing_type == "flat":
        total = price * quantity
    elif pricing_type == "per_hour":
        total = price * hours * quantity
    else:  # per_guest
        total = price * guests * quantity
    return round(total, 2)


def calculate_booking_price(
    hourly_rate: float,
    duration_minutes: int,
    guests: int,
    addons: Iterable[AddonSpec] = (),
    deposit_percent: float = 30.0,
) -> PriceBreakdown:
    if hourly_rate < 0:
        raise ValueError("hourly_rate must be non-negative")
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")
    if guests <= 0:
        raise ValueError("guests must be positive")
    if not (0.0 <= deposit_percent <= 100.0):
        raise ValueError("deposit_percent must be between 0 and 100")

    hours = round(duration_minutes / 60.0, 4)
    base_total = round(hourly_rate * (duration_minutes / 60.0), 2)

    addon_lines: List[Tuple[int, str, int, float]] = []
    addons_total = 0.0
    for spec in addons:
        line = calculate_addon_line(
            pricing_type=spec.pricing_type,
            price=spec.price,
            hours=duration_minutes / 60.0,
            guests=guests,
            quantity=spec.quantity,
        )
        addon_lines.append((spec.addon_id, spec.name, spec.quantity, line))
        addons_total += line

    addons_total = round(addons_total, 2)
    grand_total = round(base_total + addons_total, 2)
    deposit_amount = round(grand_total * (deposit_percent / 100.0), 2)

    return PriceBreakdown(
        hours=hours,
        base_total=base_total,
        addons_total=addons_total,
        grand_total=grand_total,
        deposit_percent=deposit_percent,
        deposit_amount=deposit_amount,
        addon_lines=addon_lines,
    )
