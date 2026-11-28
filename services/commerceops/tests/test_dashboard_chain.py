from decimal import Decimal
from sqlalchemy import select

from commerceops.bootstrap import seed_if_empty
from commerceops.db import session_scope
from commerceops.models import Store

from commerceops.engines.money import D
from commerceops.governance import create_ad_budget_draft, approve_and_execute_draft
from commerceops.reporting import budget_decision
from commerceops.seed import CURRENT_END, CURRENT_START, US_STORE


def test_bootstrap_seeds_main_when_another_workspace_already_has_stores(database_url):
    assert seed_if_empty(database_url, "ws-demo")
    with session_scope(database_url) as session:
        original = session.scalars(select(Store.id).where(Store.workspace_id == "ws-demo").order_by(Store.id)).all()
    assert seed_if_empty(database_url, "main")
    assert not seed_if_empty(database_url, "main")
    with session_scope(database_url) as session:
        assert session.scalars(select(Store.id).where(Store.workspace_id == "ws-demo").order_by(Store.id)).all() == original
        assert set(session.scalars(select(Store.code).where(Store.workspace_id == "main"))) == {"us-main", "uk-main"}


def test_dashboard_data_empty_and_unknown_store(client):
    route = "/api/v1/dashboard"
    params = {"store_code": US_STORE, "start_date": CURRENT_START, "end_date": CURRENT_END}
    assert client.get("/api/v1/stores").json()["stores"] == []
    assert client.get(route, params=params).json()["error"] == "store_not_found"
    assert client.post("/api/v1/seed").status_code == 200
    report = client.get(route, params=params).json()
    assert len(report["daily"]) == 7
    assert sum(D(day["profit"]) for day in report["daily"]) == Decimal("682.60")
    assert sum(D(day["spend"]) for day in report["daily"]) == Decimal("896.00")
    assert D(report["inventory_value"]) > 0
    assert report["previous_inventory_value"] is None
    params.update(start_date="2020-01-01", end_date="2020-01-01")
    empty = client.get(route, params=params).json()
    assert empty["daily"][0]["sales"] == "0"
    assert empty["inventory_value"] is None


def test_budget_scenario_matches_draft_and_human_execution(seeded):
    campaign = "camp-bottle-broad"
    scenario, _ = budget_decision(seeded, US_STORE, campaign, CURRENT_START, CURRENT_END, 15)
    draft = create_ad_budget_draft(seeded, store_code=US_STORE, campaign_external_id=campaign,
                                   start=CURRENT_START, end=CURRENT_END, created_by="agent", reduction_percent=15)
    assert D(scenario["to_daily_budget"]) == D(scenario["from_daily_budget"]) * Decimal(".85")
    assert draft["status"] == "draft"
    assert approve_and_execute_draft(seeded, draft["draft_id"], "reviewer", "reviewed", authorized=True)["status"] == "executed"
