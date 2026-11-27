"""Price simulation, formula price_sim.v1.

Given a current list price and a target list price, scale the observed
window's net sales and platform fees by the price ratio. COGS, shipping,
and other fees stay per unit. Ad spend stays at the observed window total
and does not scale with volume.

Volume moves by a published elasticity, not a fitted model:

    volume_multiplier = max(0, 1 + elasticity * (target_price - current_price) / current_price)

Scenarios are conservative -1.6, base -1.0, and optimistic -0.4.
Optimistic means demand is less elastic: a price increase loses less volume,
and a price cut gains less volume.

Unit margin and break-even ACOS are properties of the target price.
Break-even ACOS is contribution / net sales at that price when both are
positive. A zero net-sales unit is status zero_net_sales. A negative
contribution is status negative_unit_margin. Neither is coerced to 0.

Profit delta is the base scenario's period profit minus the baseline period
profit. Period profit is the scaled total minus ad spend, so a repeating
unit decimal is not multiplied back into the total.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from commerceops.engines.money import D, require_int, require_non_negative

FORMULA_VERSION = "price_sim.v1"

ELASTICITY_SCENARIOS: tuple[tuple[str, Decimal], ...] = (
    ("conservative", Decimal("-1.6")),
    ("base", Decimal("-1.0")),
    ("optimistic", Decimal("-0.4")),
)

ELASTICITY_NOTE = (
    "conservative -1.6, base -1.0, optimistic -0.4. "
    "Optimistic means demand is less elastic. "
    "A price increase then loses less volume; a price cut gains less volume. "
    "Ad spend stays at the observed window total."
)


@dataclass(frozen=True)
class PriceSimInputs:
    sku: str
    currency: str
    current_price: Decimal
    target_price: Decimal
    units: int
    gross_revenue: Decimal
    discounts: Decimal
    refunds: Decimal
    cogs: Decimal
    recovered_cogs: Decimal
    platform_fees: Decimal
    shipping_fees: Decimal
    other_fees: Decimal
    ad_spend: Decimal
    attributed_sales: Decimal


@dataclass(frozen=True)
class PriceScenario:
    name: str
    elasticity: Decimal
    volume_multiplier: Decimal
    volume_status: str
    units: Decimal
    period_profit: Decimal
    profit_delta: Decimal


@dataclass(frozen=True)
class RatioOutcome:
    value: Decimal | None
    status: str


@dataclass(frozen=True)
class PriceSimResult:
    formula_version: str
    sku: str
    currency: str
    status: str
    current_price: Decimal
    target_price: Decimal
    price_change_ratio: Decimal | None
    scale: Decimal | None
    baseline_units: int
    baseline_net_sales: Decimal | None
    baseline_contribution: Decimal | None
    baseline_unit_margin: RatioOutcome
    baseline_period_profit: Decimal | None
    new_unit_net_sales: Decimal | None
    new_unit_contribution: Decimal | None
    new_unit_margin: RatioOutcome
    break_even_acos: RatioOutcome
    current_acos: RatioOutcome
    acos_headroom: Decimal | None
    ad_spend: Decimal
    attributed_sales: Decimal
    profit_delta: Decimal | None
    elasticity_note: str
    scenarios: tuple[PriceScenario, ...]


def _trim(value: Decimal) -> Decimal:
    """Drop insignificant trailing zeros so JSON does not print -40.81000."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-", "-0"}:
        return Decimal(0)
    return Decimal(text)


def _ratio(numerator: Decimal, denominator: Decimal, zero_status: str) -> RatioOutcome:
    if denominator == 0:
        return RatioOutcome(None, zero_status)
    return RatioOutcome(_trim(numerator / denominator), "ok")


def _break_even(contribution: Decimal, net_sales: Decimal) -> RatioOutcome:
    if net_sales == 0:
        return RatioOutcome(None, "zero_net_sales")
    if net_sales < 0:
        return RatioOutcome(None, "negative_net_sales")
    if contribution < 0:
        return RatioOutcome(None, "negative_unit_margin")
    return RatioOutcome(_trim(contribution / net_sales), "ok")


def _margin(contribution: Decimal, net_sales: Decimal) -> RatioOutcome:
    if net_sales == 0:
        return RatioOutcome(None, "zero_net_sales")
    if net_sales < 0:
        return RatioOutcome(_trim(contribution / net_sales), "negative_net_sales")
    return RatioOutcome(_trim(contribution / net_sales), "ok")


def simulate_price(inputs: PriceSimInputs) -> PriceSimResult:
    current_price = D(inputs.current_price)
    target_price = D(inputs.target_price)
    units = require_int("units", inputs.units)
    gross = require_non_negative("gross_revenue", D(inputs.gross_revenue))
    discounts = require_non_negative("discounts", D(inputs.discounts))
    refunds = require_non_negative("refunds", D(inputs.refunds))
    cogs = require_non_negative("cogs", D(inputs.cogs))
    recovered = require_non_negative("recovered_cogs", D(inputs.recovered_cogs))
    platform = require_non_negative("platform_fees", D(inputs.platform_fees))
    shipping = require_non_negative("shipping_fees", D(inputs.shipping_fees))
    other = require_non_negative("other_fees", D(inputs.other_fees))
    ad_spend = require_non_negative("ad_spend", D(inputs.ad_spend))
    attributed = require_non_negative("attributed_sales", D(inputs.attributed_sales))
    if current_price <= 0:
        raise ValueError("current_price must be > 0")
    if target_price < 0:
        raise ValueError("target_price must be >= 0")

    current_acos = _ratio(ad_spend, attributed, "zero_attributed_sales")
    empty_margin = RatioOutcome(None, "zero_units")
    if units == 0:
        return PriceSimResult(
            formula_version=FORMULA_VERSION,
            sku=inputs.sku,
            currency=inputs.currency,
            status="zero_units",
            current_price=current_price,
            target_price=target_price,
            price_change_ratio=None,
            scale=None,
            baseline_units=0,
            baseline_net_sales=None,
            baseline_contribution=None,
            baseline_unit_margin=empty_margin,
            baseline_period_profit=None,
            new_unit_net_sales=None,
            new_unit_contribution=None,
            new_unit_margin=empty_margin,
            break_even_acos=RatioOutcome(None, "zero_units"),
            current_acos=current_acos,
            acos_headroom=None,
            ad_spend=ad_spend,
            attributed_sales=attributed,
            profit_delta=None,
            elasticity_note=ELASTICITY_NOTE,
            scenarios=(),
        )

    price_change_ratio = _trim((target_price - current_price) / current_price)
    scale = _trim(target_price / current_price)
    net_sales = gross - discounts - refunds
    net_cogs = cogs - recovered
    baseline_contribution = net_sales - net_cogs - platform - shipping - other
    scaled_net_sales = net_sales * scale
    scaled_platform = platform * scale
    scaled_contribution = scaled_net_sales - net_cogs - scaled_platform - shipping - other
    if scale == 1 and scaled_contribution != baseline_contribution:
        raise RuntimeError("price sim baseline identity failed")

    count = Decimal(units)
    baseline_profit = _trim(baseline_contribution - ad_spend)
    baseline_margin = _margin(baseline_contribution, net_sales)
    new_margin = _margin(scaled_contribution, scaled_net_sales)
    break_even = _break_even(scaled_contribution, scaled_net_sales)
    headroom = None
    if break_even.value is not None and current_acos.value is not None:
        headroom = _trim(break_even.value - current_acos.value)

    scenarios: list[PriceScenario] = []
    for name, elasticity in ELASTICITY_SCENARIOS:
        multiplier = Decimal(1) + elasticity * price_change_ratio
        status = "ok"
        if multiplier < 0:
            multiplier = Decimal(0)
            status = "volume_floored"
        multiplier = _trim(multiplier)
        period_profit = _trim(scaled_contribution * multiplier - ad_spend)
        scenarios.append(
            PriceScenario(
                name=name,
                elasticity=elasticity,
                volume_multiplier=multiplier,
                volume_status=status,
                units=_trim(count * multiplier),
                period_profit=period_profit,
                profit_delta=_trim(period_profit - baseline_profit),
            )
        )
    base = next(item for item in scenarios if item.name == "base")
    return PriceSimResult(
        formula_version=FORMULA_VERSION,
        sku=inputs.sku,
        currency=inputs.currency,
        status="ok",
        current_price=current_price,
        target_price=target_price,
        price_change_ratio=price_change_ratio,
        scale=scale,
        baseline_units=units,
        baseline_net_sales=_trim(net_sales),
        baseline_contribution=_trim(baseline_contribution),
        baseline_unit_margin=baseline_margin,
        baseline_period_profit=baseline_profit,
        new_unit_net_sales=_trim(scaled_net_sales / count),
        new_unit_contribution=_trim(scaled_contribution / count),
        new_unit_margin=new_margin,
        break_even_acos=break_even,
        current_acos=current_acos,
        acos_headroom=headroom,
        ad_spend=ad_spend,
        attributed_sales=attributed,
        profit_delta=base.profit_delta,
        elasticity_note=ELASTICITY_NOTE,
        scenarios=tuple(scenarios),
    )
