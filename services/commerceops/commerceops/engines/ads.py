"""Ads diagnostics, formula ads.v1.

ACOS = spend / attributed_sales          (null when attributed sales are 0)
ROAS = attributed_sales / spend          (null when spend is 0)
TACOS = spend / tacos_sales              (caller supplies the sales denominator)
CTR = clicks / impressions               (null when impressions are 0)
CPC = spend / clicks                     (null when clicks are 0)
CVR = attributed_orders / clicks         (null when clicks are 0)
CPA = spend / attributed_orders          (null when orders are 0)

A zero denominator is a status, not a zero ratio and not an exception.
Budget cuts are a deterministic ladder, not a model suggestion.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN

from commerceops.engines.money import require_int, require_non_negative

FORMULA_VERSION = "ads.v1"

FLAG_ORDER = (
    "spend_up_cvr_down",
    "acos_above_high",
    "acos_above_target",
    "acos_deteriorated",
    "clicks_exceed_impressions",
)


@dataclass(frozen=True)
class AdsPolicy:
    target_acos: Decimal = Decimal("0.35")
    high_acos: Decimal = Decimal("0.40")
    severe_acos: Decimal = Decimal("0.80")
    severe_budget_multiplier: Decimal = Decimal("0.50")
    high_budget_multiplier: Decimal = Decimal("0.70")
    cvr_decline_multiplier: Decimal = Decimal("0.80")
    min_current_spend: Decimal = Decimal("50")


@dataclass(frozen=True)
class AdTotals:
    impressions: int
    clicks: int
    spend: Decimal
    attributed_sales: Decimal
    attributed_orders: int


@dataclass(frozen=True)
class RatioValue:
    value: Decimal | None
    status: str


@dataclass(frozen=True)
class AdMetrics:
    formula_version: str
    impressions: int
    clicks: int
    spend: Decimal
    attributed_sales: Decimal
    attributed_orders: int
    acos: RatioValue
    roas: RatioValue
    tacos: RatioValue
    ctr: RatioValue
    cpc: RatioValue
    cvr: RatioValue
    cpa: RatioValue
    data_flags: tuple[str, ...]


@dataclass(frozen=True)
class BudgetSuggestion:
    formula_version: str
    current_daily_budget: Decimal
    suggested_daily_budget: Decimal
    multiplier: Decimal
    reason: str


def _ratio(numerator: Decimal, denominator: Decimal, zero_status: str) -> RatioValue:
    if denominator == 0:
        return RatioValue(None, zero_status)
    return RatioValue(numerator / denominator, "ok")


def calculate_ad_metrics(totals: AdTotals, tacos_sales: Decimal) -> AdMetrics:
    impressions = require_int("impressions", totals.impressions)
    clicks = require_int("clicks", totals.clicks)
    orders = require_int("attributed_orders", totals.attributed_orders)
    spend = require_non_negative("spend", totals.spend)
    attributed_sales = require_non_negative("attributed_sales", totals.attributed_sales)
    sales_base = require_non_negative("tacos_sales", tacos_sales)
    flags: list[str] = []
    if clicks > impressions:
        flags.append("clicks_exceed_impressions")
    return AdMetrics(
        formula_version=FORMULA_VERSION,
        impressions=impressions,
        clicks=clicks,
        spend=spend,
        attributed_sales=attributed_sales,
        attributed_orders=orders,
        acos=_ratio(spend, attributed_sales, "zero_attributed_sales"),
        roas=_ratio(attributed_sales, spend, "zero_spend"),
        tacos=_ratio(spend, sales_base, "zero_tacos_sales"),
        ctr=_ratio(Decimal(clicks), Decimal(impressions), "zero_impressions"),
        cpc=_ratio(spend, Decimal(clicks), "zero_clicks"),
        cvr=_ratio(Decimal(orders), Decimal(clicks), "zero_clicks"),
        cpa=_ratio(spend, Decimal(orders), "zero_orders"),
        data_flags=tuple(flags),
    )


def diagnose_flags(
    current: AdMetrics,
    previous: AdMetrics | None,
    policy: AdsPolicy | None = None,
) -> list[str]:
    rules = policy or AdsPolicy()
    flags: list[str] = []
    if (
        previous is not None
        and current.spend >= rules.min_current_spend
        and current.spend > previous.spend
        and current.cvr.value is not None
        and previous.cvr.value is not None
        and current.cvr.value < previous.cvr.value
    ):
        flags.append("spend_up_cvr_down")
    if current.acos.value is not None and current.acos.value >= rules.high_acos:
        flags.append("acos_above_high")
    if current.acos.value is not None and current.acos.value >= rules.target_acos:
        flags.append("acos_above_target")
    if (
        previous is not None
        and current.acos.value is not None
        and previous.acos.value is not None
        and current.acos.value > previous.acos.value
    ):
        flags.append("acos_deteriorated")
    if "clicks_exceed_impressions" in current.data_flags:
        flags.append("clicks_exceed_impressions")
    order = {name: index for index, name in enumerate(FLAG_ORDER)}
    return sorted(flags, key=lambda name: order[name])


def suggest_budget(
    daily_budget: Decimal,
    metrics: AdMetrics,
    flags: list[str] | tuple[str, ...],
    policy: AdsPolicy | None = None,
) -> BudgetSuggestion:
    rules = policy or AdsPolicy()
    budget = require_non_negative("daily_budget", daily_budget)
    flagset = set(flags)
    acos = metrics.acos.value
    if acos is not None and acos >= rules.severe_acos:
        multiplier = rules.severe_budget_multiplier
        reason = "severe_acos"
    elif acos is not None and acos >= rules.high_acos:
        multiplier = rules.high_budget_multiplier
        reason = "high_acos"
    elif "spend_up_cvr_down" in flagset:
        multiplier = rules.cvr_decline_multiplier
        reason = "cvr_decline"
    else:
        multiplier = Decimal("1")
        reason = "no_adjustment"
    suggested = (budget * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    return BudgetSuggestion(
        formula_version=FORMULA_VERSION,
        current_daily_budget=budget,
        suggested_daily_budget=suggested,
        multiplier=multiplier,
        reason=reason,
    )
