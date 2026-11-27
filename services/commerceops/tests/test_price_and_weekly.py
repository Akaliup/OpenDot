from decimal import Decimal

import pytest
from sqlalchemy import func, select

from commerceops.bootstrap import seed_if_empty
from commerceops.db import session_factory_for
from commerceops.engines.price_sim import PriceSimInputs, simulate_price
from commerceops.models import ActionDraft, PurchaseOrder
from commerceops.reporting import price_simulation
from commerceops.seed import AS_OF, CURRENT_END, CURRENT_START, US_STORE
from commerceops.weekly_report import generate_weekly_report


def _bottle_inputs(target: str) -> PriceSimInputs:
    return PriceSimInputs(
        sku="NS-BOTTLE-1L",
        currency="USD",
        current_price=Decimal("20"),
        target_price=Decimal(target),
        units=56,
        gross_revenue=Decimal("1120"),
        discounts=Decimal("56"),
        refunds=Decimal("320"),
        cogs=Decimal("252"),
        recovered_cogs=Decimal("13.50"),
        platform_fees=Decimal("168"),
        shipping_fees=Decimal("112"),
        other_fees=Decimal("0"),
        ad_spend=Decimal("665"),
        attributed_sales=Decimal("525"),
    )


def test_price_engine_matches_the_hand_calculation():
    result = simulate_price(_bottle_inputs("18"))
    by_name = {item.name: item for item in result.scenarios}
    margin = Decimal("167.9") / Decimal("669.6")
    assert result.formula_version == "price_sim.v1"
    assert result.new_unit_margin.value == margin
    assert result.break_even_acos.value == margin
    assert result.break_even_acos.status == "ok"
    assert result.profit_delta == Decimal("-40.81")
    assert by_name["base"].units == Decimal("61.6")
    assert by_name["conservative"].profit_delta == Decimal("-30.736")
    assert by_name["optimistic"].profit_delta == Decimal("-50.884")
    assert result.current_acos.value == Decimal("665") / Decimal("525")
    same = simulate_price(_bottle_inputs("20"))
    assert all(item.profit_delta == 0 for item in same.scenarios)
    with pytest.raises(TypeError):
        simulate_price(
            PriceSimInputs(
                sku="NS-BOTTLE-1L",
                currency="USD",
                current_price=Decimal("20"),
                target_price=18.0,  # type: ignore[arg-type]
                units=56,
                gross_revenue=Decimal("1120"),
                discounts=Decimal("56"),
                refunds=Decimal("320"),
                cogs=Decimal("252"),
                recovered_cogs=Decimal("13.50"),
                platform_fees=Decimal("168"),
                shipping_fees=Decimal("112"),
                other_fees=Decimal("0"),
                ad_spend=Decimal("665"),
                attributed_sales=Decimal("525"),
            )
        )


def test_price_and_weekly_http_round_trip(client, database_url):
    assert client.post("/api/v1/seed").status_code == 200
    health = client.get("/health").json()
    assert health["formula_versions"]["price_sim"] == "price_sim.v1"
    assert "volume_multiplier" in client.get("/api/v1/formulas").json()["formulas"]["price_sim.v1"]
    denied = client.post(
        "/api/v1/price-simulations",
        json={"store_code": US_STORE, "sku": "NS-BOTTLE-1L", "target_price": "-1"},
    )
    assert denied.status_code == 422
    assert denied.json()["error"] == "invalid_price"
    garbage = client.post(
        "/api/v1/price-simulations",
        json={"store_code": US_STORE, "sku": "NS-BOTTLE-1L", "target_price": "abc"},
    )
    assert garbage.status_code == 422
    missing = client.post(
        "/api/v1/price-simulations",
        json={"store_code": US_STORE, "sku": "NO-SUCH", "target_price": "10"},
    )
    assert missing.status_code == 404
    simulated = client.post(
        "/api/v1/price-simulations",
        json={
            "store_code": US_STORE,
            "sku": "NS-BOTTLE-1L",
            "target_price": "18.00",
            "start_date": CURRENT_START.isoformat(),
            "end_date": CURRENT_END.isoformat(),
        },
    )
    assert simulated.status_code == 200
    body = simulated.json()
    assert Decimal(body["profit_delta"]) == Decimal("-40.81")
    assert body["new_unit_margin"]["status"] == "ok"
    assert isinstance(body["profit_delta"], str)
    report = client.post("/api/v1/reports/weekly", json={"push_feishu": True})
    assert report.status_code == 200
    weekly = report.json()
    assert weekly["assembly"] == "weekly.v1"
    assert "682.60" in weekly["markdown"]
    assert weekly["notification"]["mode"] == "dry_run"
    assert weekly["feishu_card"]["msg_type"] == "interactive"
    assert weekly["approvals"]["pending"] == 0
    session = session_factory_for(database_url)()
    try:
        assert session.scalar(select(func.count()).select_from(ActionDraft)) == 0
    finally:
        session.close()


def test_weekly_report_leaves_a_pending_draft_alone(seeded):
    from commerceops.governance import approve_and_execute_draft, create_purchase_order_draft

    created = create_purchase_order_draft(
        seeded,
        store_code=US_STORE,
        sku="NS-CABLE-3PK",
        as_of=AS_OF,
        supplier_code=None,
        created_by="test",
    )
    report = generate_weekly_report(
        seeded,
        start=CURRENT_START,
        end=CURRENT_END,
        as_of=AS_OF,
        push_feishu=True,
    )
    assert report["approvals"]["pending"] == 1
    assert report["approvals"]["purchase_orders"] == 0
    assert "Pending drafts: 1" in report["markdown"]
    first = approve_and_execute_draft(seeded, created["draft_id"], "owner", "once")
    second = approve_and_execute_draft(seeded, created["draft_id"], "owner", "twice")
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert second["execution_ref"] == first["execution_ref"]
    assert seeded.scalar(select(func.count()).select_from(PurchaseOrder)) == 1


def test_seed_if_empty_runs_once(database_url, monkeypatch):
    monkeypatch.setenv("COMMERCEOPS_DATABASE_URL", database_url)
    assert seed_if_empty(database_url) is True
    assert seed_if_empty(database_url) is False
    session = session_factory_for(database_url)()
    try:
        report = price_simulation(session, US_STORE, "NS-BOTTLE-1L", "18", CURRENT_START, CURRENT_END)
        assert report["profit_delta"] == Decimal("-40.81")
    finally:
        session.close()

