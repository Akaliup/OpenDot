from datetime import date
from decimal import Decimal

import pytest

from commerceops.engines.profit import (
    OrderLine,
    ProfitInputs,
    RefundLine,
    aggregate_profit,
    calculate_profit,
    calculate_profit_bridge,
    compare_profit_periods,
)
from commerceops.periods import previous_period


def _inputs(**overrides) -> ProfitInputs:
    base = dict(
        revenue=Decimal("0"),
        discounts=Decimal("0"),
        refunds=Decimal("0"),
        cogs=Decimal("0"),
        recovered_cogs=Decimal("0"),
        platform_fees=Decimal("0"),
        shipping_fees=Decimal("0"),
        ad_spend=Decimal("0"),
        other_fees=Decimal("0"),
    )
    base.update(overrides)
    return ProfitInputs(**base)


def test_profit_formula_and_margin():
    result = calculate_profit(
        _inputs(
            revenue=Decimal("1000"),
            discounts=Decimal("50"),
            refunds=Decimal("25"),
            cogs=Decimal("400"),
            recovered_cogs=Decimal("10"),
            platform_fees=Decimal("100"),
            shipping_fees=Decimal("40"),
            ad_spend=Decimal("80"),
            other_fees=Decimal("5"),
        )
    )
    assert result.net_sales == Decimal("925")
    assert result.net_cogs == Decimal("390")
    assert result.net_profit == Decimal("310")
    assert result.margin == Decimal("310") / Decimal("925")
    assert result.margin_status == "ok"


def test_zero_net_sales_margin_is_null_not_zero():
    result = calculate_profit(_inputs(ad_spend=Decimal("10"), platform_fees=Decimal("5")))
    assert result.net_sales == 0
    assert result.net_profit == Decimal("-15")
    assert result.margin is None
    assert result.margin_status == "zero_net_sales"


def test_negative_net_sales_keeps_a_defined_margin():
    result = calculate_profit(_inputs(revenue=Decimal("10"), refunds=Decimal("40"), cogs=Decimal("4")))
    assert result.net_sales == Decimal("-30")
    assert result.margin_status == "negative_net_sales"
    assert result.margin == result.net_profit / result.net_sales


def test_recovered_cogs_can_exceed_period_cogs():
    result = calculate_profit(_inputs(recovered_cogs=Decimal("4"), refunds=Decimal("20")))
    assert result.net_cogs == Decimal("-4")
    assert result.net_profit == Decimal("-16")


def test_ad_spend_is_not_an_order_field():
    assert "ad_spend" not in OrderLine.__dataclass_fields__
    inputs = aggregate_profit(
        [
            OrderLine(
                quantity=2,
                gross_revenue=Decimal("40"),
                discount=Decimal("0"),
                unit_cogs=Decimal("5"),
                platform_fee=Decimal("4"),
                shipping_fee=Decimal("2"),
                other_fee=Decimal("1"),
            )
        ],
        [RefundLine(quantity=1, amount=Decimal("10"), recovered_cogs=Decimal("5"))],
        Decimal("7"),
    )
    assert inputs.revenue == Decimal("40")
    assert inputs.cogs == Decimal("10")
    assert inputs.ad_spend == Decimal("7")
    assert calculate_profit(inputs).net_profit == Decimal("11")


def test_bridge_identity_with_awkward_decimals():
    current = calculate_profit(
        _inputs(
            revenue=Decimal("100.01"),
            discounts=Decimal("0.03"),
            refunds=Decimal("1.10"),
            cogs=Decimal("40.07"),
            recovered_cogs=Decimal("0.02"),
            platform_fees=Decimal("15.05"),
            shipping_fees=Decimal("3.33"),
            ad_spend=Decimal("12.50"),
            other_fees=Decimal("0.01"),
        )
    )
    previous = calculate_profit(
        _inputs(
            revenue=Decimal("80.09"),
            discounts=Decimal("1.25"),
            refunds=Decimal("0"),
            cogs=Decimal("20"),
            recovered_cogs=Decimal("0.50"),
            platform_fees=Decimal("8.08"),
            shipping_fees=Decimal("2.02"),
            ad_spend=Decimal("4.04"),
            other_fees=Decimal("0.07"),
        )
    )
    bridge = calculate_profit_bridge(current, previous)
    assert sum((item.contribution for item in bridge.components), Decimal(0)) == current.net_profit - previous.net_profit
    assert bridge.identity_ok is True
    assert bridge.delta_net_profit == current.net_profit - previous.net_profit


def test_two_empty_periods_bridge_to_zero():
    comparison = compare_profit_periods(_inputs(), _inputs())
    assert comparison.bridge.delta_net_profit == 0
    assert all(item.contribution == 0 for item in comparison.bridge.components)


def test_negative_money_is_rejected():
    with pytest.raises(ValueError):
        calculate_profit(_inputs(revenue=Decimal("-1")))


def test_previous_window_matches_the_seed_calendar():
    assert previous_period(date(2026, 3, 8), date(2026, 3, 14)) == (date(2026, 3, 1), date(2026, 3, 7))


def test_period_rejects_reversed_and_huge_windows():
    with pytest.raises(ValueError):
        previous_period(date(2026, 3, 14), date(2026, 3, 8))
    with pytest.raises(ValueError):
        previous_period(date(2024, 1, 1), date(2026, 1, 1))
