"""CSV and JSON upserts.

The whole batch is validated before any write. A second import of the same
natural key updates the row instead of inserting another one. Import is the
operator data plane: it is not an MCP tool and it does not write an approval.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from commerceops.engines.money import D
from commerceops.errors import CommerceOpsError, ImportValidationError
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

DATASETS = (
    "orders",
    "refunds",
    "ad_metrics",
    "inventory",
    "supplier_quotes",
    "competitor_snapshots",
)

MAX_BYTES = 2_000_000
MAX_ROWS = 10_000
COLLECTION_METHODS = {"demo_seed", "manual_import", "licensed_feed"}
_CAPTURED_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_INT = re.compile(r"[0-9]+")

REQUIRED: dict[str, tuple[str, ...]] = {
    "orders": (
        "store_code",
        "external_order_id",
        "line_id",
        "sku",
        "ordered_at",
        "quantity",
        "gross_revenue",
        "discount",
        "unit_cogs",
        "platform_fee",
        "shipping_fee",
        "other_fee",
        "currency",
    ),
    "refunds": (
        "store_code",
        "external_refund_id",
        "sku",
        "refunded_at",
        "quantity",
        "amount",
        "recovered_cogs",
        "currency",
    ),
    "ad_metrics": (
        "store_code",
        "campaign_external_id",
        "campaign_name",
        "sku",
        "daily_budget",
        "metric_date",
        "impressions",
        "clicks",
        "spend",
        "attributed_sales",
        "attributed_orders",
        "currency",
    ),
    "inventory": (
        "store_code",
        "sku",
        "snapshot_date",
        "on_hand",
        "reserved",
        "inbound_qty",
        "safety_stock",
        "target_cover_days",
        "planning_lead_time_days",
    ),
    "supplier_quotes": (
        "supplier_code",
        "supplier_name",
        "sku",
        "tier_min_qty",
        "unit_price",
        "currency",
        "moq",
        "lead_time_days",
        "order_multiple",
        "freight_per_unit",
        "duty_rate",
        "on_time_sample_size",
    ),
    "competitor_snapshots": (
        "store_code",
        "sku",
        "competitor_asin",
        "competitor_title",
        "captured_at",
        "source",
        "collection_method",
        "price",
        "currency",
        "review_count",
        "negative_review_hits",
    ),
}


def read_table(content: str | bytes, content_type: str) -> list[dict[str, str]]:
    if isinstance(content, bytes):
        if len(content) > MAX_BYTES:
            raise CommerceOpsError("import payload is too large", code="import_too_large", status_code=413)
        text = content.decode("utf-8-sig")
    else:
        text = content
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise CommerceOpsError("import payload is too large", code="import_too_large", status_code=413)
    if "application/json" in content_type:
        return _read_json(text)
    return _read_csv(text)


def _read_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ImportValidationError([{"row": 0, "field": "*", "message": "missing header"}])
    rows: list[dict[str, str]] = []
    for raw in reader:
        rows.append({(key or "").strip().lower(): (value or "").strip() for key, value in raw.items()})
    return rows


def _stringify(value: object, row_number: int, field: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool) or isinstance(value, float):
        raise ImportValidationError(
            [
                {
                    "row": row_number,
                    "field": field,
                    "message": "JSON numbers must be integers or decimal strings, not floats or bools",
                }
            ]
        )
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    raise ImportValidationError(
        [{"row": row_number, "field": field, "message": "unsupported JSON value"}]
    )


def _read_json(text: str) -> list[dict[str, str]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImportValidationError([{"row": 0, "field": "*", "message": "invalid JSON"}]) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise ImportValidationError([{"row": 0, "field": "rows", "message": "expected an object with rows"}])
    rows: list[dict[str, str]] = []
    for index, item in enumerate(payload["rows"], start=1):
        if not isinstance(item, dict):
            raise ImportValidationError([{"row": index, "field": "*", "message": "row must be an object"}])
        rows.append({str(key).strip().lower(): _stringify(value, index, str(key)) for key, value in item.items()})
    return rows


class _RowErrors:
    def __init__(self) -> None:
        self._errors: list[dict] = []

    def add(self, row_number: int, field: str, message: str) -> None:
        self._errors.append({"row": row_number, "field": field, "message": message})

    def raise_if_any(self) -> None:
        if self._errors:
            raise ImportValidationError(self._errors)


def _require_columns(dataset: str, rows: list[dict[str, str]], errors: _RowErrors) -> None:
    if not rows:
        errors.add(0, "*", "no data rows")
        return
    fields = set(rows[0])
    for column in REQUIRED[dataset]:
        if column not in fields:
            errors.add(0, column, "missing column")


def _text(row: dict[str, str], field: str, row_number: int, errors: _RowErrors) -> str:
    value = row.get(field, "").strip()
    if not value:
        errors.add(row_number, field, "required")
    return value


def _integer(
    row: dict[str, str],
    field: str,
    row_number: int,
    errors: _RowErrors,
    *,
    minimum: int,
) -> int:
    raw = row.get(field, "").strip()
    if not _INT.fullmatch(raw):
        errors.add(row_number, field, f"integer >= {minimum} required")
        return 0
    value = int(raw)
    if value < minimum:
        errors.add(row_number, field, f"integer >= {minimum} required")
    return value


def _decimal(
    row: dict[str, str],
    field: str,
    row_number: int,
    errors: _RowErrors,
    *,
    minimum: Decimal = Decimal(0),
    maximum: Decimal | None = None,
    required: bool = True,
) -> Decimal | None:
    raw = row.get(field, "").strip()
    if not raw:
        if required:
            errors.add(row_number, field, "required")
        return None
    try:
        value = D(raw)
    except Exception:
        errors.add(row_number, field, "invalid decimal")
        return None
    if value < minimum:
        errors.add(row_number, field, f"must be >= {minimum}")
    if maximum is not None and value > maximum:
        errors.add(row_number, field, f"must be <= {maximum}")
    return value


def _day(row: dict[str, str], field: str, row_number: int, errors: _RowErrors, *, required: bool = True) -> date | None:
    raw = row.get(field, "").strip()
    if not raw:
        if required:
            errors.add(row_number, field, "required")
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        errors.add(row_number, field, "expected YYYY-MM-DD")
        return None


def _store(session: Session, code: str) -> Store | None:
    return session.scalar(select(Store).where(Store.code == code))


def _product(session: Session, store: Store, sku: str) -> Product | None:
    return session.scalar(select(Product).where(Product.store_id == store.id, Product.sku == sku))


def _ensure_product_stub(session: Session, store: Store, sku: str, unit_cogs: Decimal) -> Product:
    existing = _product(session, store, sku)
    if existing is not None:
        return existing
    product = Product(
        id=f"{store.id}:{sku}",
        store_id=store.id,
        sku=sku,
        asin="",
        title=sku,
        list_price=Decimal(0),
        unit_cogs=unit_cogs,
        bullet_points="",
        currency=store.currency,
    )
    session.add(product)
    session.flush()
    return product


def import_rows(session: Session, dataset: str, rows: list[dict[str, str]]) -> dict:
    if dataset not in DATASETS:
        raise CommerceOpsError(f"unknown dataset: {dataset}", code="unknown_dataset", status_code=404)
    if len(rows) > MAX_ROWS:
        raise CommerceOpsError("too many rows", code="import_too_large", status_code=413)
    errors = _RowErrors()
    _require_columns(dataset, rows, errors)
    errors.raise_if_any()
    parsed = [_PARSERS[dataset](session, row, index, errors) for index, row in enumerate(rows, start=1)]
    errors.raise_if_any()
    inserted = 0
    updated = 0
    for item in parsed:
        kind = _WRITERS[dataset](session, item)
        if kind == "inserted":
            inserted += 1
        else:
            updated += 1
    session.commit()
    return {"dataset": dataset, "rows": len(parsed), "inserted": inserted, "updated": updated}


def _money_fields(row, number, errors, fields: tuple[str, ...]) -> dict[str, Decimal]:
    return {field: _decimal(row, field, number, errors) or Decimal(0) for field in fields}


def _parse_order(session: Session, row: dict[str, str], number: int, errors: _RowErrors) -> dict:
    store = _checked_store(session, row, number, errors)
    sku = _text(row, "sku", number, errors)
    quantity = _integer(row, "quantity", number, errors, minimum=1)
    money = _money_fields(
        row,
        number,
        errors,
        ("gross_revenue", "discount", "unit_cogs", "platform_fee", "shipping_fee", "other_fee"),
    )
    ordered_at = _day(row, "ordered_at", number, errors)
    currency = _currency(row, number, errors, store)
    return {
        "store": store,
        "sku": sku,
        "external_order_id": _text(row, "external_order_id", number, errors),
        "line_id": _text(row, "line_id", number, errors),
        "ordered_at": ordered_at,
        "quantity": quantity,
        "currency": currency,
        **money,
    }


def _parse_refund(session: Session, row: dict[str, str], number: int, errors: _RowErrors) -> dict:
    store = _checked_store(session, row, number, errors)
    amount = _decimal(row, "amount", number, errors) or Decimal(0)
    recovered = _decimal(row, "recovered_cogs", number, errors) or Decimal(0)
    quantity = _integer(row, "quantity", number, errors, minimum=0)
    if amount == 0 and recovered == 0 and quantity == 0:
        errors.add(number, "amount", "empty refund")
    return {
        "store": store,
        "sku": _text(row, "sku", number, errors),
        "external_refund_id": _text(row, "external_refund_id", number, errors),
        "order_external_id": row.get("order_external_id", "").strip(),
        "refunded_at": _day(row, "refunded_at", number, errors),
        "quantity": quantity,
        "amount": amount,
        "recovered_cogs": recovered,
        "currency": _currency(row, number, errors, store),
    }


def _parse_ad(session: Session, row: dict[str, str], number: int, errors: _RowErrors) -> dict:
    store = _checked_store(session, row, number, errors)
    impressions = _integer(row, "impressions", number, errors, minimum=0)
    clicks = _integer(row, "clicks", number, errors, minimum=0)
    if clicks > impressions:
        errors.add(number, "clicks", "clicks cannot exceed impressions")
    return {
        "store": store,
        "sku": _text(row, "sku", number, errors),
        "campaign_external_id": _text(row, "campaign_external_id", number, errors),
        "campaign_name": _text(row, "campaign_name", number, errors),
        "daily_budget": _decimal(row, "daily_budget", number, errors) or Decimal(0),
        "metric_date": _day(row, "metric_date", number, errors),
        "impressions": impressions,
        "clicks": clicks,
        "spend": _decimal(row, "spend", number, errors) or Decimal(0),
        "attributed_sales": _decimal(row, "attributed_sales", number, errors) or Decimal(0),
        "attributed_orders": _integer(row, "attributed_orders", number, errors, minimum=0),
        "currency": _currency(row, number, errors, store),
    }


def _parse_inventory(session: Session, row: dict[str, str], number: int, errors: _RowErrors) -> dict:
    store = _checked_store(session, row, number, errors)
    lead = _integer(row, "planning_lead_time_days", number, errors, minimum=1)
    return {
        "store": store,
        "sku": _text(row, "sku", number, errors),
        "snapshot_date": _day(row, "snapshot_date", number, errors),
        "on_hand": _integer(row, "on_hand", number, errors, minimum=0),
        "reserved": _integer(row, "reserved", number, errors, minimum=0),
        "inbound_qty": _integer(row, "inbound_qty", number, errors, minimum=0),
        "inbound_eta": _day(row, "inbound_eta", number, errors, required=False),
        "safety_stock": _integer(row, "safety_stock", number, errors, minimum=0),
        "target_cover_days": _integer(row, "target_cover_days", number, errors, minimum=0),
        "planning_lead_time_days": lead,
    }


def _parse_quote(session: Session, row: dict[str, str], number: int, errors: _RowErrors) -> dict:
    del session
    rate = _decimal(row, "on_time_rate", number, errors, maximum=Decimal(1), required=False)
    return {
        "supplier_code": _text(row, "supplier_code", number, errors),
        "supplier_name": _text(row, "supplier_name", number, errors),
        "supplier_country": row.get("supplier_country", "").strip(),
        "sku": _text(row, "sku", number, errors),
        "tier_min_qty": _integer(row, "tier_min_qty", number, errors, minimum=1),
        "unit_price": _decimal(row, "unit_price", number, errors) or Decimal(0),
        "currency": _text(row, "currency", number, errors).upper(),
        "moq": _integer(row, "moq", number, errors, minimum=1),
        "lead_time_days": _integer(row, "lead_time_days", number, errors, minimum=1),
        "order_multiple": _integer(row, "order_multiple", number, errors, minimum=1),
        "freight_per_unit": _decimal(row, "freight_per_unit", number, errors) or Decimal(0),
        "duty_rate": _decimal(row, "duty_rate", number, errors, maximum=Decimal(1)) or Decimal(0),
        "on_time_rate": rate,
        "on_time_sample_size": _integer(row, "on_time_sample_size", number, errors, minimum=0),
    }


def _parse_competitor(session: Session, row: dict[str, str], number: int, errors: _RowErrors) -> dict:
    store = _checked_store(session, row, number, errors)
    method = _text(row, "collection_method", number, errors)
    source = _text(row, "source", number, errors)
    if method and method not in COLLECTION_METHODS:
        errors.add(number, "collection_method", "collection method is not allowed")
    if "scrape" in source.lower() or "scrape" in method.lower():
        errors.add(number, "source", "scraped origins are rejected")
    captured = _text(row, "captured_at", number, errors)
    if captured and not _CAPTURED_AT.fullmatch(captured):
        errors.add(number, "captured_at", "expected YYYY-MM-DDTHH:MM:SSZ")
    bsr_raw = row.get("bsr", "").strip()
    bsr: int | None = None
    if bsr_raw:
        if not _INT.fullmatch(bsr_raw) or int(bsr_raw) < 1:
            errors.add(number, "bsr", "integer >= 1 or empty")
        else:
            bsr = int(bsr_raw)
    return {
        "store": store,
        "sku": _text(row, "sku", number, errors),
        "competitor_asin": _text(row, "competitor_asin", number, errors),
        "competitor_title": _text(row, "competitor_title", number, errors),
        "captured_at": captured,
        "source": source,
        "collection_method": method,
        "price": _decimal(row, "price", number, errors) or Decimal(0),
        "currency": _currency(row, number, errors, store),
        "bsr": bsr,
        "rating": _decimal(row, "rating", number, errors, maximum=Decimal(5), required=False),
        "review_count": _integer(row, "review_count", number, errors, minimum=0),
        "negative_review_hits": _integer(row, "negative_review_hits", number, errors, minimum=0),
        "negative_keywords": row.get("negative_keywords", "").strip(),
        "bullet_points": row.get("bullet_points", "").strip(),
    }


def _checked_store(session: Session, row: dict[str, str], number: int, errors: _RowErrors) -> Store | None:
    code = _text(row, "store_code", number, errors)
    if not code:
        return None
    store = _store(session, code)
    if store is None:
        errors.add(number, "store_code", "unknown store")
    return store


def _currency(row: dict[str, str], number: int, errors: _RowErrors, store: Store | None) -> str:
    currency = _text(row, "currency", number, errors).upper()
    if store is not None and currency and currency != store.currency:
        errors.add(number, "currency", f"expected {store.currency}")
    return currency


def _require_known_product(session: Session, store: Store | None, sku: str, number: int, errors: _RowErrors) -> Product | None:
    if store is None or not sku:
        return None
    product = _product(session, store, sku)
    if product is None:
        errors.add(number, "sku", "unknown sku")
    return product


def _write_order(session: Session, item: dict) -> str:
    store: Store = item["store"]
    product = _ensure_product_stub(session, store, item["sku"], item["unit_cogs"])
    identity = f"{store.id}:{item['external_order_id']}:{item['line_id']}"
    existing = session.get(Order, identity)
    values = dict(
        store_id=store.id,
        product_id=product.id,
        external_order_id=item["external_order_id"],
        line_id=item["line_id"],
        ordered_at=item["ordered_at"],
        quantity=item["quantity"],
        gross_revenue=item["gross_revenue"],
        discount=item["discount"],
        unit_cogs=item["unit_cogs"],
        platform_fee=item["platform_fee"],
        shipping_fee=item["shipping_fee"],
        other_fee=item["other_fee"],
        currency=item["currency"],
    )
    return _save(session, existing, Order, identity, values)


def _write_refund(session: Session, item: dict) -> str:
    store: Store = item["store"]
    product = _product(session, store, item["sku"])
    if product is None:
        raise CommerceOpsError("unknown sku on write", code="import_invalid", status_code=422)
    identity = f"{store.id}:{item['external_refund_id']}"
    existing = session.get(Refund, identity)
    values = dict(
        store_id=store.id,
        product_id=product.id,
        external_refund_id=item["external_refund_id"],
        order_external_id=item["order_external_id"],
        refunded_at=item["refunded_at"],
        quantity=item["quantity"],
        amount=item["amount"],
        recovered_cogs=item["recovered_cogs"],
        currency=item["currency"],
    )
    return _save(session, existing, Refund, identity, values)


def _write_ad(session: Session, item: dict) -> str:
    store: Store = item["store"]
    product = _product(session, store, item["sku"])
    if product is None:
        raise CommerceOpsError("unknown sku on write", code="import_invalid", status_code=422)
    campaign_id = f"{store.id}:{item['campaign_external_id']}"
    campaign = session.get(AdCampaign, campaign_id)
    if campaign is None:
        campaign = AdCampaign(
            id=campaign_id,
            store_id=store.id,
            product_id=product.id,
            external_id=item["campaign_external_id"],
            name=item["campaign_name"],
            daily_budget=item["daily_budget"],
            currency=item["currency"],
        )
        session.add(campaign)
    else:
        campaign.name = item["campaign_name"]
        campaign.product_id = product.id
        campaign.daily_budget = item["daily_budget"]
        campaign.currency = item["currency"]
    session.flush()
    metric_id = f"{campaign.id}:{item['metric_date'].isoformat()}"
    existing = session.get(AdMetricDay, metric_id)
    values = dict(
        campaign_id=campaign.id,
        metric_date=item["metric_date"],
        impressions=item["impressions"],
        clicks=item["clicks"],
        spend=item["spend"],
        attributed_sales=item["attributed_sales"],
        attributed_orders=item["attributed_orders"],
    )
    return _save(session, existing, AdMetricDay, metric_id, values)


def _write_inventory(session: Session, item: dict) -> str:
    store: Store = item["store"]
    product = _product(session, store, item["sku"])
    if product is None:
        raise CommerceOpsError("unknown sku on write", code="import_invalid", status_code=422)
    identity = f"{product.id}:{item['snapshot_date'].isoformat()}"
    existing = session.get(InventorySnapshot, identity)
    values = dict(
        store_id=store.id,
        product_id=product.id,
        snapshot_date=item["snapshot_date"],
        on_hand=item["on_hand"],
        reserved=item["reserved"],
        inbound_qty=item["inbound_qty"],
        inbound_eta=item["inbound_eta"],
        safety_stock=item["safety_stock"],
        target_cover_days=item["target_cover_days"],
        planning_lead_time_days=item["planning_lead_time_days"],
    )
    return _save(session, existing, InventorySnapshot, identity, values)


def _write_quote(session: Session, item: dict) -> str:
    supplier = session.get(Supplier, item["supplier_code"])
    if supplier is None:
        supplier = Supplier(
            id=item["supplier_code"],
            code=item["supplier_code"],
            name=item["supplier_name"],
            country=item["supplier_country"],
            currency=item["currency"],
        )
        session.add(supplier)
        session.flush()
    else:
        supplier.name = item["supplier_name"]
        supplier.country = item["supplier_country"]
        supplier.currency = item["currency"]
    identity = f"{supplier.id}:{item['sku']}:{item['tier_min_qty']}"
    existing = session.get(SupplierQuote, identity)
    values = dict(
        supplier_id=supplier.id,
        sku=item["sku"],
        tier_min_qty=item["tier_min_qty"],
        unit_price=item["unit_price"],
        currency=item["currency"],
        moq=item["moq"],
        lead_time_days=item["lead_time_days"],
        order_multiple=item["order_multiple"],
        freight_per_unit=item["freight_per_unit"],
        duty_rate=item["duty_rate"],
        on_time_rate=item["on_time_rate"],
        on_time_sample_size=item["on_time_sample_size"],
    )
    return _save(session, existing, SupplierQuote, identity, values)


def _write_competitor(session: Session, item: dict) -> str:
    store: Store = item["store"]
    product = _product(session, store, item["sku"])
    if product is None:
        raise CommerceOpsError("unknown sku on write", code="import_invalid", status_code=422)
    identity = f"{product.id}:{item['competitor_asin']}:{item['captured_at']}"
    existing = session.get(CompetitorSnapshot, identity)
    values = dict(
        store_id=store.id,
        product_id=product.id,
        competitor_asin=item["competitor_asin"],
        competitor_title=item["competitor_title"],
        captured_at=item["captured_at"],
        source=item["source"],
        collection_method=item["collection_method"],
        price=item["price"],
        currency=item["currency"],
        bsr=item["bsr"],
        rating=item["rating"],
        review_count=item["review_count"],
        negative_review_hits=item["negative_review_hits"],
        negative_keywords=item["negative_keywords"],
        bullet_points=item["bullet_points"],
    )
    return _save(session, existing, CompetitorSnapshot, identity, values)


def _save(session: Session, existing: object, model: type, identity: str, values: dict) -> str:
    if existing is None:
        session.add(model(id=identity, **values))
        session.flush()
        return "inserted"
    for key, value in values.items():
        setattr(existing, key, value)
    return "updated"


def _guard_known(parser):  # type: ignore[no-untyped-def]
    def wrapped(session: Session, row: dict[str, str], number: int, errors: _RowErrors) -> dict:
        item = parser(session, row, number, errors)
        if parser in {_parse_refund, _parse_ad, _parse_inventory, _parse_competitor}:
            _require_known_product(session, item.get("store"), item.get("sku", ""), number, errors)
        return item

    return wrapped


_PARSERS = {
    "orders": _parse_order,
    "refunds": _guard_known(_parse_refund),
    "ad_metrics": _guard_known(_parse_ad),
    "inventory": _guard_known(_parse_inventory),
    "supplier_quotes": _parse_quote,
    "competitor_snapshots": _guard_known(_parse_competitor),
}
_WRITERS = {
    "orders": _write_order,
    "refunds": _write_refund,
    "ad_metrics": _write_ad,
    "inventory": _write_inventory,
    "supplier_quotes": _write_quote,
    "competitor_snapshots": _write_competitor,
}
