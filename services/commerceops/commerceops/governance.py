"""Drafts, the approval record, and operational writeback.

create_* stores a draft. execute_draft refuses to run without an approval
record that was already committed. approve_and_execute_draft writes that
record and the operational row in one transaction. A second call replays the
same execution instead of writing another purchase order or budget revision.
"""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from commerceops.clock import utc_now
from commerceops.context import current_workspace
from commerceops.engines.money import D
from commerceops.errors import (
    CommerceOpsError,
    DraftNotFound,
    NoActionRequired,
    UnapprovedExecutionError,
)
from commerceops.models import (
    ActionDraft,
    AdBudgetRevision,
    AdCampaign,
    ApprovalRecord,
    CompetitorResponse,
    PurchaseOrder,
    Store,
    Supplier,
    WritebackAuditLog,
)
from commerceops.reporting import budget_decision, competitor_decision, purchase_decision
from commerceops.serialize import to_jsonable

_SIMULATION_NOTE = "simulated; not transmitted to any supplier"


def create_ad_budget_draft(
    session: Session,
    *,
    store_code: str,
    campaign_external_id: str,
    start: date,
    end: date,
    created_by: str,
    idempotency_key: str | None = None,
    reduction_percent: int | None = None,
) -> dict:
    decision, evidence = budget_decision(session, store_code, campaign_external_id, start, end, reduction_percent)
    return _create(
        session,
        action_type="ad_budget_adjustment",
        store_code=store_code,
        created_by=created_by,
        idempotency_key=idempotency_key,
        start=start,
        end=end,
        as_of=None,
        decision=decision,
        evidence=evidence,
        formula_version="ads.v1",
    )


def create_purchase_order_draft(
    session: Session,
    *,
    store_code: str,
    sku: str,
    as_of: date,
    supplier_code: str | None,
    created_by: str,
    idempotency_key: str | None = None,
) -> dict:
    decision, evidence = purchase_decision(session, store_code, sku, as_of, supplier_code)
    return _create(
        session,
        action_type="purchase_order",
        store_code=store_code,
        created_by=created_by,
        idempotency_key=idempotency_key,
        start=None,
        end=None,
        as_of=as_of,
        decision=decision,
        evidence=evidence,
        formula_version="supplier.v1",
    )


def create_competitor_response_draft(
    session: Session,
    *,
    store_code: str,
    sku: str,
    as_of: date,
    created_by: str,
    idempotency_key: str | None = None,
) -> dict:
    decision, evidence = competitor_decision(session, store_code, sku, as_of)
    return _create(
        session,
        action_type="competitor_response",
        store_code=store_code,
        created_by=created_by,
        idempotency_key=idempotency_key,
        start=None,
        end=None,
        as_of=as_of,
        decision=decision,
        evidence=evidence,
        formula_version="competitor.v1",
    )


def execute_draft(session: Session, draft_id: str, actor: str, *, authorized: bool = False) -> dict:
    """Apply a draft only when an approval record already exists. This does not create one."""
    _require_authorized(authorized)
    draft = _draft(session, draft_id)
    actor = _actor(actor)
    if draft.status == "executed":
        _audit(session, draft, "replay_noop", actor, {"reason": "already_executed"})
        session.commit()
        return _emit("replay_noop", _result(draft, replayed=True))
    if draft.status == "rejected":
        _audit(session, draft, "execution_rejected", actor, {"reason": "draft_rejected"})
        session.commit()
        raise CommerceOpsError("draft is rejected", code="draft_rejected", status_code=409, details={"draft_id": draft_id})
    approval = session.scalar(select(ApprovalRecord).where(ApprovalRecord.draft_id == draft.id))
    if approval is None or approval.decision != "approved":
        _audit(session, draft, "execution_rejected", actor, {"reason": "unapproved"})
        session.commit()
        raise UnapprovedExecutionError(draft_id)
    return _apply_and_commit(session, draft, actor)


def approve_and_execute_draft(
    session: Session,
    draft_id: str,
    approver: str,
    note: str = "",
    *,
    authorized: bool = False,
) -> dict:
    _require_authorized(authorized)
    draft = _draft(session, draft_id)
    approver = _actor(approver)
    if draft.status == "executed":
        _audit(session, draft, "replay_noop", approver, {"reason": "already_executed"})
        session.commit()
        return _emit("replay_noop", _result(draft, replayed=True))
    if draft.status != "draft":
        _audit(session, draft, "execution_rejected", approver, {"reason": draft.status})
        session.commit()
        raise CommerceOpsError(
            "draft is not executable",
            code="draft_rejected" if draft.status == "rejected" else "draft_not_executable",
            status_code=409,
            details={"draft_id": draft_id},
        )
    try:
        fresh = _recompute(session, draft)
    except NoActionRequired as exc:
        _audit(session, draft, "execution_rejected", approver, {"reason": "stale_draft", "code": exc.code})
        session.commit()
        raise CommerceOpsError("draft is stale", code="stale_draft", status_code=409, details={"draft_id": draft_id}) from exc
    stored = json.loads(draft.payload_json)["decision"]
    if fresh != stored:
        _audit(session, draft, "execution_rejected", approver, {"reason": "stale_draft"})
        session.commit()
        raise CommerceOpsError("draft is stale", code="stale_draft", status_code=409, details={"draft_id": draft_id})
    approval = ApprovalRecord(
        id=str(uuid4()),
        workspace_id=draft.workspace_id,
        draft_id=draft.id,
        approver=approver,
        note=note.strip(),
        decision="approved",
        created_at=utc_now(),
    )
    session.add(approval)
    session.flush()
    draft.approval_id = approval.id
    _audit(session, draft, "approved", approver, {"approval_id": approval.id})
    return _apply_and_commit(session, draft, approver)


def reject_draft(
    session: Session,
    draft_id: str,
    approver: str,
    note: str = "",
    *,
    authorized: bool = False,
) -> dict:
    _require_authorized(authorized)
    draft = _draft(session, draft_id)
    approver = _actor(approver)
    if draft.status != "draft":
        raise CommerceOpsError(
            "only a draft can be rejected",
            code="draft_not_rejectable",
            status_code=409,
            details={"draft_id": draft_id},
        )
    approval = ApprovalRecord(
        id=str(uuid4()),
        workspace_id=draft.workspace_id,
        draft_id=draft.id,
        approver=approver,
        note=note.strip(),
        decision="rejected",
        created_at=utc_now(),
    )
    session.add(approval)
    session.flush()
    draft.approval_id = approval.id
    draft.status = "rejected"
    _audit(session, draft, "draft_rejected", approver, {"approval_id": approval.id})
    session.commit()
    return _emit("draft_rejected", _result(draft, replayed=False))


def list_drafts(session: Session, status: str | None = None) -> dict:
    query = select(ActionDraft).where(ActionDraft.workspace_id == current_workspace()).order_by(
        ActionDraft.created_at.desc(), ActionDraft.id.desc()
    )
    if status:
        query = query.where(ActionDraft.status == status)
    return {"drafts": [_summary(row) for row in session.scalars(query).all()]}


def get_draft(session: Session, draft_id: str) -> dict:
    draft = _draft(session, draft_id)
    approval = session.scalar(select(ApprovalRecord).where(ApprovalRecord.draft_id == draft.id))
    payload = _result(draft, replayed=False)
    payload["approval"] = None if approval is None else {
        "id": approval.id,
        "approver": approval.approver,
        "decision": approval.decision,
        "note": approval.note,
        "created_at": approval.created_at,
    }
    return payload


def list_audit(session: Session, draft_id: str) -> dict:
    _draft(session, draft_id)
    rows = session.scalars(
        select(WritebackAuditLog).where(WritebackAuditLog.draft_id == draft_id).order_by(WritebackAuditLog.id)
    ).all()
    return {
        "draft_id": draft_id,
        "entries": [
            {
                "id": row.id,
                "event": row.event,
                "actor": row.actor,
                "payload_hash": row.payload_hash,
                "detail": json.loads(row.detail_json),
                "created_at": row.created_at,
            }
            for row in rows
        ],
    }


def _create(
    session: Session,
    *,
    action_type: str,
    store_code: str,
    created_by: str,
    idempotency_key: str | None,
    start: date | None,
    end: date | None,
    as_of: date | None,
    decision: dict,
    evidence: dict,
    formula_version: str,
) -> dict:
    actor = _actor(created_by)
    workspace = current_workspace()
    store = session.scalar(
        select(Store).where(Store.code == store_code, Store.workspace_id == workspace)
    )
    if store is None:
        raise CommerceOpsError(f"store not found: {store_code}", code="store_not_found", status_code=404)
    identity = {
        "workspace_id": workspace,
        "action_type": action_type,
        "store_code": store_code,
        "start_date": None if start is None else start.isoformat(),
        "end_date": None if end is None else end.isoformat(),
        "as_of": None if as_of is None else as_of.isoformat(),
        "decision": decision,
    }
    key = _idempotency_key(idempotency_key, identity)
    existing = session.scalar(select(ActionDraft).where(ActionDraft.idempotency_key == key))
    if existing is not None:
        result = _result(existing, replayed=False)
        result["created"] = False
        return result
    payload = {
        "store_code": store_code,
        "start_date": identity["start_date"],
        "end_date": identity["end_date"],
        "as_of": identity["as_of"],
        "decision": decision,
        "evidence": evidence,
    }
    encoded = _canonical(payload)
    draft = ActionDraft(
        id=str(uuid4()),
        workspace_id=workspace,
        action_type=action_type,
        status="draft",
        idempotency_key=key,
        store_id=store.id,
        formula_version=formula_version,
        payload_json=encoded,
        payload_hash=sha256(encoded.encode()).hexdigest(),
        created_at=utc_now(),
        created_by=actor,
    )
    session.add(draft)
    session.flush()
    _audit(session, draft, "draft_created", actor, {"action_type": action_type})
    session.commit()
    result = _result(draft, replayed=False)
    result["created"] = True
    return _emit("draft_created", result)


def _apply_and_commit(session: Session, draft: ActionDraft, actor: str) -> dict:
    try:
        ref = _apply(session, draft)
        draft.status = "executed"
        draft.executed_at = utc_now()
        draft.execution_ref = ref
        _audit(session, draft, "executed", actor, {"execution_ref": ref})
        result = _result(draft, replayed=False)
        session.commit()
        return _emit("draft_executed", result)
    except Exception:
        session.rollback()
        raise


def _apply(session: Session, draft: ActionDraft) -> str:
    decision = json.loads(draft.payload_json)["decision"]
    if draft.action_type == "ad_budget_adjustment":
        campaign = session.scalar(
            select(AdCampaign).where(
                AdCampaign.store_id == draft.store_id,
                AdCampaign.external_id == decision["campaign_external_id"],
            )
        )
        if campaign is None:
            raise CommerceOpsError("campaign not found", code="campaign_not_found", status_code=404)
        revision = AdBudgetRevision(
            id=str(uuid4()),
            workspace_id=draft.workspace_id,
            draft_id=draft.id,
            campaign_id=campaign.id,
            previous_daily_budget=campaign.daily_budget,
            new_daily_budget=D(decision["to_daily_budget"]),
            created_at=utc_now(),
        )
        session.add(revision)
        campaign.daily_budget = revision.new_daily_budget
        session.flush()
        return revision.id
    if draft.action_type == "purchase_order":
        supplier = session.scalar(
            select(Supplier).where(
                Supplier.code == decision["supplier_code"],
                Supplier.workspace_id == draft.workspace_id,
            )
        )
        if supplier is None:
            raise CommerceOpsError("supplier not found", code="supplier_not_found", status_code=404)
        order = PurchaseOrder(
            id=str(uuid4()),
            workspace_id=draft.workspace_id,
            draft_id=draft.id,
            store_id=draft.store_id,
            supplier_id=supplier.id,
            sku=decision["sku"],
            quantity=int(decision["quantity"]),
            unit_landed_cost=D(decision["unit_landed_cost"]),
            currency=decision["currency"],
            status="simulated_open",
            sent_to_supplier=0,
            simulation_note=_SIMULATION_NOTE,
            created_at=utc_now(),
        )
        session.add(order)
        session.flush()
        return order.id
    if draft.action_type == "competitor_response":
        response = CompetitorResponse(
            id=str(uuid4()),
            workspace_id=draft.workspace_id,
            draft_id=draft.id,
            store_id=draft.store_id,
            sku=decision["sku"],
            plan_json=_canonical(decision),
            created_at=utc_now(),
        )
        session.add(response)
        session.flush()
        return response.id
    raise CommerceOpsError("unknown draft type", code="draft_not_executable", status_code=409)


def _recompute(session: Session, draft: ActionDraft) -> dict:
    payload = json.loads(draft.payload_json)
    store = session.get(Store, draft.store_id)
    if store is None:
        raise CommerceOpsError("store not found", code="store_not_found", status_code=404)
    decision = payload["decision"]
    if draft.action_type == "ad_budget_adjustment":
        fresh, _evidence = budget_decision(
            session,
            store.code,
            decision["campaign_external_id"],
            date.fromisoformat(payload["start_date"]),
            date.fromisoformat(payload["end_date"]),
            decision.get("reduction_percent"),
        )
        return fresh
    if draft.action_type == "purchase_order":
        fresh, _evidence = purchase_decision(
            session,
            store.code,
            decision["sku"],
            date.fromisoformat(payload["as_of"]),
            decision["supplier_code"],
        )
        return fresh
    fresh, _evidence = competitor_decision(
        session,
        store.code,
        decision["sku"],
        date.fromisoformat(payload["as_of"]),
    )
    return fresh


def _draft(session: Session, draft_id: str) -> ActionDraft:
    draft = session.get(ActionDraft, draft_id)
    if draft is None or draft.workspace_id != current_workspace():
        raise DraftNotFound(draft_id)
    return draft


def _require_authorized(authorized: bool) -> None:
    if not authorized:
        raise CommerceOpsError(
            "approval is not authorized for this user",
            code="approval_forbidden",
            status_code=403,
        )


def _audit(session: Session, draft: ActionDraft, event: str, actor: str, detail: dict) -> None:
    session.add(
        WritebackAuditLog(
            draft_id=draft.id,
            event=event,
            actor=actor,
            payload_hash=draft.payload_hash,
            detail_json=_canonical(detail),
            created_at=utc_now(),
            workspace_id=draft.workspace_id,
        )
    )


def _emit(event: str, payload: dict) -> dict:
    try:
        from commerceops.notify import notify_draft

        notify_draft(event, payload)
    except Exception:
        import logging

        logging.getLogger("commerceops").warning("commerceops notification failed", exc_info=True)
    return payload


def _summary(draft: ActionDraft) -> dict:
    payload = json.loads(draft.payload_json)
    return {
        "draft_id": draft.id,
        "action_type": draft.action_type,
        "status": draft.status,
        "formula_version": draft.formula_version,
        "created_by": draft.created_by,
        "created_at": draft.created_at,
        "executed_at": draft.executed_at,
        "execution_ref": draft.execution_ref,
        "decision": payload.get("decision"),
        "evidence": payload.get("evidence"),
    }


def _result(draft: ActionDraft, *, replayed: bool) -> dict:
    payload = json.loads(draft.payload_json)
    return {
        "draft_id": draft.id,
        "action_type": draft.action_type,
        "status": draft.status,
        "formula_version": draft.formula_version,
        "decision": payload["decision"],
        "execution_ref": draft.execution_ref,
        "replayed": replayed,
        "created_at": draft.created_at,
        "executed_at": draft.executed_at,
    }


def _actor(value: str) -> str:
    actor = value.strip()
    if not actor or len(actor) > 120:
        raise CommerceOpsError("actor is required", code="actor_required", status_code=422)
    return actor


def _idempotency_key(explicit: str | None, identity: dict) -> str:
    workspace = str(identity.get("workspace_id") or current_workspace())
    if explicit is not None and explicit.strip():
        key = f"{workspace}:{explicit.strip()}"
        if len(key) > 200:
            raise CommerceOpsError("idempotency key is too long", code="invalid_idempotency_key", status_code=422)
        return key
    return sha256(_canonical(identity).encode()).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(to_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
