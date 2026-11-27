from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DatabaseError, IntegrityError

from commerceops.errors import CommerceOpsError, UnapprovedExecutionError
from commerceops.governance import (
    approve_and_execute_draft,
    create_ad_budget_draft,
    create_competitor_response_draft,
    create_purchase_order_draft,
    execute_draft,
    list_audit,
    reject_draft,
)
from commerceops.models import (
    AdBudgetRevision,
    AdCampaign,
    CompetitorSnapshot,
    PurchaseOrder,
    WritebackAuditLog,
)
from commerceops.seed import AS_OF, CURRENT_END, CURRENT_START, US_STORE


def test_unapproved_execution_fails_closed_and_is_audited(seeded):
    campaign = seeded.scalar(select(AdCampaign).where(AdCampaign.external_id == "camp-bottle-exact"))
    original = campaign.daily_budget
    created = create_ad_budget_draft(
        seeded,
        store_code=US_STORE,
        campaign_external_id="camp-bottle-exact",
        start=CURRENT_START,
        end=CURRENT_END,
        created_by="analyst",
    )
    assert created["status"] == "draft"
    assert created["decision"]["to_daily_budget"] == "31.5000"
    seeded.refresh(campaign)
    assert campaign.daily_budget == original
    with pytest.raises(UnapprovedExecutionError):
        execute_draft(seeded, created["draft_id"], "analyst", authorized=True)
    seeded.refresh(campaign)
    assert campaign.daily_budget == original
    assert seeded.scalar(select(func.count()).select_from(AdBudgetRevision)) == 0
    events = [entry["event"] for entry in list_audit(seeded, created["draft_id"])["entries"]]
    assert events == ["draft_created", "execution_rejected"]
    assert list_audit(seeded, created["draft_id"])["entries"][-1]["detail"]["reason"] == "unapproved"


def test_approved_execution_is_idempotent(seeded):
    created = create_ad_budget_draft(
        seeded,
        store_code=US_STORE,
        campaign_external_id="camp-bottle-exact",
        start=CURRENT_START,
        end=CURRENT_END,
        created_by="analyst",
    )
    again = create_ad_budget_draft(
        seeded,
        store_code=US_STORE,
        campaign_external_id="camp-bottle-exact",
        start=CURRENT_START,
        end=CURRENT_END,
        created_by="analyst",
    )
    assert again["created"] is False
    assert again["draft_id"] == created["draft_id"]
    first = approve_and_execute_draft(seeded, created["draft_id"], "owner", "cut the exact campaign", authorized=True)
    second = approve_and_execute_draft(seeded, created["draft_id"], "someone-else", "replay", authorized=True)
    campaign = seeded.scalar(select(AdCampaign).where(AdCampaign.external_id == "camp-bottle-exact"))
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert first["execution_ref"] == second["execution_ref"]
    assert campaign.daily_budget == Decimal("31.50")
    assert seeded.scalar(select(func.count()).select_from(AdBudgetRevision)) == 1
    events = [entry["event"] for entry in list_audit(seeded, created["draft_id"])["entries"]]
    assert events == ["draft_created", "approved", "executed", "replay_noop"]


def test_purchase_order_and_competitor_response_stay_simulated(seeded):
    before_snapshots = seeded.scalar(select(func.count()).select_from(CompetitorSnapshot))
    purchase = create_purchase_order_draft(
        seeded,
        store_code=US_STORE,
        sku="NS-CABLE-3PK",
        as_of=AS_OF,
        supplier_code=None,
        created_by="buyer",
    )
    assert purchase["decision"]["supplier_code"] == "SUP-SZR"
    assert purchase["decision"]["quantity"] == 210
    assert seeded.scalar(select(func.count()).select_from(PurchaseOrder)) == 0
    approved = approve_and_execute_draft(seeded, purchase["draft_id"], "owner", "buy the ranked quote", authorized=True)
    approve_and_execute_draft(seeded, purchase["draft_id"], "owner", "again", authorized=True)
    orders = seeded.scalars(select(PurchaseOrder)).all()
    assert len(orders) == 1
    assert orders[0].id == approved["execution_ref"]
    assert orders[0].sent_to_supplier == 0
    assert orders[0].status == "simulated_open"
    assert "not transmitted" in orders[0].simulation_note
    with pytest.raises((IntegrityError, DatabaseError)):
        seeded.execute(text("UPDATE purchase_orders SET sent_to_supplier = 1"))
        seeded.commit()
    seeded.rollback()

    response = create_competitor_response_draft(
        seeded,
        store_code=US_STORE,
        sku="NS-LAMP-LED",
        as_of=AS_OF,
        created_by="analyst",
    )
    assert any(action["alert"] == "price_drop" for action in response["decision"]["actions"])
    approve_and_execute_draft(seeded, response["draft_id"], "owner", "review price", authorized=True)
    assert seeded.scalar(select(func.count()).select_from(CompetitorSnapshot)) == before_snapshots


def test_yoga_draft_is_refused_and_rejected_draft_cannot_execute(seeded):
    with pytest.raises(CommerceOpsError) as refused:
        create_ad_budget_draft(
            seeded,
            store_code=US_STORE,
            campaign_external_id="camp-yoga",
            start=CURRENT_START,
            end=CURRENT_END,
            created_by="analyst",
        )
    assert refused.value.code == "no_adjustment_required"

    created = create_ad_budget_draft(
        seeded,
        store_code=US_STORE,
        campaign_external_id="camp-lamp",
        start=CURRENT_START,
        end=CURRENT_END,
        created_by="analyst",
    )
    reject_draft(seeded, created["draft_id"], "owner", "not now", authorized=True)
    with pytest.raises(CommerceOpsError) as rejected:
        approve_and_execute_draft(seeded, created["draft_id"], "owner", "too late", authorized=True)
    assert rejected.value.code == "draft_rejected"
    assert seeded.scalar(select(func.count()).select_from(AdBudgetRevision)) == 0

    broad = create_ad_budget_draft(
        seeded,
        store_code=US_STORE,
        campaign_external_id="camp-bottle-broad",
        start=CURRENT_START,
        end=CURRENT_END,
        created_by="analyst",
    )
    campaign = seeded.scalar(select(AdCampaign).where(AdCampaign.external_id == "camp-bottle-broad"))
    campaign.daily_budget = Decimal("80")
    seeded.commit()
    with pytest.raises(CommerceOpsError) as stale:
        approve_and_execute_draft(seeded, broad["draft_id"], "owner", "stale", authorized=True)
    assert stale.value.code == "stale_draft"
    seeded.refresh(campaign)
    assert campaign.daily_budget == Decimal("80")
    assert seeded.scalar(select(func.count()).select_from(AdBudgetRevision)) == 0


def test_audit_log_rejects_updates_and_deletes(seeded):
    created = create_purchase_order_draft(
        seeded,
        store_code=US_STORE,
        sku="NS-CABLE-3PK",
        as_of=AS_OF,
        supplier_code="SUP-VNF",
        created_by="buyer",
    )
    assert created["decision"]["quantity"] == 250
    with pytest.raises((IntegrityError, DatabaseError)):
        seeded.execute(text("UPDATE writeback_audit_logs SET actor = 'tampered'"))
        seeded.commit()
    seeded.rollback()
    with pytest.raises((IntegrityError, DatabaseError)):
        seeded.execute(text("DELETE FROM writeback_audit_logs"))
        seeded.commit()
    seeded.rollback()
    assert seeded.scalar(select(func.count()).select_from(WritebackAuditLog)) >= 1
