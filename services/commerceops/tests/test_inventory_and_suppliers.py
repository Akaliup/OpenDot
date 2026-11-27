from datetime import date
from decimal import Decimal

import pytest

from commerceops.engines.inventory import analyze_cover, plan_replenishment, unconstrained_need
from commerceops.engines.suppliers import (
    WEIGHTS,
    SupplierQuoteInput,
    apply_moq_and_multiple,
    landed_unit_cost,
    rank_suppliers,
    select_tier,
)


def _quote(code: str, **overrides) -> SupplierQuoteInput:
    base = dict(
        supplier_code=code,
        tier_min_qty=1,
        unit_price=Decimal("10"),
        duty_rate=Decimal("0"),
        freight_per_unit=Decimal("0"),
        moq=1,
        lead_time_days=10,
        order_multiple=1,
        on_time_rate=Decimal("1"),
        on_time_sample_size=10,
        currency="USD",
    )
    base.update(overrides)
    return SupplierQuoteInput(**base)


def test_days_of_cover_and_boundary():
    at_horizon = analyze_cover(
        on_hand=14, reserved=0, units_sold=14, lookback_days=14, as_of=date(2026, 3, 15), horizon_days=14
    )
    assert at_horizon.days_of_cover == Decimal("14")
    assert at_horizon.at_risk is True
    assert at_horizon.stockout_date == date(2026, 3, 29)
    above = analyze_cover(
        on_hand=15, reserved=0, units_sold=14, lookback_days=14, as_of=date(2026, 3, 15), horizon_days=14
    )
    assert above.at_risk is False


def test_zero_velocity_is_undefined_not_zero_or_infinite():
    with_stock = analyze_cover(
        on_hand=10, reserved=0, units_sold=0, lookback_days=14, as_of=date(2026, 3, 15), horizon_days=14
    )
    empty = analyze_cover(
        on_hand=0, reserved=0, units_sold=0, lookback_days=14, as_of=date(2026, 3, 15), horizon_days=14
    )
    assert with_stock.days_of_cover is None
    assert with_stock.status == "undefined_no_velocity"
    assert with_stock.at_risk is False
    assert empty.days_of_cover is None
    assert empty.status == "undefined_no_velocity"
    plan = plan_replenishment(
        average_daily_sales_value=Decimal(0),
        planning_lead_time_days=12,
        target_cover_days=30,
        safety_stock=15,
        available=10,
        inbound_qty=0,
        inbound_eta=None,
        stockout_date=None,
        velocity_status="undefined_no_velocity",
    )
    assert plan.reorder_point is None
    assert plan.suggested_order_qty is None
    assert plan.status == "insufficient_velocity"


def test_zero_available_with_velocity_stocks_out_today():
    cover = analyze_cover(
        on_hand=3, reserved=5, units_sold=28, lookback_days=14, as_of=date(2026, 3, 15), horizon_days=14
    )
    assert cover.oversold is True
    assert cover.available == 0
    assert cover.days_of_cover == 0
    assert cover.at_risk is True
    assert cover.stockout_date == date(2026, 3, 15)


def test_reorder_point_inbound_and_ceiling():
    cover = analyze_cover(
        on_hand=20, reserved=2, units_sold=70, lookback_days=14, as_of=date(2026, 3, 15), horizon_days=14
    )
    assert cover.average_daily_sales == Decimal("5")
    assert cover.days_of_cover == Decimal("3.6")
    plan = plan_replenishment(
        average_daily_sales_value=cover.average_daily_sales,
        planning_lead_time_days=12,
        target_cover_days=30,
        safety_stock=15,
        available=cover.available,
        inbound_qty=10,
        inbound_eta=date(2026, 3, 30),
        stockout_date=cover.stockout_date,
        velocity_status=cover.status,
    )
    assert plan.reorder_point == Decimal("75")
    assert plan.suggested_order_qty_exact == Decimal("207")
    assert plan.suggested_order_qty == 207
    assert plan.effective_inbound_qty == 0
    assert plan.unknown_eta_inbound_qty == 0
    assert plan.inbound_late is True
    assert unconstrained_need(Decimal("2.5"), 4, 2, 1, 3, 0) == Decimal("13")


def test_inbound_without_eta_does_not_offset_demand():
    plan = plan_replenishment(
        average_daily_sales_value=Decimal("1"),
        planning_lead_time_days=5,
        target_cover_days=5,
        safety_stock=0,
        available=2,
        inbound_qty=3,
        inbound_eta=None,
        stockout_date=date(2026, 3, 17),
        velocity_status="ok",
    )
    assert plan.inbound_late is False
    assert plan.unknown_eta_inbound_qty == 3
    assert plan.effective_inbound_qty == 0
    assert plan.suggested_order_qty_exact == Decimal("8")


def test_landed_cost_tiers_and_moq():
    assert landed_unit_cost(Decimal("2.40"), Decimal("0.05"), Decimal("0.30")) == Decimal("2.82")
    assert landed_unit_cost(Decimal("1.90"), Decimal("0.08"), Decimal("0.45")) == Decimal("2.502")
    assert landed_unit_cost(Decimal("2.20"), Decimal("0.04"), Decimal("0.35")) == Decimal("2.638")
    cheap = _quote("SZR", tier_min_qty=1, unit_price=Decimal("2.40"), freight_per_unit=Decimal("0.30"))
    volume = _quote("SZR", tier_min_qty=500, unit_price=Decimal("2.10"), freight_per_unit=Decimal("0.20"))
    assert select_tier([cheap, volume], 197).tier_min_qty == 1
    assert select_tier([cheap, volume], 500).tier_min_qty == 500
    assert apply_moq_and_multiple(Decimal("197"), 100, 10) == 200
    assert apply_moq_and_multiple(Decimal("40"), 100, 10) == 100
    assert apply_moq_and_multiple(Decimal("0"), 100, 10) == 0


def test_rank_score_is_the_weighted_sum_and_tie_breaks_by_code():
    assert sum(WEIGHTS.values(), Decimal(0)) == 1
    demand = dict(
        average_daily_sales=Decimal("1"),
        available=0,
        inbound_qty=0,
        safety_stock=0,
        target_cover_days=0,
        days_of_cover=Decimal("30"),
        velocity_ok=True,
    )
    ranked = rank_suppliers([_quote("B", unit_price=Decimal("20")), _quote("A", unit_price=Decimal("10"))], **demand)
    assert [row.supplier_code for row in ranked.rankings] == ["A", "B"]
    assert ranked.rankings[0].score == Decimal("1")
    assert ranked.rankings[1].score == Decimal("0.8")
    for row in ranked.rankings:
        assert row.score == sum(WEIGHTS[key] * row.components[key] for key in WEIGHTS)
    tied = rank_suppliers([_quote("B"), _quote("A")], **demand)
    assert [row.supplier_code for row in tied.rankings] == ["A", "B"]


def test_zero_landed_cost_insufficient_sample_and_no_velocity():
    demand = dict(
        average_daily_sales=Decimal("1"),
        available=0,
        inbound_qty=0,
        safety_stock=0,
        target_cover_days=0,
        days_of_cover=Decimal("20"),
        velocity_ok=True,
    )
    free = _quote("FREE", unit_price=Decimal("0"), lead_time_days=5)
    paid = _quote("PAID", unit_price=Decimal("5"), lead_time_days=5, on_time_sample_size=7, on_time_rate=Decimal("0.99"))
    ranked = rank_suppliers([paid, free], **demand)
    by_code = {row.supplier_code: row for row in ranked.rankings}
    assert by_code["FREE"].components["landed_cost"] == 1
    assert by_code["PAID"].components["landed_cost"] == 0
    assert by_code["PAID"].components["on_time_delivery"] == 0
    assert by_code["PAID"].on_time_status == "insufficient_sample"
    assert by_code["FREE"].lead_time_risk == "comfortable"
    unranked = rank_suppliers([free, paid], **{**demand, "velocity_ok": False, "average_daily_sales": Decimal(0), "days_of_cover": None})
    assert unranked.status == "insufficient_velocity"
    assert unranked.ranked is False
    assert all(row.adjusted_order_qty is None for row in unranked.rankings)
    assert rank_suppliers([], **demand).status == "no_quotes"


def test_late_lead_and_inconsistent_terms():
    demand = dict(
        average_daily_sales=Decimal("2"),
        available=4,
        inbound_qty=0,
        safety_stock=0,
        target_cover_days=0,
        days_of_cover=Decimal("2"),
        velocity_ok=True,
    )
    ranked = rank_suppliers([_quote("SLOW", lead_time_days=10, moq=1)], **demand)
    assert ranked.rankings[0].lead_time_risk == "arrives_after_stockout"
    with pytest.raises(ValueError):
        rank_suppliers(
            [_quote("X", tier_min_qty=1, moq=1), _quote("X", tier_min_qty=10, moq=5)],
            **demand,
        )


def test_cover_rejects_bad_windows():
    with pytest.raises(ValueError):
        analyze_cover(on_hand=1, reserved=0, units_sold=1, lookback_days=0, as_of=date(2026, 3, 15), horizon_days=14)
    with pytest.raises(ValueError):
        analyze_cover(on_hand=-1, reserved=0, units_sold=1, lookback_days=7, as_of=date(2026, 3, 15), horizon_days=14)
