"""Inventory cover and replenishment, formula inventory.v1.

days_of_cover = available / average_daily_sales
    when average_daily_sales is 0 the result is status undefined_no_velocity.
    It is never 0 and never infinity.

available = on_hand - reserved, floored at 0. reserved > on_hand is oversold.

reorder_point = average_daily_sales * lead_time_days + safety_stock
    null when velocity is 0, because a safety-stock-only number would pretend
    we observed demand.

unconstrained need =
    average_daily_sales * (lead_time_days + target_cover_days) + safety_stock
    - available - inbound_qty
    floored at 0.

Suggested units are the ceiling of that need. MOQ and order multiple belong
to the supplier quote, not to this signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from commerceops.engines.money import require_int

FORMULA_VERSION = "inventory.v1"


@dataclass(frozen=True)
class CoverResult:
    formula_version: str
    on_hand: int
    reserved: int
    available: int
    oversold: bool
    units_sold: int
    lookback_days: int
    average_daily_sales: Decimal
    days_of_cover: Decimal | None
    status: str
    at_risk: bool
    horizon_days: int
    stockout_date: date | None


@dataclass(frozen=True)
class ReplenishmentResult:
    formula_version: str
    reorder_point: Decimal | None
    suggested_order_qty_exact: Decimal | None
    suggested_order_qty: int | None
    status: str
    inbound_qty: int
    inbound_late: bool


def average_daily_sales(units_sold: int, lookback_days: int) -> Decimal:
    require_int("units_sold", units_sold)
    require_int("lookback_days", lookback_days, minimum=1)
    return Decimal(units_sold) / Decimal(lookback_days)


def available_units(on_hand: int, reserved: int) -> tuple[int, bool]:
    require_int("on_hand", on_hand)
    require_int("reserved", reserved)
    if reserved > on_hand:
        return 0, True
    return on_hand - reserved, False


def analyze_cover(
    *,
    on_hand: int,
    reserved: int,
    units_sold: int,
    lookback_days: int,
    as_of: date,
    horizon_days: int,
) -> CoverResult:
    require_int("horizon_days", horizon_days)
    available, oversold = available_units(on_hand, reserved)
    average = average_daily_sales(units_sold, lookback_days)
    if average == 0:
        return CoverResult(
            formula_version=FORMULA_VERSION,
            on_hand=on_hand,
            reserved=reserved,
            available=available,
            oversold=oversold,
            units_sold=units_sold,
            lookback_days=lookback_days,
            average_daily_sales=average,
            days_of_cover=None,
            status="undefined_no_velocity",
            at_risk=False,
            horizon_days=horizon_days,
            stockout_date=None,
        )
    days = Decimal(available) / average
    whole_days = int(days.to_integral_value(rounding=ROUND_FLOOR))
    return CoverResult(
        formula_version=FORMULA_VERSION,
        on_hand=on_hand,
        reserved=reserved,
        available=available,
        oversold=oversold,
        units_sold=units_sold,
        lookback_days=lookback_days,
        average_daily_sales=average,
        days_of_cover=days,
        status="ok",
        at_risk=days <= Decimal(horizon_days),
        horizon_days=horizon_days,
        stockout_date=as_of + timedelta(days=whole_days),
    )


def unconstrained_need(
    average_daily_sales_value: Decimal,
    lead_time_days: int,
    target_cover_days: int,
    safety_stock: int,
    available: int,
    inbound_qty: int,
) -> Decimal:
    if average_daily_sales_value <= 0:
        raise ValueError("velocity required")
    require_int("lead_time_days", lead_time_days, minimum=1)
    require_int("target_cover_days", target_cover_days)
    require_int("safety_stock", safety_stock)
    require_int("available", available)
    require_int("inbound_qty", inbound_qty)
    gross = average_daily_sales_value * Decimal(lead_time_days + target_cover_days) + Decimal(safety_stock)
    net = Decimal(available + inbound_qty)
    raw = gross - net
    return raw if raw > 0 else Decimal(0)


def plan_replenishment(
    *,
    average_daily_sales_value: Decimal,
    planning_lead_time_days: int,
    target_cover_days: int,
    safety_stock: int,
    available: int,
    inbound_qty: int,
    inbound_eta: date | None,
    stockout_date: date | None,
    velocity_status: str,
) -> ReplenishmentResult:
    require_int("planning_lead_time_days", planning_lead_time_days, minimum=1)
    require_int("inbound_qty", inbound_qty)
    inbound_late = bool(
        inbound_qty > 0
        and inbound_eta is not None
        and stockout_date is not None
        and inbound_eta > stockout_date
    )
    if velocity_status != "ok" or average_daily_sales_value == 0:
        return ReplenishmentResult(
            formula_version=FORMULA_VERSION,
            reorder_point=None,
            suggested_order_qty_exact=None,
            suggested_order_qty=None,
            status="insufficient_velocity",
            inbound_qty=inbound_qty,
            inbound_late=inbound_late,
        )
    reorder = average_daily_sales_value * Decimal(planning_lead_time_days) + Decimal(safety_stock)
    exact = unconstrained_need(
        average_daily_sales_value,
        planning_lead_time_days,
        target_cover_days,
        safety_stock,
        available,
        inbound_qty,
    )
    suggested = int(exact.to_integral_value(rounding=ROUND_CEILING))
    return ReplenishmentResult(
        formula_version=FORMULA_VERSION,
        reorder_point=reorder,
        suggested_order_qty_exact=exact,
        suggested_order_qty=suggested,
        status="ok",
        inbound_qty=inbound_qty,
        inbound_late=inbound_late,
    )
