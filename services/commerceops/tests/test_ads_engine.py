from decimal import Decimal

import pytest

from commerceops.engines.ads import AdTotals, AdsPolicy, calculate_ad_metrics, diagnose_flags, suggest_budget


def _totals(**overrides) -> AdTotals:
    base = dict(impressions=1000, clicks=100, spend=Decimal("50"), attributed_sales=Decimal("200"), attributed_orders=10)
    base.update(overrides)
    return AdTotals(**base)


def test_ratios_are_exact_when_they_divide():
    metrics = calculate_ad_metrics(_totals(), Decimal("400"))
    assert metrics.acos.value == Decimal("0.25")
    assert metrics.roas.value == Decimal("4")
    assert metrics.tacos.value == Decimal("0.125")
    assert metrics.ctr.value == Decimal("0.1")
    assert metrics.cpc.value == Decimal("0.5")
    assert metrics.cvr.value == Decimal("0.1")
    assert metrics.cpa.value == Decimal("5")
    assert metrics.acos.status == "ok"


def test_zero_denominators_are_statuses_not_zeros():
    metrics = calculate_ad_metrics(
        AdTotals(0, 0, Decimal("0"), Decimal("0"), 0),
        Decimal("0"),
    )
    assert metrics.acos.value is None and metrics.acos.status == "zero_attributed_sales"
    assert metrics.roas.value is None and metrics.roas.status == "zero_spend"
    assert metrics.tacos.value is None and metrics.tacos.status == "zero_tacos_sales"
    assert metrics.ctr.value is None and metrics.ctr.status == "zero_impressions"
    assert metrics.cpc.value is None and metrics.cpc.status == "zero_clicks"
    assert metrics.cvr.value is None and metrics.cvr.status == "zero_clicks"
    assert metrics.cpa.value is None and metrics.cpa.status == "zero_orders"


def test_zero_spend_with_sales_has_zero_acos_and_null_roas():
    metrics = calculate_ad_metrics(
        AdTotals(10, 2, Decimal("0"), Decimal("30"), 1),
        Decimal("30"),
    )
    assert metrics.acos.value == 0 and metrics.acos.status == "ok"
    assert metrics.roas.value is None and metrics.roas.status == "zero_spend"
    assert metrics.cvr.value == Decimal("0.5")


def test_clicks_without_orders_have_zero_cvr_and_null_cpa():
    metrics = calculate_ad_metrics(_totals(attributed_orders=0, attributed_sales=Decimal("0")), Decimal("10"))
    assert metrics.cvr.value == 0 and metrics.cvr.status == "ok"
    assert metrics.cpa.value is None and metrics.cpa.status == "zero_orders"
    assert metrics.acos.status == "zero_attributed_sales"


def test_spend_up_cvr_down_and_budget_ladder():
    previous = calculate_ad_metrics(_totals(spend=Decimal("40"), attributed_orders=10), Decimal("100"))
    current = calculate_ad_metrics(_totals(spend=Decimal("80"), attributed_orders=4, attributed_sales=Decimal("90")), Decimal("100"))
    flags = diagnose_flags(current, previous)
    assert "spend_up_cvr_down" in flags
    assert "acos_deteriorated" in flags
    suggestion = suggest_budget(Decimal("40"), current, flags)
    assert suggestion.reason == "severe_acos"
    assert suggestion.suggested_daily_budget == Decimal("20.00")


def test_high_acos_uses_seventy_percent_before_the_cvr_rule():
    current = calculate_ad_metrics(_totals(spend=Decimal("50"), attributed_sales=Decimal("100"), attributed_orders=5), Decimal("100"))
    previous = calculate_ad_metrics(_totals(spend=Decimal("20"), attributed_sales=Decimal("100"), attributed_orders=10), Decimal("100"))
    flags = diagnose_flags(current, previous)
    suggestion = suggest_budget(Decimal("45"), current, flags)
    assert current.acos.value == Decimal("0.5")
    assert suggestion.reason == "high_acos"
    assert suggestion.multiplier == Decimal("0.70")
    assert suggestion.suggested_daily_budget == Decimal("31.50")


def test_cvr_decline_without_high_acos_uses_eighty_percent():
    previous = calculate_ad_metrics(_totals(spend=Decimal("40"), attributed_sales=Decimal("200"), attributed_orders=20), Decimal("200"))
    current = calculate_ad_metrics(_totals(spend=Decimal("60"), attributed_sales=Decimal("200"), attributed_orders=10), Decimal("200"))
    flags = diagnose_flags(current, previous)
    assert "spend_up_cvr_down" in flags
    assert "acos_above_high" not in flags
    suggestion = suggest_budget(Decimal("10"), current, flags)
    assert suggestion.reason == "cvr_decline"
    assert suggestion.suggested_daily_budget == Decimal("8.00")


def test_small_spend_increase_does_not_flag_and_flat_campaign_is_not_cut():
    previous = calculate_ad_metrics(_totals(spend=Decimal("10"), attributed_orders=10), Decimal("100"))
    current = calculate_ad_metrics(_totals(spend=Decimal("20"), attributed_orders=5, attributed_sales=Decimal("200")), Decimal("100"))
    assert "spend_up_cvr_down" not in diagnose_flags(current, previous)
    flat_previous = calculate_ad_metrics(_totals(), Decimal("400"))
    flat_current = calculate_ad_metrics(_totals(), Decimal("400"))
    suggestion = suggest_budget(Decimal("15"), flat_current, diagnose_flags(flat_current, flat_previous))
    assert suggestion.reason == "no_adjustment"
    assert suggestion.suggested_daily_budget == Decimal("15.00")


def test_custom_min_spend_policy():
    previous = calculate_ad_metrics(_totals(spend=Decimal("10"), attributed_orders=10), Decimal("100"))
    current = calculate_ad_metrics(_totals(spend=Decimal("12"), attributed_orders=5), Decimal("100"))
    flags = diagnose_flags(current, previous, AdsPolicy(min_current_spend=Decimal("12")))
    assert "spend_up_cvr_down" in flags


def test_clicks_above_impressions_are_flagged_and_negative_inputs_fail():
    metrics = calculate_ad_metrics(_totals(impressions=1, clicks=2), Decimal("10"))
    assert "clicks_exceed_impressions" in diagnose_flags(metrics, None)
    with pytest.raises(ValueError):
        calculate_ad_metrics(_totals(spend=Decimal("-1")), Decimal("1"))
