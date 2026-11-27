"""Local FastAPI surface. Bind it to loopback; OpenDot is the authenticated edge."""

from __future__ import annotations

from datetime import date
import os

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from commerceops.alerts import anomaly_brief
from commerceops.csv_import import import_rows, read_table
from commerceops.db import session_factory_for
from commerceops.evals.bench import load_latest, run_bench
from commerceops.notify import notify_anomalies, recent_notifications
from commerceops.engines.catalog import FORMULA_VERSIONS, FORMULAS
from commerceops.errors import CommerceOpsError
from commerceops.context import bind_workspace, reset_workspace
from commerceops.identity import HEADER, read_identity
from commerceops.governance import (
    approve_and_execute_draft,
    create_ad_budget_draft,
    create_competitor_response_draft,
    create_purchase_order_draft,
    execute_draft,
    get_draft,
    list_audit,
    list_drafts,
    reject_draft,
)
from commerceops.reporting import (
    ads_report,
    competitor_report,
    inventory_report,
    list_stores,
    price_simulation,
    profit_report,
    supplier_report,
)
from commerceops.seed import AS_OF, CURRENT_END, CURRENT_START
from commerceops.weekly_report import generate_weekly_report
from commerceops.seed import seed_demo_data
from commerceops.serialize import to_jsonable
from commerceops.sop.retrieval import search_sops


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdDraftBody(_Model):
    store_code: str
    campaign_external_id: str
    start_date: date
    end_date: date
    created_by: str = "api"
    idempotency_key: str | None = None


class PurchaseDraftBody(_Model):
    store_code: str
    sku: str
    as_of: date
    supplier_code: str | None = None
    created_by: str = "api"
    idempotency_key: str | None = None


class CompetitorDraftBody(_Model):
    store_code: str
    sku: str
    as_of: date
    created_by: str = "api"
    idempotency_key: str | None = None


class ExecuteBody(_Model):
    actor: str


class ApprovalBody(_Model):
    approver: str
    note: str = ""


class RejectBody(_Model):
    approver: str
    note: str = ""


class PriceSimBody(_Model):
    store_code: str
    sku: str
    target_price: str
    start_date: date | None = None
    end_date: date | None = None


class WeeklyReportBody(_Model):
    start_date: date | None = None
    end_date: date | None = None
    as_of: date | None = None
    push_feishu: bool = True


def create_app(database_url: str | None = None) -> FastAPI:
    app = FastAPI(title="CommerceOps", version="0.2.0")
    app.state.session_factory = session_factory_for(database_url)

    @app.middleware("http")
    async def _require_signed_identity(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        try:
            identity = read_identity(request.headers.get(HEADER, ""))
        except CommerceOpsError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": exc.code, "message": exc.message, "details": exc.details},
            )
        token = bind_workspace(identity.workspace_id)
        request.state.identity = identity
        try:
            return await call_next(request)
        finally:
            reset_workspace(token)

    @app.exception_handler(CommerceOpsError)
    async def _handle_error(_request: Request, exc: CommerceOpsError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "message": exc.message, "details": exc.details},
        )

    def get_session() -> Session:
        session = app.state.session_factory()
        try:
            yield session
        finally:
            session.close()

    @app.get("/health")
    def health(session: Session = Depends(get_session)) -> dict:
        session.execute(text("SELECT 1"))
        return {"status": "ok", "service": "commerceops"}

    @app.get("/api/v1/formulas")
    def formulas() -> dict:
        return {"versions": FORMULA_VERSIONS, "formulas": FORMULAS}

    @app.post("/api/v1/seed")
    def seed(request: Request, session: Session = Depends(get_session)) -> dict:
        return seed_demo_data(session, request.state.identity.workspace_id)

    @app.post("/api/v1/import/{dataset}")
    async def import_dataset(dataset: str, request: Request) -> dict:
        rows = read_table(await request.body(), request.headers.get("content-type", ""))
        session = app.state.session_factory()
        try:
            return import_rows(session, dataset, rows)
        finally:
            session.close()

    @app.get("/api/v1/stores")
    def stores(session: Session = Depends(get_session)) -> dict:
        return to_jsonable(list_stores(session))

    @app.get("/api/v1/profit")
    def profit(
        store_code: str,
        start_date: date,
        end_date: date,
        compare: bool = True,
        session: Session = Depends(get_session),
    ) -> dict:
        return to_jsonable(profit_report(session, store_code, start_date, end_date, compare))

    @app.get("/api/v1/ads")
    def ads(
        store_code: str,
        start_date: date,
        end_date: date,
        compare: bool = True,
        session: Session = Depends(get_session),
    ) -> dict:
        return to_jsonable(ads_report(session, store_code, start_date, end_date, compare))

    @app.post("/api/v1/ads/budget-drafts")
    def ad_draft(body: AdDraftBody, request: Request, session: Session = Depends(get_session)) -> dict:
        return to_jsonable(
            create_ad_budget_draft(
                session,
                store_code=body.store_code,
                campaign_external_id=body.campaign_external_id,
                start=body.start_date,
                end=body.end_date,
                created_by=request.state.identity.username,
                idempotency_key=body.idempotency_key,
            )
        )

    @app.get("/api/v1/inventory")
    def inventory(
        store_code: str,
        as_of: date,
        horizon_days: int = 14,
        lookback_days: int = 14,
        session: Session = Depends(get_session),
    ) -> dict:
        return to_jsonable(inventory_report(session, store_code, as_of, horizon_days, lookback_days))

    @app.get("/api/v1/suppliers/compare")
    def suppliers(
        store_code: str,
        sku: str,
        as_of: date,
        session: Session = Depends(get_session),
    ) -> dict:
        return to_jsonable(supplier_report(session, store_code, sku, as_of))

    @app.post("/api/v1/purchase-order-drafts")
    def purchase_draft(body: PurchaseDraftBody, request: Request, session: Session = Depends(get_session)) -> dict:
        return to_jsonable(
            create_purchase_order_draft(
                session,
                store_code=body.store_code,
                sku=body.sku,
                as_of=body.as_of,
                supplier_code=body.supplier_code,
                created_by=request.state.identity.username,
                idempotency_key=body.idempotency_key,
            )
        )

    @app.get("/api/v1/competitors/diff")
    def competitors(
        store_code: str,
        sku: str,
        as_of: date,
        session: Session = Depends(get_session),
    ) -> dict:
        return to_jsonable(competitor_report(session, store_code, sku, as_of))

    @app.post("/api/v1/competitor-response-drafts")
    def competitor_draft(body: CompetitorDraftBody, request: Request, session: Session = Depends(get_session)) -> dict:
        return to_jsonable(
            create_competitor_response_draft(
                session,
                store_code=body.store_code,
                sku=body.sku,
                as_of=body.as_of,
                created_by=request.state.identity.username,
                idempotency_key=body.idempotency_key,
            )
        )

    @app.post("/api/v1/price-simulations")
    def price_sim(body: PriceSimBody, session: Session = Depends(get_session)) -> dict:
        start = body.start_date or CURRENT_START
        end = body.end_date or CURRENT_END
        return to_jsonable(price_simulation(session, body.store_code, body.sku, body.target_price, start, end))

    @app.post("/api/v1/reports/weekly")
    def weekly(body: WeeklyReportBody, session: Session = Depends(get_session)) -> dict:
        return generate_weekly_report(
            session,
            start=body.start_date or CURRENT_START,
            end=body.end_date or CURRENT_END,
            as_of=body.as_of or AS_OF,
            push_feishu=body.push_feishu,
        )

    @app.get("/api/v1/sops/search")
    def sops(q: str = "", limit: int = 5) -> dict:
        try:
            return to_jsonable(search_sops(q, limit))
        except ValueError as exc:
            raise CommerceOpsError(str(exc), code="invalid_query", status_code=422) from exc

    @app.get("/api/v1/drafts")
    def drafts(status: str | None = None, session: Session = Depends(get_session)) -> dict:
        return to_jsonable(list_drafts(session, status))

    @app.get("/api/v1/notifications")
    def notifications() -> dict:
        return {"notifications": recent_notifications()}

    @app.post("/api/v1/notifications/anomalies")
    def anomalies(store_code: str, session: Session = Depends(get_session)) -> dict:
        brief = anomaly_brief(session, store_code)
        notice = notify_anomalies(to_jsonable(brief)) if brief["alerts"] else None
        return to_jsonable({"brief": brief, "notification": notice})

    @app.post("/api/v1/evals/run")
    def run_evals() -> dict:
        return run_bench()

    @app.get("/api/v1/evals/latest")
    def latest_eval() -> dict:
        return {"scorecard": load_latest()}

    @app.get("/api/v1/drafts/{draft_id}")
    def draft(draft_id: str, session: Session = Depends(get_session)) -> dict:
        return to_jsonable(get_draft(session, draft_id))

    @app.get("/api/v1/drafts/{draft_id}/audit")
    def audit(draft_id: str, session: Session = Depends(get_session)) -> dict:
        return to_jsonable(list_audit(session, draft_id))

    @app.post("/api/v1/drafts/{draft_id}/execute")
    def execute(draft_id: str, body: ExecuteBody, request: Request, session: Session = Depends(get_session)) -> dict:
        identity = request.state.identity
        return to_jsonable(
            execute_draft(session, draft_id, identity.username, authorized=identity.can_approve)
        )

    @app.post("/api/v1/drafts/{draft_id}/approve-and-execute")
    def approve(draft_id: str, body: ApprovalBody, request: Request, session: Session = Depends(get_session)) -> dict:
        identity = request.state.identity
        return to_jsonable(
            approve_and_execute_draft(
                session,
                draft_id,
                identity.username,
                body.note,
                authorized=identity.can_approve,
            )
        )

    @app.post("/api/v1/drafts/{draft_id}/reject")
    def reject(draft_id: str, body: RejectBody, request: Request, session: Session = Depends(get_session)) -> dict:
        identity = request.state.identity
        return to_jsonable(
            reject_draft(session, draft_id, identity.username, body.note, authorized=identity.can_approve)
        )

    return app


def _auto_seed_enabled() -> bool:
    return os.environ.get("COMMERCEOPS_AUTO_SEED", "0").strip().lower() in {"1", "true", "yes"}


def main() -> None:
    import uvicorn

    if _auto_seed_enabled():
        from commerceops.bootstrap import seed_if_empty

        seeded = seed_if_empty()
        print(f"commerceops auto-seed {'wrote demo data' if seeded else 'database already has stores'}", flush=True)
    uvicorn.run(
        "commerceops.api.app:create_app",
        factory=True,
        host=os.environ.get("COMMERCEOPS_HOST", "127.0.0.1"),
        port=int(os.environ.get("COMMERCEOPS_PORT", "8077")),
    )


if __name__ == "__main__":
    main()
