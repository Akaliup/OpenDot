from decimal import Decimal

from sqlalchemy import func, select

from commerceops.csv_import import import_rows, read_table
from commerceops.engines.money import money_str
from commerceops.errors import ImportValidationError
from commerceops.models import AdCampaign, Order, PurchaseOrder, WritebackAuditLog
from commerceops.reporting import (
    ads_report,
    competitor_report,
    inventory_report,
    profit_report,
    supplier_report,
)
from commerceops.seed import (
    AS_OF,
    CURRENT_END,
    CURRENT_START,
    US_STORE,
    UK_STORE,
    seed_demo_data,
    summarize,
)

_ORDER_HEADER = "store_code,external_order_id,line_id,sku,ordered_at,quantity,gross_revenue,discount,unit_cogs,platform_fee,shipping_fee,other_fee,currency"


def test_seed_counts_and_second_run_are_stable(seeded):
    first = summarize(seeded)
    assert first == {
        "stores": 2,
        "products": 5,
        "orders": 70,
        "refunds": 4,
        "ad_campaigns": 5,
        "ad_metric_days": 70,
        "inventory_snapshots": 5,
        "suppliers": 3,
        "supplier_quotes": 6,
        "competitor_snapshots": 10,
        "sop_documents": 4,
    }
    seed_demo_data(seeded)
    assert summarize(seeded) == first


def test_seeded_profit_bridge_matches_the_hand_calculation(seeded):
    report = profit_report(seeded, US_STORE, CURRENT_START, CURRENT_END, compare=True)
    assert report["current"].net_profit == Decimal("682.60")
    assert report["previous"].net_profit == Decimal("1371.90")
    assert report["current"].refunds == Decimal("320")
    assert report["previous"].refunds == Decimal("20")
    assert report["current"].ad_spend == Decimal("896")
    assert report["previous"].ad_spend == Decimal("504")
    assert report["current"].recovered_cogs == Decimal("13.50")
    assert report["units_sold"] == 147
    assert report["bridge"].delta_net_profit == Decimal("-689.30")
    contributions = {item.code: item.contribution for item in report["bridge"].components}
    assert contributions == {
        "revenue": Decimal("-70"),
        "discounts": Decimal("14"),
        "refunds": Decimal("-300"),
        "net_cogs": Decimal("41.20"),
        "platform_fees": Decimal("10.50"),
        "shipping_fees": Decimal("7"),
        "ad_spend": Decimal("-392"),
        "other_fees": Decimal("0"),
    }
    assert sum(contributions.values(), Decimal(0)) == report["bridge"].delta_net_profit
    assert [item.code for item in report["drags"][:2]] == ["ad_spend", "refunds"]
    uk = profit_report(seeded, UK_STORE, CURRENT_START, CURRENT_END, compare=True)
    assert uk["currency"] == "GBP"
    assert uk["current"].net_profit == Decimal("126")
    assert uk["previous"].net_profit == Decimal("126")
    assert uk["bridge"].delta_net_profit == 0


def test_seeded_ads_inventory_suppliers_and_competitors(seeded):
    ads = ads_report(seeded, US_STORE, CURRENT_START, CURRENT_END)
    by_id = {row["campaign_external_id"]: row for row in ads["campaigns"]}
    exact = by_id["camp-bottle-exact"]
    assert exact["current"].acos.value == Decimal("0.75")
    assert exact["previous"].acos.value == Decimal("0.2")
    assert exact["current"].cvr.value == Decimal("0.05")
    assert exact["budget"].reason == "high_acos"
    assert exact["budget"].suggested_daily_budget == Decimal("31.50")
    assert "spend_up_cvr_down" in exact["flags"]
    assert by_id["camp-bottle-broad"]["budget"].reason == "severe_acos"
    assert by_id["camp-bottle-broad"]["budget"].suggested_daily_budget == Decimal("25.00")
    assert by_id["camp-yoga"]["budget"].reason == "no_adjustment"
    assert "spend_up_cvr_down" not in by_id["camp-yoga"]["flags"]
    assert ads["tacos"].value == Decimal("896") / Decimal("3304")

    inventory = inventory_report(seeded, US_STORE, AS_OF)
    assert inventory["at_risk_skus"] == ["NS-CABLE-3PK", "NS-LAMP-LED"]
    cable = next(row for row in inventory["skus"] if row["sku"] == "NS-CABLE-3PK")
    assert cable["cover"].days_of_cover == Decimal("3.6")
    assert cable["replenishment"].reorder_point == Decimal("75")
    assert cable["replenishment"].inbound_late is True

    suppliers = supplier_report(seeded, US_STORE, "NS-CABLE-3PK", AS_OF)
    ranked = suppliers["rank"].rankings
    assert [row.supplier_code for row in ranked] == ["SUP-SZR", "SUP-VNF", "SUP-NBV"]
    assert [row.adjusted_order_qty for row in ranked] == [200, 240, 300]
    assert [row.landed_cost for row in ranked] == [Decimal("2.82"), Decimal("2.638"), Decimal("2.502")]
    assert ranked[0].lead_time_risk == "arrives_after_stockout"
    for row in ranked:
        assert row.score == sum(suppliers["rank"].weights[key] * row.components[key] for key in suppliers["rank"].weights)

    competitors = competitor_report(seeded, US_STORE, "NS-LAMP-LED", AS_OF)
    assert competitors["sample_data"] is True
    assert competitors["data_origin"] == "imported_snapshots"
    by_asin = {row["competitor_asin"]: row for row in competitors["comparisons"]}
    assert by_asin["B0COMP001"]["alerts"] == ["price_drop", "bsr_jump", "complaint_spike"]
    assert by_asin["B0COMP001"]["source"] == "demo_seed"
    assert by_asin["B0COMP003"]["alerts"] == ["rating_drop"]
    assert money_str(by_asin["B0COMP001"]["price_change"]) == "-6.0000"


def test_csv_upsert_is_idempotent_and_validation_is_atomic(session, seeded):
    before = session.scalar(select(func.count()).select_from(Order))
    valid = (
        _ORDER_HEADER
        + "\nus-main,csv-1,1,NS-IMPORT,2026-03-02,2,30.00,1.00,4.00,2.00,1.00,0,USD\n"
    )
    first = import_rows(session, "orders", read_table(valid, "text/csv"))
    second = import_rows(session, "orders", read_table(valid, "text/csv"))
    assert first["inserted"] == 1 and first["updated"] == 0
    assert second["inserted"] == 0 and second["updated"] == 1
    changed = valid.replace("30.00", "32.50")
    import_rows(session, "orders", read_table(changed, "text/csv"))
    order = session.scalar(select(Order).where(Order.external_order_id == "csv-1"))
    assert order.gross_revenue == Decimal("32.50")
    assert session.scalar(select(func.count()).select_from(Order)) == before + 1

    invalid = (
        _ORDER_HEADER
        + "\nus-main,csv-bad,1,NS-IMPORT,2026-03-02,-1,10,0,1,1,1,0,USD"
        + "\nus-main,csv-good,1,NS-IMPORT,2026-03-02,1,10,0,1,1,1,0,USD\n"
    )
    try:
        import_rows(session, "orders", read_table(invalid, "text/csv"))
        raise AssertionError("invalid batch should fail")
    except ImportValidationError as exc:
        assert exc.errors[0]["field"] == "quantity"
    assert session.scalar(select(Order).where(Order.external_order_id == "csv-good")) is None

    mismatch = valid.replace("USD", "GBP").replace("csv-1", "csv-gbp")
    try:
        import_rows(session, "orders", read_table(mismatch, "text/csv"))
        raise AssertionError("currency mismatch should fail")
    except ImportValidationError as exc:
        assert exc.errors[0]["field"] == "currency"

    clicks = (
        "store_code,campaign_external_id,campaign_name,sku,daily_budget,metric_date,impressions,clicks,spend,attributed_sales,attributed_orders,currency\n"
        "us-main,camp-yoga,Yoga Auto,NS-YOGA-MAT,15.00,2026-03-02,10,11,1,1,1,USD\n"
    )
    try:
        import_rows(session, "ad_metrics", read_table(clicks, "text/csv"))
        raise AssertionError("clicks above impressions should fail")
    except ImportValidationError as exc:
        assert any(error["field"] == "clicks" for error in exc.errors)

    scraped = (
        "store_code,sku,competitor_asin,competitor_title,captured_at,source,collection_method,price,currency,review_count,negative_review_hits\n"
        "us-main,NS-LAMP-LED,B0SCRAPE,Scraped,2026-03-02T00:00:00Z,amazon_scrape,manual_import,10,USD,1,0\n"
    )
    try:
        import_rows(session, "competitor_snapshots", read_table(scraped, "text/csv"))
        raise AssertionError("scraped origin should fail")
    except ImportValidationError as exc:
        assert exc.errors


def test_csv_budget_import_is_ingest_and_does_not_write_an_audit(session, seeded):
    row = (
        "store_code,campaign_external_id,campaign_name,sku,daily_budget,metric_date,impressions,clicks,spend,attributed_sales,attributed_orders,currency\n"
        "us-main,camp-yoga,Yoga Auto,NS-YOGA-MAT,19.00,2026-03-08,800,40,15.00,90.00,3,USD\n"
    )
    import_rows(session, "ad_metrics", read_table(row, "text/csv"))
    campaign = session.scalar(select(AdCampaign).where(AdCampaign.external_id == "camp-yoga"))
    assert campaign.daily_budget == Decimal("19.00")
    assert session.scalar(select(func.count()).select_from(WritebackAuditLog)) == 0
    assert session.scalar(select(func.count()).select_from(PurchaseOrder)) == 0


def test_json_import_rejects_float_money(session, seeded):
    try:
        import_rows(
            session,
            "orders",
            read_table(
                '{"rows":[{"store_code":"us-main","external_order_id":"j1","line_id":"1","sku":"NS-YOGA-MAT","ordered_at":"2026-03-02","quantity":1,"gross_revenue":10.5,"discount":"0","unit_cogs":"1","platform_fee":"1","shipping_fee":"1","other_fee":"0","currency":"USD"}]}',
                "application/json",
            ),
        )
        raise AssertionError("float money should fail")
    except ImportValidationError:
        pass
