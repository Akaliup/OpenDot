"""Profit attribution, formula profit.v1.

net_sales = revenue - discounts - refunds
net_cogs = cogs - recovered_cogs
net_profit = net_sales - net_cogs - platform_fees - shipping_fees - ad_spend - other_fees

Ad spend is an input. Order lines have no ad field, so campaign spend cannot
be added twice. Margin is null when net_sales is 0 (status zero_net_sales).

The bridge uses one sign per component so:

    current.net_profit - previous.net_profit
        = sum(sign(component) * (current - previous))
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from commerceops.engines.money import D, require_int, require_non_negative

FORMULA_VERSION = "profit.v1"

_BRIDGE_SIGNS: tuple[tuple[str, int], ...] = (
    ("revenue", 1),
    ("discounts", -1),
    ("refunds", -1),
    ("net_cogs", -1),
    ("platform_fees", -1),
    ("shipping_fees", -1),
    ("ad_spend", -1),
    ("other_fees", -1),
)


@dataclass(frozen=True)
class OrderLine:
    quantity: int
    gross_revenue: Decimal
    discount: Decimal
    unit_cogs: Decimal
    platform_fee: Decimal
    shipping_fee: Decimal
    other_fee: Decimal


@dataclass(frozen=True)
class RefundLine:
    quantity: int
    amount: Decimal
    recovered_cogs: Decimal


@dataclass(frozen=True)
class ProfitInputs:
    revenue: Decimal
    discounts: Decimal
    refunds: Decimal
    cogs: Decimal
    recovered_cogs: Decimal
    platform_fees: Decimal
    shipping_fees: Decimal
    ad_spend: Decimal
    other_fees: Decimal


@dataclass(frozen=True)
class ProfitResult:
    formula_version: str
    revenue: Decimal
    discounts: Decimal
    refunds: Decimal
    cogs: Decimal
    recovered_cogs: Decimal
    net_cogs: Decimal
    platform_fees: Decimal
    shipping_fees: Decimal
    ad_spend: Decimal
    other_fees: Decimal
    net_sales: Decimal
    net_profit: Decimal
    margin: Decimal | None
    margin_status: str


@dataclass(frozen=True)
class BridgeComponent:
    code: str
    current: Decimal
    previous: Decimal
    contribution: Decimal


@dataclass(frozen=True)
class ProfitBridge:
    formula_version: str
    delta_net_profit: Decimal
    components: tuple[BridgeComponent, ...]
    identity_ok: bool


@dataclass(frozen=True)
class ProfitComparison:
    formula_version: str
    current: ProfitResult
    previous: ProfitResult
    bridge: ProfitBridge


def _money(name: str, value: Decimal) -> Decimal:
    return require_non_negative(name, D(value) if not isinstance(value, Decimal) else value)


def aggregate_profit(
    orders: list[OrderLine] | tuple[OrderLine, ...],
    refunds: list[RefundLine] | tuple[RefundLine, ...],
    ad_spend: Decimal,
) -> ProfitInputs:
    """Sum lines in Decimal. ad_spend is added once, from outside the lines."""
    revenue = Decimal(0)
    discounts = Decimal(0)
    cogs = Decimal(0)
    platform_fees = Decimal(0)
    shipping_fees = Decimal(0)
    other_fees = Decimal(0)
    for line in orders:
        require_int("quantity", line.quantity, minimum=1)
        revenue += _money("gross_revenue", line.gross_revenue)
        discounts += _money("discount", line.discount)
        cogs += _money("unit_cogs", line.unit_cogs) * Decimal(line.quantity)
        platform_fees += _money("platform_fee", line.platform_fee)
        shipping_fees += _money("shipping_fee", line.shipping_fee)
        other_fees += _money("other_fee", line.other_fee)
    refunds_total = Decimal(0)
    recovered = Decimal(0)
    for refund in refunds:
        require_int("refund_quantity", refund.quantity, minimum=0)
        refunds_total += _money("refund_amount", refund.amount)
        recovered += _money("recovered_cogs", refund.recovered_cogs)
    return ProfitInputs(
        revenue=revenue,
        discounts=discounts,
        refunds=refunds_total,
        cogs=cogs,
        recovered_cogs=recovered,
        platform_fees=platform_fees,
        shipping_fees=shipping_fees,
        ad_spend=_money("ad_spend", ad_spend),
        other_fees=other_fees,
    )


def calculate_profit(inputs: ProfitInputs) -> ProfitResult:
    revenue = _money("revenue", inputs.revenue)
    discounts = _money("discounts", inputs.discounts)
    refunds = _money("refunds", inputs.refunds)
    cogs = _money("cogs", inputs.cogs)
    recovered = _money("recovered_cogs", inputs.recovered_cogs)
    platform_fees = _money("platform_fees", inputs.platform_fees)
    shipping_fees = _money("shipping_fees", inputs.shipping_fees)
    ad_spend = _money("ad_spend", inputs.ad_spend)
    other_fees = _money("other_fees", inputs.other_fees)
    net_cogs = cogs - recovered
    net_sales = revenue - discounts - refunds
    net_profit = net_sales - net_cogs - platform_fees - shipping_fees - ad_spend - other_fees
    if net_sales == 0:
        margin: Decimal | None = None
        margin_status = "zero_net_sales"
    else:
        margin = net_profit / net_sales
        margin_status = "negative_net_sales" if net_sales < 0 else "ok"
    return ProfitResult(
        formula_version=FORMULA_VERSION,
        revenue=revenue,
        discounts=discounts,
        refunds=refunds,
        cogs=cogs,
        recovered_cogs=recovered,
        net_cogs=net_cogs,
        platform_fees=platform_fees,
        shipping_fees=shipping_fees,
        ad_spend=ad_spend,
        other_fees=other_fees,
        net_sales=net_sales,
        net_profit=net_profit,
        margin=margin,
        margin_status=margin_status,
    )


def calculate_profit_margin(inputs: ProfitInputs) -> tuple[Decimal | None, str]:
    result = calculate_profit(inputs)
    return result.margin, result.margin_status


def calculate_profit_bridge(current: ProfitResult, previous: ProfitResult) -> ProfitBridge:
    components: list[BridgeComponent] = []
    for code, sign in _BRIDGE_SIGNS:
        current_value = getattr(current, code)
        previous_value = getattr(previous, code)
        components.append(
            BridgeComponent(
                code=code,
                current=current_value,
                previous=previous_value,
                contribution=Decimal(sign) * (current_value - previous_value),
            )
        )
    delta = current.net_profit - previous.net_profit
    total = sum((item.contribution for item in components), Decimal(0))
    if total != delta:
        raise RuntimeError("profit bridge identity failed")
    return ProfitBridge(
        formula_version=FORMULA_VERSION,
        delta_net_profit=delta,
        components=tuple(components),
        identity_ok=True,
    )


def compare_profit_periods(current: ProfitInputs, previous: ProfitInputs) -> ProfitComparison:
    current_result = calculate_profit(current)
    previous_result = calculate_profit(previous)
    return ProfitComparison(
        formula_version=FORMULA_VERSION,
        current=current_result,
        previous=previous_result,
        bridge=calculate_profit_bridge(current_result, previous_result),
    )


def profit_drags(bridge: ProfitBridge) -> list[BridgeComponent]:
    drags = [item for item in bridge.components if item.contribution < 0]
    drags.sort(key=lambda item: (item.contribution, item.code))
    return drags
