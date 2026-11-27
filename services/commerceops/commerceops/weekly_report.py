"""Weekly executive report. Every figure is copied from an engine result.

The assembler does not estimate, round for narrative, or add a cross-currency
total. Markdown and the Feishu card are rendered from the same JSON object
the API returns, after Decimals have become strings.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from commerceops.context import current_workspace
from commerceops.engines.catalog import FORMULA_VERSIONS
from commerceops.notify import build_card, dispatch
from commerceops.models import (
    ActionDraft,
    AdBudgetRevision,
    CompetitorResponse,
    Product,
    PurchaseOrder,
    Store,
    WritebackAuditLog,
)
from commerceops.reporting import ads_report, competitor_report, inventory_report, list_stores, profit_report, supplier_report
from commerceops.serialize import to_jsonable

ASSEMBLY_VERSION = "weekly.v1"
_OMITTED_FROM_SOURCE = ("markdown", "feishu_card", "notification")


def generate_weekly_report(
    session: Session,
    *,
    start: date,
    end: date,
    as_of: date,
    push_feishu: bool,
) -> dict:
    stores = []
    for store in list_stores(session)["stores"]:
        code = store["code"]
        profit = profit_report(session, code, start, end, compare=True)
        ads = ads_report(session, code, start, end, compare=True)
        inventory = inventory_report(session, code, as_of, horizon_days=14)
        cuts = []
        for campaign in ads["campaigns"]:
            budget = campaign["budget"]
            if budget.reason == "no_adjustment":
                continue
            cuts.append(
                {
                    "campaign_external_id": campaign["campaign_external_id"],
                    "name": campaign["name"],
                    "sku": campaign["sku"],
                    "reason": budget.reason,
                    "current_daily_budget": budget.current_daily_budget,
                    "suggested_daily_budget": budget.suggested_daily_budget,
                    "daily_cut": budget.current_daily_budget - budget.suggested_daily_budget,
                }
            )
        cuts.sort(key=lambda row: (-row["daily_cut"], row["campaign_external_id"]))
        stockouts = []
        for sku in inventory["at_risk_skus"]:
            row = next(item for item in inventory["skus"] if item["sku"] == sku)
            cover = row["cover"]
            replenishment = row["replenishment"]
            ranked = supplier_report(session, code, sku, as_of)
            quotes = [
                {
                    "supplier_code": quote.supplier_code,
                    "rank": quote.rank,
                    "landed_cost": quote.landed_cost,
                    "adjusted_order_qty": quote.adjusted_order_qty,
                    "lead_time_risk": quote.lead_time_risk,
                }
                for quote in ranked["rank"].rankings
            ]
            stockouts.append(
                {
                    "sku": sku,
                    "days_of_cover": cover.days_of_cover,
                    "cover_status": cover.status,
                    "suggested_order_qty": replenishment.suggested_order_qty,
                    "supplier_status": ranked["rank"].status,
                    "suppliers": quotes,
                }
            )
        competitors = []
        store_row = session.scalar(
            select(Store).where(Store.code == code, Store.workspace_id == current_workspace())
        )
        products = []
        if store_row is not None:
            products = session.scalars(
                select(Product).where(
                    Product.workspace_id == current_workspace(),
                    Product.store_id == store_row.id,
                ).order_by(Product.sku)
            ).all()
        for product in products:
            diff = competitor_report(session, code, product.sku, as_of)
            alerts = [item for item in diff["comparisons"] if item.get("alerts")]
            if not alerts:
                continue
            competitors.append(
                {
                    "sku": product.sku,
                    "sample_data": diff["sample_data"],
                    "alerts": [
                        {
                            "competitor_asin": item["competitor_asin"],
                            "alerts": list(item["alerts"]),
                            "price_change": item.get("price_change"),
                            "source": item.get("source", ""),
                            "collection_method": item.get("collection_method", ""),
                        }
                        for item in alerts
                    ],
                }
            )
        bridge = profit["bridge"]
        stores.append(
            {
                "code": code,
                "currency": store["currency"],
                "profit": {
                    "current_net_profit": profit["current"].net_profit,
                    "previous_net_profit": profit["previous"].net_profit,
                    "delta_net_profit": bridge.delta_net_profit,
                    "identity_ok": bridge.identity_ok,
                    "components": [
                        {"code": item.code, "contribution": item.contribution} for item in bridge.components
                    ],
                },
                "ad_cuts": cuts,
                "stockouts": stockouts,
                "competitors": competitors,
            }
        )
    body = {
        "assembly": ASSEMBLY_VERSION,
        "engines": dict(FORMULA_VERSIONS),
        "period": {"start": start, "end": end},
        "as_of": as_of,
        "currencies_are_not_summed": True,
        "model_tokens": 0,
        "stores": stores,
        "approvals": _approval_summary(session),
    }
    rendered = to_jsonable(body)
    markdown = render_weekly_markdown(rendered)
    card = weekly_card(rendered)
    notification = None
    if push_feishu:
        notification = dispatch(
            "weekly_report",
            "CommerceOps weekly report",
            card["card"]["elements"][0]["text"]["content"],
            {
                "period": f"{rendered['period']['start']} .. {rendered['period']['end']}",
                "as_of": rendered["as_of"],
            },
        )
    rendered["markdown"] = markdown
    rendered["feishu_card"] = card
    rendered["notification"] = notification
    return rendered


def render_weekly_markdown(report: dict) -> str:
    engines = report["engines"]
    lines = [
        "# CommerceOps weekly report",
        f"Period: {report['period']['start']} .. {report['period']['end']}",
        f"As of: {report['as_of']}",
        "Engines: " + ", ".join(f"{key}={engines[key]}" for key in engines),
        "Currencies are reported separately and are not summed.",
        "Model tokens: 0",
        "",
        "## Profit bridge",
    ]
    for store in report["stores"]:
        profit = store["profit"]
        lines.append(f"### {store['code']} ({store['currency']})")
        lines.append(f"Current net profit: {profit['current_net_profit']}")
        lines.append(f"Previous net profit: {profit['previous_net_profit']}")
        lines.append(f"Delta: {profit['delta_net_profit']}")
        lines.append(f"Identity ok: {str(profit['identity_ok']).lower()}")
        for component in profit["components"]:
            lines.append(f"- {component['code']}: {component['contribution']}")
        lines.append("")
    lines.append("## Ad cuts")
    for store in report["stores"]:
        lines.append(f"### {store['code']} ({store['currency']})")
        if not store["ad_cuts"]:
            lines.append("No ad cuts.")
            lines.append("")
            continue
        for cut in store["ad_cuts"]:
            lines.append(
                f"- {cut['campaign_external_id']}: {cut['current_daily_budget']} -> {cut['suggested_daily_budget']} "
                f"({cut['reason']}), daily cut {cut['daily_cut']}"
            )
        lines.append("")
    lines.append("## Stockouts under 14 days")
    for store in report["stores"]:
        lines.append(f"### {store['code']}")
        if not store["stockouts"]:
            lines.append("No SKU under 14 days.")
            lines.append("")
            continue
        for item in store["stockouts"]:
            cover = item["days_of_cover"] if item["days_of_cover"] is not None else item["cover_status"]
            lines.append(
                f"- {item['sku']}: cover {cover} days, suggested {item['suggested_order_qty']}, status {item['cover_status']}"
            )
            if not item["suppliers"]:
                lines.append(f"  supplier status: {item['supplier_status']}")
                continue
            for quote in item["suppliers"]:
                lines.append(
                    f"  {quote['rank']}. {quote['supplier_code']} landed {quote['landed_cost']} "
                    f"qty {quote['adjusted_order_qty']} {quote['lead_time_risk']}"
                )
        lines.append("")
    lines.append("## Competitor alerts")
    for store in report["stores"]:
        lines.append(f"### {store['code']}")
        if not store["competitors"]:
            lines.append("No competitor alerts.")
            lines.append("")
            continue
        for block in store["competitors"]:
            sample = str(block["sample_data"]).lower()
            for alert in block["alerts"]:
                names = ", ".join(alert["alerts"])
                lines.append(
                    f"- {block['sku']} {alert['competitor_asin']}: {names}, "
                    f"price change {alert['price_change']}, source {alert['source']}, sample_data {sample}"
                )
        lines.append("")
    approvals = report["approvals"]
    lines.extend(
        [
            "## Approvals",
            f"Pending drafts: {approvals['pending']}",
            f"Executed drafts: {approvals['executed']}",
            f"Rejected drafts: {approvals['rejected']}",
            f"Audit rows: {approvals['audit_rows']}",
            f"Purchase orders: {approvals['purchase_orders']}",
            f"Purchase orders sent: {approvals['purchase_orders_sent']}",
            f"Budget revisions: {approvals['budget_revisions']}",
            f"Competitor responses: {approvals['competitor_responses']}",
        ]
    )
    if approvals["recent_events"]:
        lines.append("Recent audit events:")
        for event in approvals["recent_events"]:
            lines.append(f"- {event['created_at']} {event['event']} {event['actor']} {event['draft_id']}")
    else:
        lines.append("Recent audit events: none")
    lines.append("")
    lines.append("This report copies engine output. It does not call a model.")
    return "\n".join(lines).rstrip() + "\n"


def weekly_card(report: dict) -> dict:
    lines = []
    for store in report["stores"]:
        profit = store["profit"]
        lines.append(
            f"**{store['code']} {store['currency']}** net {profit['current_net_profit']} "
            f"(delta {profit['delta_net_profit']}), ad cuts {len(store['ad_cuts'])}, "
            f"stockouts {len(store['stockouts'])}"
        )
    approvals = report["approvals"]
    lines.append(
        f"Drafts pending {approvals['pending']} executed {approvals['executed']} rejected {approvals['rejected']}"
    )
    return build_card(
        "CommerceOps weekly report",
        "\n".join(lines),
        {
            "period": f"{report['period']['start']} .. {report['period']['end']}",
            "as_of": str(report["as_of"]),
        },
    )


def _approval_summary(session: Session) -> dict:
    workspace = current_workspace()
    counts = {"draft": 0, "executed": 0, "rejected": 0}
    for status in session.scalars(
        select(ActionDraft.status).where(ActionDraft.workspace_id == workspace)
    ).all():
        counts[status] = counts.get(status, 0) + 1
    recent = session.scalars(
        select(WritebackAuditLog)
        .where(WritebackAuditLog.workspace_id == workspace)
        .order_by(WritebackAuditLog.id.desc())
        .limit(8)
    ).all()
    sent = session.scalar(
        select(func.coalesce(func.sum(PurchaseOrder.sent_to_supplier), 0)).where(
            PurchaseOrder.workspace_id == workspace
        )
    )
    return {
        "pending": counts.get("draft", 0),
        "executed": counts.get("executed", 0),
        "rejected": counts.get("rejected", 0),
        "audit_rows": int(
            session.scalar(
                select(func.count()).select_from(WritebackAuditLog).where(WritebackAuditLog.workspace_id == workspace)
            )
            or 0
        ),
        "purchase_orders": int(
            session.scalar(
                select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.workspace_id == workspace)
            )
            or 0
        ),
        "purchase_orders_sent": int(sent or 0),
        "budget_revisions": int(
            session.scalar(
                select(func.count())
                .select_from(AdBudgetRevision)
                .join(ActionDraft, ActionDraft.id == AdBudgetRevision.draft_id)
                .where(ActionDraft.workspace_id == workspace)
            )
            or 0
        ),
        "competitor_responses": int(
            session.scalar(
                select(func.count())
                .select_from(CompetitorResponse)
                .join(ActionDraft, ActionDraft.id == CompetitorResponse.draft_id)
                .where(ActionDraft.workspace_id == workspace)
            )
            or 0
        ),
        "recent_events": [
            {
                "draft_id": row.draft_id,
                "event": row.event,
                "actor": row.actor,
                "created_at": row.created_at,
            }
            for row in reversed(recent)
        ],
    }
