"""Authorization, workspace isolation, inbound, currency, and Alembic upgrades."""

from datetime import date
from decimal import Decimal
import sqlite3

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from commerceops.api.app import create_app
from commerceops.context import bind_workspace, reset_workspace
from commerceops.db import init_db, session_factory_for
from commerceops.engines.inventory import plan_replenishment, split_inbound
from commerceops.engines.suppliers import SupplierQuoteInput, rank_suppliers
from commerceops.governance import approve_and_execute_draft, create_purchase_order_draft
from commerceops.models import PurchaseOrder
from commerceops.reporting import list_stores, profit_report
from commerceops.seed import AS_OF, CURRENT_END, CURRENT_START, US_STORE, seed_demo_data
from tests.conftest import approver_token


def _headers(username: str, *, can_approve: bool, workspace_id: str = "ws-demo") -> dict[str, str]:
    return {
        "x-commerceops-identity": approver_token(
            workspace_id,
            can_approve=can_approve,
            username=username,
        )
    }


def test_direct_api_without_signature_is_rejected(database_url):
    raw = TestClient(create_app(database_url))
    denied = raw.post(
        "/api/v1/drafts/missing/approve-and-execute",
        json={"approver": "owner", "note": "bypass"},
    )
    assert denied.status_code == 401
    assert denied.json()["error"] == "unauthorized"
    health = raw.get("/health")
    assert health.status_code == 200
    assert "formula_versions" not in health.json()


def test_non_approver_cannot_spoof_owner_and_a_real_approval_runs_once(database_url):
    app = create_app(database_url)
    raw = TestClient(app)
    owner = TestClient(app)
    member = TestClient(app)
    owner.headers.update(_headers("owner", can_approve=True))
    member.headers.update(_headers("member", can_approve=False))
    assert owner.post("/api/v1/seed").status_code == 200
    created = owner.post(
        "/api/v1/purchase-order-drafts",
        json={
            "store_code": US_STORE,
            "sku": "NS-CABLE-3PK",
            "as_of": AS_OF.isoformat(),
            "created_by": "owner",
        },
    ).json()
    draft_id = created["draft_id"]
    listed = owner.get("/api/v1/drafts").json()["drafts"][0]
    assert listed["created_by"] == "owner"
    unsigned = raw.post(
        f"/api/v1/drafts/{draft_id}/approve-and-execute",
        json={"approver": "owner", "note": "unsigned"},
    )
    assert unsigned.status_code == 401
    spoofed = member.post(
        f"/api/v1/drafts/{draft_id}/approve-and-execute",
        json={"approver": "owner", "note": "spoof"},
    )
    assert spoofed.status_code == 403
    assert spoofed.json()["error"] == "approval_forbidden"
    assert owner.get(f"/api/v1/drafts/{draft_id}").json()["status"] == "draft"
    first = owner.post(
        f"/api/v1/drafts/{draft_id}/approve-and-execute",
        json={"approver": "member", "note": "real owner"},
    ).json()
    second = owner.post(
        f"/api/v1/drafts/{draft_id}/approve-and-execute",
        json={"approver": "member", "note": "again"},
    ).json()
    assert first["status"] == "executed" and first["replayed"] is False
    assert second["replayed"] is True
    assert second["execution_ref"] == first["execution_ref"]
    session = session_factory_for(database_url)()
    try:
        assert session.query(PurchaseOrder).count() == 1
    finally:
        session.close()


def test_two_workspaces_cannot_read_each_others_drafts(database_url):
    app = create_app(database_url)
    client = TestClient(app)
    for workspace, actor in (("ws-a", "ada"), ("ws-b", "ben")):
        client.headers.update(_headers(actor, can_approve=True, workspace_id=workspace))
        assert client.post("/api/v1/seed").status_code == 200
    client.headers.update(_headers("ada", can_approve=True, workspace_id="ws-a"))
    created = client.post(
        "/api/v1/purchase-order-drafts",
        json={"store_code": US_STORE, "sku": "NS-CABLE-3PK", "as_of": AS_OF.isoformat(), "created_by": "ben"},
    ).json()
    draft_id = created["draft_id"]
    assert client.get("/api/v1/drafts").json()["drafts"][0]["created_by"] == "ada"
    client.headers.update(_headers("ben", can_approve=False, workspace_id="ws-b"))
    assert client.get(f"/api/v1/drafts/{created['draft_id']}").status_code == 404
    assert client.get("/api/v1/drafts").json()["drafts"] == []
    weekly = client.post("/api/v1/reports/weekly", json={"push_feishu": False}).json()
    assert weekly["approvals"]["pending"] == 0
    client.headers.update(_headers("ada", can_approve=True, workspace_id="ws-a"))
    assert client.get("/api/v1/drafts").json()["drafts"][0]["draft_id"] == created["draft_id"]


def test_all_sixteen_models_carry_workspace_and_store_code_cannot_cross(database_url):
    from commerceops.models import (
        ActionDraft,
        AdBudgetRevision,
        AdCampaign,
        AdMetricDay,
        ApprovalRecord,
        CompetitorResponse,
        CompetitorSnapshot,
        InventorySnapshot,
        Order,
        Product,
        PurchaseOrder,
        Refund,
        Store,
        Supplier,
        SupplierQuote,
        WritebackAuditLog,
    )

    url_models = (
        Store,
        Product,
        Order,
        Refund,
        AdCampaign,
        AdMetricDay,
        InventorySnapshot,
        Supplier,
        SupplierQuote,
        CompetitorSnapshot,
        ActionDraft,
        ApprovalRecord,
        WritebackAuditLog,
        PurchaseOrder,
        AdBudgetRevision,
        CompetitorResponse,
    )
    init_db(database_url)
    bind = session_factory_for(database_url).kw["bind"]
    inspector = inspect(bind)
    missing = [
        model.__tablename__
        for model in url_models
        if "workspace_id" not in {column["name"] for column in inspector.get_columns(model.__tablename__)}
    ]
    assert missing == []
    app = create_app(database_url)
    client = TestClient(app)
    client.headers.update(_headers("ada", can_approve=True, workspace_id="ws-a"))
    assert client.post("/api/v1/seed").status_code == 200
    client.headers.update(_headers("ben", can_approve=True, workspace_id="ws-b"))
    assert client.post("/api/v1/seed").status_code == 200
    foreign = client.get(
        "/api/v1/profit",
        params={
            "store_code": "ws-a:us-main",
            "start_date": CURRENT_START.isoformat(),
            "end_date": CURRENT_END.isoformat(),
        },
    )
    assert foreign.status_code == 404
    own = client.get(
        "/api/v1/profit",
        params={"store_code": US_STORE, "start_date": CURRENT_START.isoformat(), "end_date": CURRENT_END.isoformat()},
    )
    assert own.status_code == 200
    assert own.json()["current"]["net_profit"] == "682.60"
    session = session_factory_for(database_url)()
    try:
        for model in (AdMetricDay, Supplier, AdCampaign, Order):
            rows = session.scalars(select(model).where(model.workspace_id == "ws-b")).all()
            assert rows
            assert all(row.workspace_id == "ws-b" for row in rows)
    finally:
        session.close()


def test_split_inbound_on_time_late_missing_eta_and_zero():
    stockout = date(2026, 3, 18)
    assert split_inbound(10, date(2026, 3, 18), stockout) == (10, 0, False)
    assert split_inbound(10, date(2026, 3, 30), stockout) == (0, 0, True)
    assert split_inbound(4, None, stockout) == (0, 4, False)
    assert split_inbound(0, None, stockout) == (0, 0, False)
    on_time = plan_replenishment(
        average_daily_sales_value=Decimal("1"),
        planning_lead_time_days=5,
        target_cover_days=5,
        safety_stock=0,
        available=2,
        inbound_qty=3,
        inbound_eta=date(2026, 3, 16),
        stockout_date=date(2026, 3, 17),
        velocity_status="ok",
    )
    assert on_time.effective_inbound_qty == 3
    assert on_time.suggested_order_qty_exact == Decimal("5")
    late = plan_replenishment(
        average_daily_sales_value=Decimal("1"),
        planning_lead_time_days=5,
        target_cover_days=5,
        safety_stock=0,
        available=2,
        inbound_qty=3,
        inbound_eta=date(2026, 4, 1),
        stockout_date=date(2026, 3, 17),
        velocity_status="ok",
    )
    assert late.effective_inbound_qty == 0
    assert late.inbound_late is True
    assert late.suggested_order_qty_exact == Decimal("8")


def _quote(code: str, currency: str) -> SupplierQuoteInput:
    return SupplierQuoteInput(
        supplier_code=code,
        tier_min_qty=1,
        unit_price=Decimal("10"),
        duty_rate=Decimal("0"),
        freight_per_unit=Decimal("1"),
        moq=1,
        lead_time_days=10,
        order_multiple=1,
        on_time_rate=Decimal("1"),
        on_time_sample_size=10,
        currency=currency,
    )


def test_mixed_supplier_currencies_are_not_ranked():
    demand = dict(
        average_daily_sales=Decimal("1"),
        available=0,
        inbound_qty=0,
        safety_stock=0,
        target_cover_days=0,
        days_of_cover=Decimal("10"),
        velocity_ok=True,
    )
    mixed = rank_suppliers([_quote("US", "USD"), _quote("CN", "CNY")], **demand)
    assert mixed.status == "mixed_currency_unsupported"
    assert mixed.ranked is False
    assert mixed.rankings == ()
    same = rank_suppliers([_quote("A", "GBP"), _quote("B", "GBP")], **demand)
    assert same.status == "ok"


def test_alembic_creates_a_fresh_database(tmp_path):
    url = f"sqlite:///{tmp_path}/fresh.db"
    init_db(url)
    bind = session_factory_for(url).kw["bind"]
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("action_drafts")}
    assert "workspace_id" in columns
    assert "alembic_version" in inspector.get_table_names()


def test_alembic_upgrades_a_pre_alembic_sqlite_database(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE action_drafts (
            id TEXT PRIMARY KEY,
            action_type TEXT NOT NULL,
            status TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            store_id TEXT NOT NULL,
            formula_version TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE writeback_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id TEXT NOT NULL,
            event TEXT NOT NULL,
            actor TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE purchase_orders (
            id TEXT PRIMARY KEY,
            draft_id TEXT NOT NULL UNIQUE,
            store_id TEXT NOT NULL,
            supplier_id TEXT NOT NULL,
            sku TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_landed_cost TEXT NOT NULL,
            currency TEXT NOT NULL,
            status TEXT NOT NULL,
            sent_to_supplier INTEGER NOT NULL,
            simulation_note TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO action_drafts VALUES ('d1','purchase_order','draft','k1','s1','supplier.v1','{}','hash','t','owner')"
    )
    connection.execute(
        "INSERT INTO writeback_audit_logs (draft_id, event, actor, payload_hash, detail_json, created_at) VALUES ('d1','draft_created','owner','hash','{}','t')"
    )
    connection.execute(
        "INSERT INTO purchase_orders VALUES ('po1','d1','s1','sup','SKU',10,'2.82','USD','simulated_open',0,'simulated','t')"
    )
    connection.commit()
    connection.close()
    init_db(f"sqlite:///{path}")
    check = sqlite3.connect(path)
    draft = check.execute("SELECT status, workspace_id, created_by FROM action_drafts WHERE id = 'd1'").fetchone()
    audit = check.execute("SELECT event, workspace_id FROM writeback_audit_logs WHERE draft_id = 'd1'").fetchone()
    order = check.execute("SELECT quantity, workspace_id, sent_to_supplier FROM purchase_orders WHERE id = 'po1'").fetchone()
    check.close()
    assert draft == ("draft", "ws-legacy", "owner")
    assert audit == ("draft_created", "ws-legacy")
    assert order == (10, "ws-legacy", 0)


def test_authorized_library_approval_still_writes_once(seeded):
    created = create_purchase_order_draft(
        seeded,
        store_code=US_STORE,
        sku="NS-CABLE-3PK",
        as_of=AS_OF,
        supplier_code=None,
        created_by="buyer",
    )
    first = approve_and_execute_draft(seeded, created["draft_id"], "owner", "once", authorized=True)
    second = approve_and_execute_draft(seeded, created["draft_id"], "intruder", "twice", authorized=True)
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert second["execution_ref"] == first["execution_ref"]
    assert seeded.execute(text("SELECT COUNT(*) FROM purchase_orders")).scalar() == 1
