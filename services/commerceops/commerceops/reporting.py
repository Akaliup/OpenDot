"""Read models. SQL loads rows; engines do the arithmetic."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from commerceops.engines.ads import (
    FORMULA_VERSION as ADS_VERSION,
    AdMetrics,
    AdTotals,
    calculate_ad_metrics,
    diagnose_flags,
    suggest_budget,
)
from commerceops.engines.competitor import FORMULA_VERSION as COMPETITOR_VERSION
from commerceops.engines.competitor import Snapshot, diff_history
from commerceops.engines.inventory import FORMULA_VERSION as INVENTORY_VERSION
from commerceops.engines.inventory import analyze_cover, plan_replenishment
from commerceops.engines.money import money_str, ratio_str
from commerceops.engines.profit import (
    FORMULA_VERSION as PROFIT_VERSION,
    OrderLine,
    RefundLine,
    aggregate_profit,
    compare_profit_periods,
    profit_drags,
)
from commerceops.engines.suppliers import FORMULA_VERSION as SUPPLIER_VERSION
from commerceops.engines.suppliers import SupplierQuoteInput, rank_suppliers
from commerceops.errors import CommerceOpsError, NoActionRequired, StoreNotFound
from commerceops.models import (
    AdCampaign,
    AdMetricDay,
    CompetitorSnapshot,
    InventorySnapshot,
    Order,
    Product,
    Refund,
    Store,
    Supplier,
    SupplierQuote,
)
from commerceops.periods import previous_period

_SALES_DEFINITION = "gross_revenue - discounts; refunds are not removed and ad spend is not deducted"


def list_stores(session: Session) -> dict:
    stores = session.scalars(select(Store).order_by(Store.code)).all()
    return {
        "stores": [
            {
                "code": store.code,
                "name": store.name,
                "marketplace": store.marketplace,
                "currency": store.currency,
                "timezone": store.timezone,
            }
            for store in stores
        ]
    }


def profit_report(session: Session, store_code: str, start: date, end: date, compare: bool = True) -> dict:
    store = _store(session, store_code)
    _window(start, end)
    current_orders = _orders(session, store.id, start, end)
    current_refunds = _refunds(session, store.id, start, end)
    current_inputs = aggregate_profit(
        [_order_line(row) for row in current_orders],
        [_refund_line(row) for row in current_refunds],
        _ad_spend(session, store.id, start, end),
    )
    previous_bounds = previous_period(start, end) if compare else None
    previous_result = None
    bridge = None
    drags = []
    if previous_bounds is not None:
        prev_start, prev_end = previous_bounds
        previous_inputs = aggregate_profit(
            [_order_line(row) for row in _orders(session, store.id, prev_start, prev_end)],
            [_refund_line(row) for row in _refunds(session, store.id, prev_start, prev_end)],
            _ad_spend(session, store.id, prev_start, prev_end),
        )
        comparison = compare_profit_periods(current_inputs, previous_inputs)
        current_result = comparison.current
        previous_result = comparison.previous
        bridge = comparison.bridge
        drags = profit_drags(bridge)
    else:
        from commerceops.engines.profit import calculate_profit

        current_result = calculate_profit(current_inputs)
    return {
        "formula_version": PROFIT_VERSION,
        "store_code": store.code,
        "currency": store.currency,
        "period": {"start": start, "end": end},
        "previous_period": (
            None if previous_bounds is None else {"start": previous_bounds[0], "end": previous_bounds[1]}
        ),
        "units_sold": sum(row.quantity for row in current_orders),
        "units_refunded": sum(row.quantity for row in current_refunds),
        "ad_spend_source": "ad_metric_days",
        "current": current_result,
        "previous": previous_result,
        "bridge": bridge,
        "drags": drags,
    }


def ads_report(session: Session, store_code: str, start: date, end: date, compare: bool = True) -> dict:
    store = _store(session, store_code)
    _window(start, end)
    previous_bounds = previous_period(start, end) if compare else None
    orders = _orders(session, store.id, start, end)
    total_sales = sum((row.gross_revenue - row.discount for row in orders), Decimal(0))
    campaigns = session.scalars(
        select(AdCampaign).where(AdCampaign.store_id == store.id).order_by(AdCampaign.external_id)
    ).all()
    campaign_rows = []
    store_impressions = 0
    store_clicks = 0
    store_spend = Decimal(0)
    store_attributed_sales = Decimal(0)
    store_orders = 0
    for campaign in campaigns:
        current_totals = _ad_totals(session, campaign.id, start, end)
        previous_totals = (
            _ad_totals(session, campaign.id, previous_bounds[0], previous_bounds[1])
            if previous_bounds is not None
            else None
        )
        current_base = _tacos_base(session, store, campaign, start, end, total_sales)
        previous_base = (
            _tacos_base(session, store, campaign, previous_bounds[0], previous_bounds[1], None)
            if previous_bounds is not None
            else Decimal(0)
        )
        current_metrics = calculate_ad_metrics(current_totals or _zero_totals(), current_base)
        previous_metrics = (
            None
            if previous_totals is None
            else calculate_ad_metrics(previous_totals, previous_base)
        )
        flags = diagnose_flags(current_metrics, previous_metrics)
        suggestion = suggest_budget(campaign.daily_budget, current_metrics, flags)
        if current_totals is not None:
            store_impressions += current_totals.impressions
            store_clicks += current_totals.clicks
            store_spend += current_totals.spend
            store_attributed_sales += current_totals.attributed_sales
            store_orders += current_totals.attributed_orders
        campaign_rows.append(
            {
                "campaign_external_id": campaign.external_id,
                "name": campaign.name,
                "sku": _sku(session, campaign.product_id),
                "current": current_metrics,
                "previous": previous_metrics,
                "flags": flags,
                "budget": suggestion,
            }
        )
    store_metrics = calculate_ad_metrics(
        AdTotals(store_impressions, store_clicks, store_spend, store_attributed_sales, store_orders),
        total_sales,
    )
    return {
        "formula_version": ADS_VERSION,
        "store_code": store.code,
        "currency": store.currency,
        "period": {"start": start, "end": end},
        "previous_period": (
            None if previous_bounds is None else {"start": previous_bounds[0], "end": previous_bounds[1]}
        ),
        "total_sales": total_sales,
        "total_sales_definition": _SALES_DEFINITION,
        "total_ad_spend": store_spend,
        "tacos": store_metrics.tacos,
        "attributed_sales_note": "summed across campaigns and not deduplicated",
        "campaigns": campaign_rows,
    }


def budget_decision(
    session: Session,
    store_code: str,
    campaign_external_id: str,
    start: date,
    end: date,
) -> tuple[dict, dict]:
    report = ads_report(session, store_code, start, end, compare=True)
    match = next(
        (row for row in report["campaigns"] if row["campaign_external_id"] == campaign_external_id),
        None,
    )
    if match is None:
        raise CommerceOpsError(
            f"campaign not found: {campaign_external_id}",
            code="campaign_not_found",
            status_code=404,
        )
    suggestion = match["budget"]
    if suggestion.reason == "no_adjustment":
        raise NoActionRequired(
            "campaign does not qualify for a budget cut",
            code="no_adjustment_required",
        )
    decision = {
        "campaign_external_id": campaign_external_id,
        "from_daily_budget": money_str(suggestion.current_daily_budget),
        "to_daily_budget": money_str(suggestion.suggested_daily_budget),
        "multiplier": ratio_str(suggestion.multiplier),
        "reason": suggestion.reason,
    }
    evidence = {
        "flags": match["flags"],
        "current": _metrics_brief(match["current"]),
        "previous": None if match["previous"] is None else _metrics_brief(match["previous"]),
    }
    return decision, evidence


def inventory_report(
    session: Session,
    store_code: str,
    as_of: date,
    horizon_days: int = 14,
    lookback_days: int = 14,
) -> dict:
    store = _store(session, store_code)
    if horizon_days < 0 or lookback_days < 1:
        raise CommerceOpsError("invalid inventory window", code="invalid_period", status_code=422)
    velocity_end = as_of - timedelta(days=1)
    velocity_start = as_of - timedelta(days=lookback_days)
    products = session.scalars(select(Product).where(Product.store_id == store.id).order_by(Product.sku)).all()
    skus = []
    for product in products:
        snapshot = _snapshot(session, product.id, as_of)
        if snapshot is None:
            skus.append({"sku": product.sku, "status": "no_snapshot", "at_risk": False})
            continue
        units = _units_sold(session, product.id, velocity_start, velocity_end)
        cover = analyze_cover(
            on_hand=snapshot.on_hand,
            reserved=snapshot.reserved,
            units_sold=units,
            lookback_days=lookback_days,
            as_of=as_of,
            horizon_days=horizon_days,
        )
        replenishment = plan_replenishment(
            average_daily_sales_value=cover.average_daily_sales,
            planning_lead_time_days=snapshot.planning_lead_time_days,
            target_cover_days=snapshot.target_cover_days,
            safety_stock=snapshot.safety_stock,
            available=cover.available,
            inbound_qty=snapshot.inbound_qty,
            inbound_eta=snapshot.inbound_eta,
            stockout_date=cover.stockout_date,
            velocity_status=cover.status,
        )
        skus.append(
            {
                "sku": product.sku,
                "status": "ok",
                "snapshot_date": snapshot.snapshot_date,
                "cover": cover,
                "replenishment": replenishment,
                "at_risk": cover.at_risk,
            }
        )
    return {
        "formula_version": INVENTORY_VERSION,
        "store_code": store.code,
        "as_of": as_of,
        "horizon_days": horizon_days,
        "lookback_days": lookback_days,
        "velocity_window": {"start": velocity_start, "end": velocity_end},
        "demand_definition": "gross units ordered; refunds are not subtracted",
        "skus": skus,
        "at_risk_skus": [row["sku"] for row in skus if row["at_risk"]],
    }


def supplier_report(
    session: Session,
    store_code: str,
    sku: str,
    as_of: date,
    horizon_days: int = 14,
    lookback_days: int = 14,
) -> dict:
    inventory = inventory_report(session, store_code, as_of, horizon_days, lookback_days)
    row = next((item for item in inventory["skus"] if item["sku"] == sku), None)
    if row is None:
        raise CommerceOpsError(f"sku not found: {sku}", code="sku_not_found", status_code=404)
    if row["status"] != "ok":
        raise CommerceOpsError(f"no inventory snapshot for {sku}", code="no_snapshot", status_code=409)
    quotes = session.execute(
        select(SupplierQuote, Supplier)
        .join(Supplier, Supplier.id == SupplierQuote.supplier_id)
        .where(SupplierQuote.sku == sku)
        .order_by(Supplier.code, SupplierQuote.tier_min_qty)
    ).all()
    inputs = [
        SupplierQuoteInput(
            supplier_code=supplier.code,
            tier_min_qty=quote.tier_min_qty,
            unit_price=quote.unit_price,
            duty_rate=quote.duty_rate,
            freight_per_unit=quote.freight_per_unit,
            moq=quote.moq,
            lead_time_days=quote.lead_time_days,
            order_multiple=quote.order_multiple,
            on_time_rate=quote.on_time_rate,
            on_time_sample_size=quote.on_time_sample_size,
            currency=quote.currency,
        )
        for quote, supplier in quotes
    ]
    cover = row["cover"]
    replenishment = row["replenishment"]
    ranked = rank_suppliers(
        inputs,
        average_daily_sales=cover.average_daily_sales,
        available=cover.available,
        inbound_qty=replenishment.inbound_qty,
        safety_stock=_safety(session, store_code, sku, as_of),
        target_cover_days=_target(session, store_code, sku, as_of),
        days_of_cover=cover.days_of_cover,
        velocity_ok=cover.status == "ok",
    )
    return {
        "formula_version": SUPPLIER_VERSION,
        "store_code": store_code,
        "sku": sku,
        "as_of": as_of,
        "average_daily_sales": cover.average_daily_sales,
        "days_of_cover": cover.days_of_cover,
        "velocity_status": cover.status,
        "planning_suggested_order_qty": replenishment.suggested_order_qty,
        "rank": ranked,
    }


def purchase_decision(
    session: Session,
    store_code: str,
    sku: str,
    as_of: date,
    supplier_code: str | None = None,
) -> tuple[dict, dict]:
    report = supplier_report(session, store_code, sku, as_of)
    ranked = report["rank"]
    if ranked.status != "ok" or not ranked.rankings:
        raise NoActionRequired(
            f"cannot rank suppliers: {ranked.status}",
            code=ranked.status,
        )
    if supplier_code:
        chosen = next((row for row in ranked.rankings if row.supplier_code == supplier_code), None)
        if chosen is None:
            raise CommerceOpsError(
                f"supplier has no quote for {sku}",
                code="supplier_not_found",
                status_code=404,
            )
    else:
        chosen = ranked.rankings[0]
    if not chosen.adjusted_order_qty:
        raise NoActionRequired("raw need is zero", code="no_purchase_needed")
    decision = {
        "sku": sku,
        "supplier_code": chosen.supplier_code,
        "quantity": chosen.adjusted_order_qty,
        "unit_landed_cost": money_str(chosen.landed_cost),
        "currency": chosen.currency,
        "lead_time_days": chosen.lead_time_days,
        "lead_time_risk": chosen.lead_time_risk,
    }
    return decision, {"rank_status": ranked.status, "supplier_code": chosen.supplier_code}


def competitor_report(session: Session, store_code: str, sku: str, as_of: date) -> dict:
    store = _store(session, store_code)
    product = _product(session, store, sku)
    cutoff = f"{as_of.isoformat()}T23:59:59Z"
    rows = session.scalars(
        select(CompetitorSnapshot)
        .where(CompetitorSnapshot.product_id == product.id, CompetitorSnapshot.captured_at <= cutoff)
        .order_by(CompetitorSnapshot.competitor_asin, CompetitorSnapshot.captured_at)
    ).all()
    grouped: dict[str, list[Snapshot]] = {}
    for row in rows:
        grouped.setdefault(row.competitor_asin, []).append(_snapshot_input(row))
    comparisons = [diff_history(grouped[asin]) for asin in sorted(grouped)]
    methods = {row.collection_method for row in rows}
    return {
        "formula_version": COMPETITOR_VERSION,
        "store_code": store.code,
        "sku": sku,
        "our_list_price": product.list_price,
        "currency": product.currency,
        "as_of": as_of,
        "data_origin": "imported_snapshots",
        "sample_data": bool(methods) and methods <= {"demo_seed"},
        "comparisons": comparisons,
    }


def competitor_decision(session: Session, store_code: str, sku: str, as_of: date) -> tuple[dict, dict]:
    report = competitor_report(session, store_code, sku, as_of)
    actions = []
    for comparison in report["comparisons"]:
        for action in comparison.get("suggested_actions", []):
            actions.append(
                {
                    "code": action["code"],
                    "alert": action["alert"],
                    "competitor_asin": action["competitor_asin"],
                    "detail": action["detail"],
                }
            )
    actions.sort(key=lambda item: (item["competitor_asin"], item["alert"]))
    if not actions:
        raise NoActionRequired("no competitor alerts in this window", code="no_alerts")
    return {"sku": sku, "actions": actions}, {"comparison_count": len(report["comparisons"])}


def _store(session: Session, store_code: str) -> Store:
    store = session.scalar(select(Store).where(Store.code == store_code))
    if store is None:
        raise StoreNotFound(store_code)
    return store


def _product(session: Session, store: Store, sku: str) -> Product:
    product = session.scalar(select(Product).where(Product.store_id == store.id, Product.sku == sku))
    if product is None:
        raise CommerceOpsError(f"sku not found: {sku}", code="sku_not_found", status_code=404)
    return product


def _window(start: date, end: date) -> None:
    try:
        previous_period(start, end)
    except ValueError as exc:
        raise CommerceOpsError(str(exc), code="invalid_period", status_code=422) from exc


def _orders(session: Session, store_id: str, start: date, end: date) -> list[Order]:
    return list(
        session.scalars(
            select(Order).where(Order.store_id == store_id, Order.ordered_at >= start, Order.ordered_at <= end)
        ).all()
    )


def _refunds(session: Session, store_id: str, start: date, end: date) -> list[Refund]:
    return list(
        session.scalars(
            select(Refund).where(Refund.store_id == store_id, Refund.refunded_at >= start, Refund.refunded_at <= end)
        ).all()
    )


def _order_line(row: Order) -> OrderLine:
    return OrderLine(
        quantity=row.quantity,
        gross_revenue=row.gross_revenue,
        discount=row.discount,
        unit_cogs=row.unit_cogs,
        platform_fee=row.platform_fee,
        shipping_fee=row.shipping_fee,
        other_fee=row.other_fee,
    )


def _refund_line(row: Refund) -> RefundLine:
    return RefundLine(quantity=row.quantity, amount=row.amount, recovered_cogs=row.recovered_cogs)


def _ad_spend(session: Session, store_id: str, start: date, end: date) -> Decimal:
    rows = session.execute(
        select(AdMetricDay.spend)
        .join(AdCampaign, AdCampaign.id == AdMetricDay.campaign_id)
        .where(AdCampaign.store_id == store_id, AdMetricDay.metric_date >= start, AdMetricDay.metric_date <= end)
    ).all()
    return sum((spend for (spend,) in rows), Decimal(0))


def _ad_totals(session: Session, campaign_id: str, start: date, end: date) -> AdTotals | None:
    rows = session.scalars(
        select(AdMetricDay).where(
            AdMetricDay.campaign_id == campaign_id,
            AdMetricDay.metric_date >= start,
            AdMetricDay.metric_date <= end,
        )
    ).all()
    if not rows:
        return None
    return AdTotals(
        impressions=sum(row.impressions for row in rows),
        clicks=sum(row.clicks for row in rows),
        spend=sum((row.spend for row in rows), Decimal(0)),
        attributed_sales=sum((row.attributed_sales for row in rows), Decimal(0)),
        attributed_orders=sum(row.attributed_orders for row in rows),
    )


def _zero_totals() -> AdTotals:
    return AdTotals(0, 0, Decimal(0), Decimal(0), 0)


def _tacos_base(
    session: Session,
    store: Store,
    campaign: AdCampaign,
    start: date,
    end: date,
    store_sales: Decimal | None,
) -> Decimal:
    if campaign.product_id is None:
        if store_sales is not None:
            return store_sales
        rows = _orders(session, store.id, start, end)
        return sum((row.gross_revenue - row.discount for row in rows), Decimal(0))
    rows = session.scalars(
        select(Order).where(
            Order.product_id == campaign.product_id,
            Order.ordered_at >= start,
            Order.ordered_at <= end,
        )
    ).all()
    return sum((row.gross_revenue - row.discount for row in rows), Decimal(0))


def _sku(session: Session, product_id: str | None) -> str | None:
    if product_id is None:
        return None
    product = session.get(Product, product_id)
    return None if product is None else product.sku


def _snapshot(session: Session, product_id: str, as_of: date) -> InventorySnapshot | None:
    return session.scalars(
        select(InventorySnapshot)
        .where(InventorySnapshot.product_id == product_id, InventorySnapshot.snapshot_date <= as_of)
        .order_by(InventorySnapshot.snapshot_date.desc())
    ).first()


def _units_sold(session: Session, product_id: str, start: date, end: date) -> int:
    rows = session.scalars(
        select(Order).where(Order.product_id == product_id, Order.ordered_at >= start, Order.ordered_at <= end)
    ).all()
    return sum(row.quantity for row in rows)


def _safety(session: Session, store_code: str, sku: str, as_of: date) -> int:
    store = _store(session, store_code)
    product = _product(session, store, sku)
    snapshot = _snapshot(session, product.id, as_of)
    if snapshot is None:
        raise CommerceOpsError("no inventory snapshot", code="no_snapshot", status_code=409)
    return snapshot.safety_stock


def _target(session: Session, store_code: str, sku: str, as_of: date) -> int:
    store = _store(session, store_code)
    product = _product(session, store, sku)
    snapshot = _snapshot(session, product.id, as_of)
    if snapshot is None:
        raise CommerceOpsError("no inventory snapshot", code="no_snapshot", status_code=409)
    return snapshot.target_cover_days


def _snapshot_input(row: CompetitorSnapshot) -> Snapshot:
    return Snapshot(
        competitor_asin=row.competitor_asin,
        competitor_title=row.competitor_title,
        captured_at=row.captured_at,
        source=row.source,
        collection_method=row.collection_method,
        price=row.price,
        currency=row.currency,
        bsr=row.bsr,
        rating=row.rating,
        review_count=row.review_count,
        negative_review_hits=row.negative_review_hits,
        negative_keywords=row.negative_keywords,
    )


def _metrics_brief(metrics: AdMetrics) -> dict:
    return {
        "spend": money_str(metrics.spend),
        "attributed_sales": money_str(metrics.attributed_sales),
        "acos": ratio_str(metrics.acos.value),
        "acos_status": metrics.acos.status,
        "cvr": ratio_str(metrics.cvr.value),
        "cvr_status": metrics.cvr.status,
        "roas": ratio_str(metrics.roas.value),
        "roas_status": metrics.roas.status,
    }
