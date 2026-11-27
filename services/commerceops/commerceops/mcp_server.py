"""stdio MCP server. Draft tools do not write operational tables.

commerceops_approve_and_execute_draft is the human gate. Phase 2 should not
grant it to a model without OpenDot's own approval ledger in front of it.
"""

from __future__ import annotations

from datetime import date
import json
import logging
import sys

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from commerceops.db import session_scope
from commerceops.errors import CommerceOpsError
from commerceops.governance import (
    approve_and_execute_draft,
    create_ad_budget_draft,
    create_competitor_response_draft,
    create_purchase_order_draft,
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
from commerceops.serialize import to_jsonable
from commerceops.sop.retrieval import search_sops

_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
_DRAFT = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_REPORT = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
_APPROVE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)

mcp = MCPServer(
    name="commerceops",
    instructions=(
        "CommerceOps profit, ads, inventory, supplier, competitor, price simulation, and weekly report figures come only from these tools. "
        "Search SOPs when you need a procedure, and quote the returned citation. "
        "simulate_price_change and generate_weekly_report do not change budgets, purchase orders, or listings. "
        "create_* tools store drafts and do not change those records either. "
        "commerceops_approve_and_execute_draft records a human approval and applies one draft. "
        "Call it only after a person has approved. Never invent a money figure."
    ),
)


def _dump(value: object) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False)


def _guard(fn):  # type: ignore[no-untyped-def]
    try:
        return _dump(fn())
    except CommerceOpsError as exc:
        raise ToolError(f"{exc.code}: {exc.message}") from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolError("invalid_period: expected YYYY-MM-DD") from exc


@mcp.tool(name="commerceops_list_stores", annotations=_READ, structured_output=False)
def commerceops_list_stores() -> str:
    """List stores. Read only."""
    with session_scope() as session:
        return _guard(lambda: list_stores(session))


@mcp.tool(name="commerceops_profit_report", annotations=_READ, structured_output=False)
def commerceops_profit_report(store_code: str, start_date: str, end_date: str, compare_previous: bool = True) -> str:
    """Net profit, margin, and the profit bridge. Ad spend comes from ad metrics only."""
    start, end = _day(start_date), _day(end_date)
    with session_scope() as session:
        return _guard(lambda: profit_report(session, store_code, start, end, compare_previous))


@mcp.tool(name="commerceops_ads_diagnosis", annotations=_READ, structured_output=False)
def commerceops_ads_diagnosis(store_code: str, start_date: str, end_date: str) -> str:
    """ACOS, ROAS, TACOS, CTR, CVR, and the budget ladder. Does not change a budget."""
    start, end = _day(start_date), _day(end_date)
    with session_scope() as session:
        return _guard(lambda: ads_report(session, store_code, start, end, True))


@mcp.tool(name="commerceops_inventory_risk", annotations=_READ, structured_output=False)
def commerceops_inventory_risk(store_code: str, as_of: str, horizon_days: int = 14) -> str:
    """Days of cover, reorder point, and suggested units before MOQ."""
    day = _day(as_of)
    with session_scope() as session:
        return _guard(lambda: inventory_report(session, store_code, day, horizon_days))


@mcp.tool(name="commerceops_supplier_comparison", annotations=_READ, structured_output=False)
def commerceops_supplier_comparison(store_code: str, sku: str, as_of: str) -> str:
    """Rank supplier quotes by the published landed-cost, lead-time, MOQ, and on-time weights."""
    day = _day(as_of)
    with session_scope() as session:
        return _guard(lambda: supplier_report(session, store_code, sku, day))


@mcp.tool(name="commerceops_competitor_diff", annotations=_READ, structured_output=False)
def commerceops_competitor_diff(store_code: str, sku: str, as_of: str) -> str:
    """Diff imported competitor snapshots. This does not fetch or scrape a marketplace."""
    day = _day(as_of)
    with session_scope() as session:
        return _guard(lambda: competitor_report(session, store_code, sku, day))


@mcp.tool(name="commerceops_search_sops", annotations=_READ, structured_output=False)
def commerceops_search_sops(query: str, limit: int = 5) -> str:
    """Search SOP markdown and return doc_id, section, and an exact quote."""
    return _guard(lambda: search_sops(query, limit))


@mcp.tool(name="simulate_price_change", annotations=_READ, structured_output=False)
def simulate_price_change(
    store_code: str,
    sku: str,
    target_price: str,
    start_date: str = "",
    end_date: str = "",
) -> str:
    """Simulate a list-price change. Returns unit margin, profit delta, break-even ACOS, and elasticity scenarios. Does not write."""
    start = _day(start_date) if start_date else CURRENT_START
    end = _day(end_date) if end_date else CURRENT_END
    with session_scope() as session:
        return _guard(lambda: price_simulation(session, store_code, sku, target_price, start, end))


@mcp.tool(name="generate_weekly_report", annotations=_REPORT, structured_output=False)
def generate_weekly_report_tool(
    start_date: str = "",
    end_date: str = "",
    as_of: str = "",
    push_feishu: bool = False,
) -> str:
    """Assemble the weekly report from engine output. Does not create drafts. push_feishu sends only when a webhook is set."""
    start = _day(start_date) if start_date else CURRENT_START
    end = _day(end_date) if end_date else CURRENT_END
    day = _day(as_of) if as_of else AS_OF
    with session_scope() as session:
        return _guard(
            lambda: generate_weekly_report(session, start=start, end=end, as_of=day, push_feishu=push_feishu)
        )


@mcp.tool(name="commerceops_create_ad_budget_draft", annotations=_DRAFT, structured_output=False)
def commerceops_create_ad_budget_draft(
    store_code: str,
    campaign_external_id: str,
    start_date: str,
    end_date: str,
    created_by: str = "agent",
    idempotency_key: str = "",
) -> str:
    """Store an ad-budget draft. Does not change the campaign's daily budget."""
    start, end = _day(start_date), _day(end_date)
    with session_scope() as session:
        return _guard(
            lambda: create_ad_budget_draft(
                session,
                store_code=store_code,
                campaign_external_id=campaign_external_id,
                start=start,
                end=end,
                created_by=created_by,
                idempotency_key=idempotency_key or None,
            )
        )


@mcp.tool(name="commerceops_create_purchase_order_draft", annotations=_DRAFT, structured_output=False)
def commerceops_create_purchase_order_draft(
    store_code: str,
    sku: str,
    as_of: str,
    supplier_code: str = "",
    created_by: str = "agent",
    idempotency_key: str = "",
) -> str:
    """Store a purchase-order draft. Does not send anything to a supplier."""
    day = _day(as_of)
    with session_scope() as session:
        return _guard(
            lambda: create_purchase_order_draft(
                session,
                store_code=store_code,
                sku=sku,
                as_of=day,
                supplier_code=supplier_code or None,
                created_by=created_by,
                idempotency_key=idempotency_key or None,
            )
        )


@mcp.tool(name="commerceops_create_competitor_response_draft", annotations=_DRAFT, structured_output=False)
def commerceops_create_competitor_response_draft(
    store_code: str,
    sku: str,
    as_of: str,
    created_by: str = "agent",
    idempotency_key: str = "",
) -> str:
    """Store a competitor-response draft. Does not edit a listing or post a reply."""
    day = _day(as_of)
    with session_scope() as session:
        return _guard(
            lambda: create_competitor_response_draft(
                session,
                store_code=store_code,
                sku=sku,
                as_of=day,
                created_by=created_by,
                idempotency_key=idempotency_key or None,
            )
        )


@mcp.tool(name="commerceops_approve_and_execute_draft", annotations=_APPROVE, structured_output=False)
def commerceops_approve_and_execute_draft(draft_id: str, approver: str, note: str = "") -> str:
    """Record an explicit human approval and apply one draft. Idempotent if already executed."""
    with session_scope() as session:
        return _guard(lambda: approve_and_execute_draft(session, draft_id, approver, note))


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s %(message)s")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
