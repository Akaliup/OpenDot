"""Supplier ranking, formula supplier.v1.

landed_unit_cost = unit_price * (1 + duty_rate) + freight_per_unit

Score = 0.40 * cost + 0.25 * lead + 0.20 * MOQ fit + 0.15 * on-time rate.
Weights sum to 1. Cost and lead are normalized against the best quote in the
comparison set. MOQ fit is raw need / MOQ, capped at 1. On-time rate counts
only when sample_size >= 8; otherwise that component is 0 and the status is
insufficient_sample. The weights are not redistributed.

Quantity is ceiling(raw need) snapped to the order multiple, then raised to
MOQ when the snapped quantity is still short. A raw need of 0 stays 0: MOQ
does not create a purchase.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from types import MappingProxyType

from commerceops.engines.inventory import unconstrained_need
from commerceops.engines.money import require_int, require_non_negative

FORMULA_VERSION = "supplier.v1"
MIN_ON_TIME_SAMPLE = 8
WEIGHTS = MappingProxyType(
    {
        "landed_cost": Decimal("0.40"),
        "lead_time": Decimal("0.25"),
        "moq_fit": Decimal("0.20"),
        "on_time_delivery": Decimal("0.15"),
    }
)
WEIGHT_NOTE = (
    "Score = 0.40*normalized landed cost + 0.25*normalized lead time "
    "+ 0.20*MOQ fit + 0.15*on-time rate. "
    "Cost and lead time are normalized against the cheapest and fastest quote "
    "in this comparison. MOQ fit is raw need / MOQ, capped at 1. "
    "On-time rate is used only when sample_size >= 8; otherwise its component "
    "is 0 and on_time_status is insufficient_sample. Weights sum to 1. "
    "This score is arithmetic, not a model opinion."
)


@dataclass(frozen=True)
class SupplierQuoteInput:
    supplier_code: str
    tier_min_qty: int
    unit_price: Decimal
    duty_rate: Decimal
    freight_per_unit: Decimal
    moq: int
    lead_time_days: int
    order_multiple: int
    on_time_rate: Decimal | None
    on_time_sample_size: int
    currency: str


@dataclass(frozen=True)
class RankedQuote:
    supplier_code: str
    rank: int | None
    tier_min_qty: int
    unit_price: Decimal
    landed_cost: Decimal
    moq: int
    order_multiple: int
    raw_need: Decimal | None
    adjusted_order_qty: int | None
    lead_time_days: int
    lead_time_risk: str
    on_time_rate: Decimal | None
    on_time_sample_size: int
    on_time_status: str
    score: Decimal | None
    components: dict[str, Decimal] | None
    currency: str


@dataclass(frozen=True)
class SupplierRankResult:
    formula_version: str
    status: str
    ranked: bool
    weights: dict[str, Decimal]
    weight_note: str
    min_on_time_sample: int
    rankings: tuple[RankedQuote, ...]


def landed_unit_cost(unit_price: Decimal, duty_rate: Decimal, freight_per_unit: Decimal) -> Decimal:
    price = require_non_negative("unit_price", unit_price)
    duty = require_non_negative("duty_rate", duty_rate)
    if duty > 1:
        raise ValueError("duty_rate must be <= 1")
    freight = require_non_negative("freight_per_unit", freight_per_unit)
    return price * (Decimal(1) + duty) + freight


def ceil_to_multiple(quantity: Decimal, multiple: int) -> int:
    require_int("order_multiple", multiple, minimum=1)
    if quantity <= 0:
        return 0
    units = (quantity / Decimal(multiple)).to_integral_value(rounding=ROUND_CEILING)
    return int(units) * multiple


def apply_moq_and_multiple(raw: Decimal, moq: int, multiple: int) -> int:
    require_int("moq", moq, minimum=1)
    if raw <= 0:
        return 0
    quantity = ceil_to_multiple(raw, multiple)
    if quantity < moq:
        quantity = ceil_to_multiple(Decimal(moq), multiple)
    return quantity


def select_tier(quotes: list[SupplierQuoteInput] | tuple[SupplierQuoteInput, ...], quantity: int) -> SupplierQuoteInput:
    if not quotes:
        raise ValueError("no tiers")
    eligible = [quote for quote in quotes if quote.tier_min_qty <= max(quantity, 1)]
    pool = eligible or list(quotes)
    return max(pool, key=lambda quote: (quote.tier_min_qty, quote.supplier_code))


def _lead_risk(lead_time_days: int, days_of_cover: Decimal | None) -> str:
    if days_of_cover is None:
        return "unknown_velocity"
    lead = Decimal(lead_time_days)
    if lead > days_of_cover:
        return "arrives_after_stockout"
    if lead > days_of_cover * Decimal("0.5"):
        return "tight"
    return "comfortable"


def _on_time(quote: SupplierQuoteInput) -> tuple[Decimal, str]:
    if quote.on_time_rate is None or quote.on_time_sample_size < MIN_ON_TIME_SAMPLE:
        return Decimal(0), "insufficient_sample"
    rate = require_non_negative("on_time_rate", quote.on_time_rate)
    if rate > 1:
        raise ValueError("on_time_rate must be <= 1")
    return rate, "ok"


def _assert_consistent(group: list[SupplierQuoteInput]) -> None:
    first = group[0]
    for quote in group[1:]:
        if (
            quote.lead_time_days != first.lead_time_days
            or quote.moq != first.moq
            or quote.order_multiple != first.order_multiple
            or quote.duty_rate != first.duty_rate
            or quote.currency != first.currency
        ):
            raise ValueError(f"inconsistent quote terms for {first.supplier_code}")


def _prepare(quote: SupplierQuoteInput) -> None:
    require_int("tier_min_qty", quote.tier_min_qty, minimum=1)
    require_int("lead_time_days", quote.lead_time_days, minimum=1)
    require_int("moq", quote.moq, minimum=1)
    require_int("order_multiple", quote.order_multiple, minimum=1)
    require_int("on_time_sample_size", quote.on_time_sample_size)
    if not quote.supplier_code:
        raise ValueError("supplier_code is required")


def rank_suppliers(
    quotes: list[SupplierQuoteInput] | tuple[SupplierQuoteInput, ...],
    *,
    average_daily_sales: Decimal,
    available: int,
    inbound_qty: int,
    safety_stock: int,
    target_cover_days: int,
    days_of_cover: Decimal | None,
    velocity_ok: bool,
) -> SupplierRankResult:
    if sum(WEIGHTS.values(), Decimal(0)) != 1:
        raise RuntimeError("supplier weights must sum to 1")
    if not quotes:
        return SupplierRankResult(
            formula_version=FORMULA_VERSION,
            status="no_quotes",
            ranked=False,
            weights=dict(WEIGHTS),
            weight_note=WEIGHT_NOTE,
            min_on_time_sample=MIN_ON_TIME_SAMPLE,
            rankings=(),
        )
    grouped: dict[str, list[SupplierQuoteInput]] = {}
    for quote in quotes:
        _prepare(quote)
        grouped.setdefault(quote.supplier_code, []).append(quote)
    for group in grouped.values():
        _assert_consistent(group)

    prepared: list[dict] = []
    for code, group in grouped.items():
        lead = group[0].lead_time_days
        if velocity_ok and average_daily_sales > 0:
            raw = unconstrained_need(
                average_daily_sales,
                lead,
                target_cover_days,
                safety_stock,
                available,
                inbound_qty,
            )
            tier_qty = int(raw.to_integral_value(rounding=ROUND_CEILING)) if raw > 0 else 0
            tier = select_tier(group, tier_qty if tier_qty > 0 else group[0].moq)
            adjusted = apply_moq_and_multiple(raw, tier.moq, tier.order_multiple)
            retier = select_tier(group, adjusted if adjusted > 0 else tier.moq)
            if retier.tier_min_qty != tier.tier_min_qty:
                tier = retier
                adjusted = apply_moq_and_multiple(raw, tier.moq, tier.order_multiple)
            if raw <= 0:
                moq_fit = Decimal(0)
            elif raw >= Decimal(tier.moq):
                moq_fit = Decimal(1)
            else:
                moq_fit = raw / Decimal(tier.moq)
        else:
            raw = None
            adjusted = None
            tier = select_tier(group, min(item.tier_min_qty for item in group))
            moq_fit = None
        landed = landed_unit_cost(tier.unit_price, tier.duty_rate, tier.freight_per_unit)
        on_time_score, on_time_status = _on_time(tier)
        prepared.append(
            {
                "code": code,
                "tier": tier,
                "landed": landed,
                "raw": raw,
                "adjusted": adjusted,
                "moq_fit": moq_fit,
                "on_time_score": on_time_score,
                "on_time_status": on_time_status,
                "risk": _lead_risk(lead, days_of_cover if velocity_ok else None),
            }
        )

    if not velocity_ok or average_daily_sales <= 0:
        prepared.sort(key=lambda item: (item["landed"], item["code"]))
        rankings = [
            RankedQuote(
                supplier_code=item["code"],
                rank=None,
                tier_min_qty=item["tier"].tier_min_qty,
                unit_price=item["tier"].unit_price,
                landed_cost=item["landed"],
                moq=item["tier"].moq,
                order_multiple=item["tier"].order_multiple,
                raw_need=None,
                adjusted_order_qty=None,
                lead_time_days=item["tier"].lead_time_days,
                lead_time_risk="unknown_velocity",
                on_time_rate=item["tier"].on_time_rate,
                on_time_sample_size=item["tier"].on_time_sample_size,
                on_time_status=item["on_time_status"],
                score=None,
                components=None,
                currency=item["tier"].currency,
            )
            for item in prepared
        ]
        return SupplierRankResult(
            formula_version=FORMULA_VERSION,
            status="insufficient_velocity",
            ranked=False,
            weights=dict(WEIGHTS),
            weight_note=WEIGHT_NOTE,
            min_on_time_sample=MIN_ON_TIME_SAMPLE,
            rankings=tuple(rankings),
        )

    min_landed = min(item["landed"] for item in prepared)
    min_lead = min(item["tier"].lead_time_days for item in prepared)
    scored: list[RankedQuote] = []
    for item in prepared:
        landed = item["landed"]
        if min_landed == 0:
            cost_score = Decimal(1) if landed == 0 else Decimal(0)
        else:
            cost_score = min_landed / landed
        lead_score = Decimal(min_lead) / Decimal(item["tier"].lead_time_days)
        components = {
            "landed_cost": cost_score,
            "lead_time": lead_score,
            "moq_fit": item["moq_fit"],
            "on_time_delivery": item["on_time_score"],
        }
        score = sum((WEIGHTS[key] * components[key] for key in WEIGHTS), Decimal(0))
        scored.append(
            RankedQuote(
                supplier_code=item["code"],
                rank=0,
                tier_min_qty=item["tier"].tier_min_qty,
                unit_price=item["tier"].unit_price,
                landed_cost=landed,
                moq=item["tier"].moq,
                order_multiple=item["tier"].order_multiple,
                raw_need=item["raw"],
                adjusted_order_qty=item["adjusted"],
                lead_time_days=item["tier"].lead_time_days,
                lead_time_risk=item["risk"],
                on_time_rate=item["tier"].on_time_rate,
                on_time_sample_size=item["tier"].on_time_sample_size,
                on_time_status=item["on_time_status"],
                score=score,
                components=components,
                currency=item["tier"].currency,
            )
        )
    scored.sort(key=lambda row: (-(row.score or Decimal(0)), row.landed_cost, row.supplier_code))
    ranked = tuple(
        RankedQuote(
            supplier_code=row.supplier_code,
            rank=index,
            tier_min_qty=row.tier_min_qty,
            unit_price=row.unit_price,
            landed_cost=row.landed_cost,
            moq=row.moq,
            order_multiple=row.order_multiple,
            raw_need=row.raw_need,
            adjusted_order_qty=row.adjusted_order_qty,
            lead_time_days=row.lead_time_days,
            lead_time_risk=row.lead_time_risk,
            on_time_rate=row.on_time_rate,
            on_time_sample_size=row.on_time_sample_size,
            on_time_status=row.on_time_status,
            score=row.score,
            components=row.components,
            currency=row.currency,
        )
        for index, row in enumerate(scored, start=1)
    )
    return SupplierRankResult(
        formula_version=FORMULA_VERSION,
        status="ok",
        ranked=True,
        weights=dict(WEIGHTS),
        weight_note=WEIGHT_NOTE,
        min_on_time_sample=MIN_ON_TIME_SAMPLE,
        rankings=ranked,
    )
