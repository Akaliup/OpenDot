"""Deterministic demo data with the five interview anomalies.

The as-of date is 2026-03-15. The current window is 2026-03-08 through
2026-03-14. The previous window is 2026-03-01 through 2026-03-07.

US store, those windows, after this seed:

- previous net profit 1371.90, current net profit 682.60, bridge -689.30
- the two largest drags are ad spend (-392.00) and refunds (-300.00)
- Bottle Exact, Bottle Broad, and Lamp Exact are high-ACOS or declining-CVR
- NS-CABLE-3PK and NS-LAMP-LED cover fewer than 14 days
- cable quotes rank SUP-SZR, then SUP-VNF, then SUP-NBV
- competitor B0COMP001 drops price, jumps BSR, and spikes complaint hits

Re-running the seed upserts the same natural keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from commerceops.config import get_settings
from commerceops.context import DEMO_WORKSPACE, bind_workspace, current_workspace, reset_workspace
from commerceops.errors import CommerceOpsError
from commerceops.csv_import import import_rows
from commerceops.db import session_factory_for
from commerceops.models import (
    AdCampaign,
    AdMetricDay,
    CompetitorSnapshot,
    InventorySnapshot,
    Order,
    Product,
    Refund,
    SopDocument,
    Store,
    Supplier,
    SupplierQuote,
)
from commerceops.serialize import to_jsonable
from commerceops.sop.retrieval import load_package_documents

AS_OF = date(2026, 3, 15)
CURRENT_START = date(2026, 3, 8)
CURRENT_END = date(2026, 3, 14)
PREVIOUS_START = date(2026, 3, 1)
PREVIOUS_END = date(2026, 3, 7)
US_STORE = "us-main"
UK_STORE = "uk-main"
HORIZON_DAYS = 14
LOOKBACK_DAYS = 14


@dataclass(frozen=True)
class DaySale:
    sku: str
    quantity: int
    gross: str
    discount: str
    unit_cogs: str
    platform: str
    shipping: str
    other: str


@dataclass(frozen=True)
class DayAd:
    external_id: str
    impressions: int
    clicks: int
    spend: str
    sales: str
    orders: int


def _days(start: date, end: date) -> list[date]:
    cursor = start
    values: list[date] = []
    while cursor <= end:
        values.append(cursor)
        cursor += timedelta(days=1)
    return values


_US_PREV = (
    DaySale("NS-BOTTLE-1L", 10, "200.00", "10.00", "4.50", "30.00", "20.00", "0.00"),
    DaySale("NS-YOGA-MAT", 5, "150.00", "0.00", "6.00", "15.00", "10.00", "0.00"),
    DaySale("NS-CABLE-3PK", 4, "60.00", "0.00", "2.20", "9.00", "6.00", "0.00"),
    DaySale("NS-LAMP-LED", 2, "80.00", "0.00", "8.00", "12.00", "8.00", "0.00"),
)
_US_CURR = (
    DaySale("NS-BOTTLE-1L", 8, "160.00", "8.00", "4.50", "24.00", "16.00", "0.00"),
    DaySale("NS-YOGA-MAT", 5, "150.00", "0.00", "6.00", "15.00", "10.00", "0.00"),
    DaySale("NS-CABLE-3PK", 6, "90.00", "0.00", "2.20", "13.50", "9.00", "0.00"),
    DaySale("NS-LAMP-LED", 2, "80.00", "0.00", "8.00", "12.00", "8.00", "0.00"),
)
_UK = (DaySale("UK-MUG", 3, "45.00", "0.00", "4.00", "6.00", "5.00", "0.00"),)

_CAMPAIGNS = {
    "camp-bottle-exact": ("Bottle Exact Match", "NS-BOTTLE-1L", "45.00", US_STORE),
    "camp-bottle-broad": ("Bottle Broad Match", "NS-BOTTLE-1L", "50.00", US_STORE),
    "camp-yoga": ("Yoga Auto", "NS-YOGA-MAT", "15.00", US_STORE),
    "camp-lamp": ("Lamp Exact Match", "NS-LAMP-LED", "18.00", US_STORE),
    "camp-uk-mug": ("UK Mug Auto", "UK-MUG", "4.00", UK_STORE),
}
_ADS_PREV = (
    DayAd("camp-bottle-exact", 1000, 50, "20.00", "100.00", 5),
    DayAd("camp-bottle-broad", 2000, 30, "25.00", "40.00", 1),
    DayAd("camp-yoga", 800, 40, "15.00", "90.00", 3),
    DayAd("camp-lamp", 500, 25, "12.00", "80.00", 2),
    DayAd("camp-uk-mug", 200, 10, "4.00", "20.00", 1),
)
_ADS_CURR = (
    DayAd("camp-bottle-exact", 1200, 40, "45.00", "60.00", 2),
    DayAd("camp-bottle-broad", 2200, 40, "50.00", "15.00", 1),
    DayAd("camp-yoga", 800, 40, "15.00", "90.00", 3),
    DayAd("camp-lamp", 600, 30, "18.00", "40.00", 1),
    DayAd("camp-uk-mug", 200, 10, "4.00", "20.00", 1),
)


def _order_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    plan = (
        (US_STORE, "USD", _days(PREVIOUS_START, PREVIOUS_END), _US_PREV),
        (US_STORE, "USD", _days(CURRENT_START, CURRENT_END), _US_CURR),
        (UK_STORE, "GBP", _days(PREVIOUS_START, PREVIOUS_END), _UK),
        (UK_STORE, "GBP", _days(CURRENT_START, CURRENT_END), _UK),
    )
    for store, currency, days, specs in plan:
        for day in days:
            for spec in specs:
                rows.append(
                    {
                        "store_code": store,
                        "external_order_id": f"{spec.sku}-{day.isoformat()}",
                        "line_id": "1",
                        "sku": spec.sku,
                        "ordered_at": day.isoformat(),
                        "quantity": str(spec.quantity),
                        "gross_revenue": spec.gross,
                        "discount": spec.discount,
                        "unit_cogs": spec.unit_cogs,
                        "platform_fee": spec.platform,
                        "shipping_fee": spec.shipping,
                        "other_fee": spec.other,
                        "currency": currency,
                    }
                )
    return rows


def _refund_rows() -> list[dict[str, str]]:
    specs = (
        ("rf-bottle-prev-1", "2026-03-03", "1", "20.00", "4.50"),
        ("rf-bottle-curr-1", "2026-03-10", "4", "80.00", "9.00"),
        ("rf-bottle-curr-2", "2026-03-12", "6", "120.00", "0.00"),
        ("rf-bottle-curr-3", "2026-03-13", "6", "120.00", "4.50"),
    )
    return [
        {
            "store_code": US_STORE,
            "external_refund_id": refund_id,
            "sku": "NS-BOTTLE-1L",
            "refunded_at": when,
            "quantity": quantity,
            "amount": amount,
            "recovered_cogs": recovered,
            "currency": "USD",
            "order_external_id": "",
        }
        for refund_id, when, quantity, amount, recovered in specs
    ]


def _ad_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    plan = (
        (_days(PREVIOUS_START, PREVIOUS_END), _ADS_PREV),
        (_days(CURRENT_START, CURRENT_END), _ADS_CURR),
    )
    for days, specs in plan:
        for day in days:
            for spec in specs:
                name, sku, budget, store = _CAMPAIGNS[spec.external_id]
                rows.append(
                    {
                        "store_code": store,
                        "campaign_external_id": spec.external_id,
                        "campaign_name": name,
                        "sku": sku,
                        "daily_budget": budget,
                        "metric_date": day.isoformat(),
                        "impressions": str(spec.impressions),
                        "clicks": str(spec.clicks),
                        "spend": spec.spend,
                        "attributed_sales": spec.sales,
                        "attributed_orders": str(spec.orders),
                        "currency": "USD" if store == US_STORE else "GBP",
                    }
                )
    return rows


def _inventory_rows() -> list[dict[str, str]]:
    specs = (
        (US_STORE, "NS-BOTTLE-1L", "200", "10", "40", "2026-03-20", "20", "21", "15"),
        (US_STORE, "NS-YOGA-MAT", "160", "10", "20", "2026-03-25", "10", "21", "10"),
        (US_STORE, "NS-CABLE-3PK", "20", "2", "10", "2026-03-30", "15", "30", "12"),
        (US_STORE, "NS-LAMP-LED", "12", "0", "0", "", "8", "21", "18"),
        (UK_STORE, "UK-MUG", "100", "0", "0", "", "12", "21", "14"),
    )
    rows = []
    for store, sku, on_hand, reserved, inbound, eta, safety, target, lead in specs:
        rows.append(
            {
                "store_code": store,
                "sku": sku,
                "snapshot_date": AS_OF.isoformat(),
                "on_hand": on_hand,
                "reserved": reserved,
                "inbound_qty": inbound,
                "inbound_eta": eta,
                "safety_stock": safety,
                "target_cover_days": target,
                "planning_lead_time_days": lead,
            }
        )
    return rows


def _quote_rows() -> list[dict[str, str]]:
    specs = (
        ("SUP-SZR", "Shenzhen Rapid", "CN", "NS-CABLE-3PK", "1", "2.40", "100", "12", "10", "0.30", "0.05", "0.96", "40"),
        ("SUP-SZR", "Shenzhen Rapid", "CN", "NS-CABLE-3PK", "500", "2.10", "100", "12", "10", "0.20", "0.05", "0.96", "40"),
        ("SUP-NBV", "Ningbo Value", "CN", "NS-CABLE-3PK", "1", "1.90", "300", "28", "50", "0.45", "0.08", "0.81", "12"),
        ("SUP-VNF", "Vietnam Flex", "VN", "NS-CABLE-3PK", "1", "2.20", "150", "20", "10", "0.35", "0.04", "0.90", "25"),
        ("SUP-SZR", "Shenzhen Rapid", "CN", "NS-LAMP-LED", "1", "7.40", "50", "16", "10", "0.80", "0.05", "0.96", "40"),
        ("SUP-NBV", "Ningbo Value", "CN", "NS-LAMP-LED", "1", "6.90", "200", "30", "20", "1.10", "0.08", "0.81", "12"),
    )
    rows = []
    for code, name, country, sku, tier, price, moq, lead, multiple, freight, duty, rate, sample in specs:
        rows.append(
            {
                "supplier_code": code,
                "supplier_name": name,
                "supplier_country": country,
                "sku": sku,
                "tier_min_qty": tier,
                "unit_price": price,
                "currency": "USD",
                "moq": moq,
                "lead_time_days": lead,
                "order_multiple": multiple,
                "freight_per_unit": freight,
                "duty_rate": duty,
                "on_time_rate": rate,
                "on_time_sample_size": sample,
            }
        )
    return rows


def _competitor_rows() -> list[dict[str, str]]:
    older = "2026-03-01T00:00:00Z"
    newer = "2026-03-14T00:00:00Z"
    series = (
        ("B0COMP001", "Lumina Lamp", "42.00", "36.00", "1200", "400", "4.6", "4.5", "800", "860", "4", "18", "cord length", "flicker, dead on arrival, adapter heat"),
        ("B0COMP002", "Harbor Lamp", "41.00", "41.00", "2000", "1900", "4.4", "4.4", "210", "220", "3", "3", "brightness", "brightness"),
        ("B0COMP003", "North Glow", "39.00", "39.50", "800", "1100", "4.7", "4.2", "540", "560", "2", "5", "warm light", "warm light, dim"),
        ("B0COMP004", "Desk Arc", "45.00", "44.00", "3000", "3100", "4.1", "4.1", "90", "92", "6", "6", "heavy base", "heavy base"),
        ("B0COMP005", "Pico Lamp", "38.00", "37.00", "1500", "1400", "4.3", "4.3", "330", "340", "1", "2", "usb", "usb"),
    )
    rows: list[dict[str, str]] = []
    for asin, title, old_price, new_price, old_bsr, new_bsr, old_rating, new_rating, old_reviews, new_reviews, old_hits, new_hits, old_words, new_words in series:
        for captured, price, bsr, rating, reviews, hits, words in (
            (older, old_price, old_bsr, old_rating, old_reviews, old_hits, old_words),
            (newer, new_price, new_bsr, new_rating, new_reviews, new_hits, new_words),
        ):
            rows.append(
                {
                    "store_code": US_STORE,
                    "sku": "NS-LAMP-LED",
                    "competitor_asin": asin,
                    "competitor_title": title,
                    "captured_at": captured,
                    "source": "demo_seed",
                    "collection_method": "demo_seed",
                    "price": price,
                    "currency": "USD",
                    "bsr": bsr,
                    "rating": rating,
                    "review_count": reviews,
                    "negative_review_hits": hits,
                    "negative_keywords": words,
                    "bullet_points": "touch dimmer; usb-c",
                }
            )
    return rows


def _upsert_store(session: Session, workspace_id: str, code: str, name: str, marketplace: str, currency: str, timezone: str) -> None:
    identity = f"{workspace_id}:{code}"
    store = session.get(Store, identity)
    values = dict(
        workspace_id=workspace_id,
        code=code,
        name=name,
        marketplace=marketplace,
        currency=currency,
        timezone=timezone,
    )
    if store is None:
        session.add(Store(id=identity, **values))
        return
    for key, value in values.items():
        setattr(store, key, value)


def _upsert_product(
    session: Session,
    workspace_id: str,
    store_code: str,
    sku: str,
    asin: str,
    title: str,
    list_price: str,
    unit_cogs: str,
    bullets: str,
    currency: str,
) -> None:
    store_id = f"{workspace_id}:{store_code}"
    identity = f"{store_id}:{sku}"
    product = session.get(Product, identity)
    values = dict(
        workspace_id=workspace_id,
        store_id=store_id,
        sku=sku,
        asin=asin,
        title=title,
        list_price=Decimal(list_price),
        unit_cogs=Decimal(unit_cogs),
        bullet_points=bullets,
        currency=currency,
    )
    if product is None:
        session.add(Product(id=identity, **values))
        return
    for key, value in values.items():
        setattr(product, key, value)


def _seed_sops(session: Session) -> None:
    for document in load_package_documents():
        body = Path(document.path).read_text(encoding="utf-8")
        existing = session.get(SopDocument, document.doc_id)
        if existing is None:
            session.add(
                SopDocument(
                    id=document.doc_id,
                    title=document.title,
                    version=document.version,
                    body_markdown=body,
                    source_sha256=document.sha256,
                )
            )
            continue
        existing.title = document.title
        existing.version = document.version
        existing.body_markdown = body
        existing.source_sha256 = document.sha256


def seed_demo_data(session: Session, workspace_id: str | None = None) -> dict[str, int]:
    if workspace_id:
        workspace = workspace_id
    else:
        try:
            workspace = current_workspace()
        except CommerceOpsError:
            workspace = os.environ.get("COMMERCEOPS_WORKSPACE_ID", DEMO_WORKSPACE)
    token = bind_workspace(workspace)
    try:
        return _seed_demo_data(session, workspace)
    finally:
        reset_workspace(token)


def _seed_demo_data(session: Session, workspace: str) -> dict[str, int]:
    _upsert_store(session, workspace, US_STORE, "Northstar US", "amazon_us", "USD", "America/New_York")
    _upsert_store(session, workspace, UK_STORE, "Northstar UK", "amazon_uk", "GBP", "Europe/London")
    _upsert_product(session, workspace, US_STORE, "NS-BOTTLE-1L", "B0BOTTLE1L", "Northstar Insulated Bottle 1L", "20.00", "4.50", "Double wall; leakproof lid.", "USD")
    _upsert_product(session, workspace, US_STORE, "NS-YOGA-MAT", "B0YOGAMAT1", "Northstar Travel Yoga Mat", "30.00", "6.00", "Closed-cell; carry strap.", "USD")
    _upsert_product(session, workspace, US_STORE, "NS-CABLE-3PK", "B0CABLE3PK", "Northstar Cable 3-Pack", "15.00", "2.20", "Braided; 1m 2m 3m.", "USD")
    _upsert_product(session, workspace, US_STORE, "NS-LAMP-LED", "B0LAMPLED1", "Northstar LED Desk Lamp", "40.00", "8.00", "Touch dimmer; USB-C.", "USD")
    _upsert_product(session, workspace, UK_STORE, "UK-MUG", "B0UKMUG001", "Northstar Stack Mug", "15.00", "4.00", "Stoneware; dishwasher safe.", "GBP")
    session.commit()
    import_rows(session, "orders", _order_rows())
    import_rows(session, "refunds", _refund_rows())
    import_rows(session, "ad_metrics", _ad_rows())
    import_rows(session, "inventory", _inventory_rows())
    import_rows(session, "supplier_quotes", _quote_rows())
    import_rows(session, "competitor_snapshots", _competitor_rows())
    _seed_sops(session)
    session.commit()
    return summarize(session)


def summarize(session: Session) -> dict[str, int]:
    models = {
        "stores": Store,
        "products": Product,
        "orders": Order,
        "refunds": Refund,
        "ad_campaigns": AdCampaign,
        "ad_metric_days": AdMetricDay,
        "inventory_snapshots": InventorySnapshot,
        "suppliers": Supplier,
        "supplier_quotes": SupplierQuote,
        "competitor_snapshots": CompetitorSnapshot,
        "sop_documents": SopDocument,
    }
    return {
        name: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for name, model in models.items()
    }


def main() -> None:
    from commerceops.reporting import profit_report

    session = session_factory_for(get_settings().database_url)()
    try:
        counts = seed_demo_data(session, os.environ.get("COMMERCEOPS_WORKSPACE_ID", DEMO_WORKSPACE))
        report = profit_report(session, US_STORE, CURRENT_START, CURRENT_END, compare=True)
        print(
            json.dumps(
                {
                    "counts": counts,
                    "us_current_net_profit": to_jsonable(report["current"].net_profit),
                    "us_previous_net_profit": to_jsonable(report["previous"].net_profit),
                },
                indent=2,
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
