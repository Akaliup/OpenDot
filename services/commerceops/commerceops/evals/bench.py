"""Tool-contract scorecard. No model is called.

Each case seeds its own SQLite file, calls the same functions the MCP tools
use, and records pass/fail assertions. Ops minutes are planning estimates for
the manual work the tools replace. Measured model tokens are zero.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile

from sqlalchemy import func, select

from commerceops.clock import utc_now
from commerceops.db import session_factory_for
from commerceops.errors import CommerceOpsError, NoActionRequired
from commerceops.governance import (
    approve_and_execute_draft,
    create_ad_budget_draft,
    create_purchase_order_draft,
    execute_draft,
    get_draft,
    list_audit,
    reject_draft,
)
from commerceops.models import AdBudgetRevision, AdCampaign, PurchaseOrder
from commerceops.reporting import ads_report, competitor_report, inventory_report, price_simulation, profit_report, supplier_report
from commerceops.weekly_report import generate_weekly_report
from commerceops.seed import AS_OF, CURRENT_END, CURRENT_START, UK_STORE, US_STORE, seed_demo_data
from commerceops.sop.retrieval import search_sops

RELAY_TOKENS_PER_CASE = 400


def _check(name: str, passed: bool, expected: str, actual: str) -> dict:
    return {"name": name, "passed": passed, "expected": expected, "actual": actual}


def _case(case_id: str, title: str, minutes: int, *, formula: bool, policy: bool, assertions: list[dict]) -> dict:
    return {
        "id": case_id,
        "title": title,
        "passed": all(item["passed"] for item in assertions),
        "formula_check": formula,
        "policy_guard": policy,
        "ops_minutes_saved": minutes,
        "estimated_relay_tokens": RELAY_TOKENS_PER_CASE,
        "measured_model_tokens": 0,
        "assertions": assertions,
    }


def _fresh(work) -> dict:  # type: ignore[no-untyped-def]
    with tempfile.TemporaryDirectory() as directory:
        url = f"sqlite:///{directory}/bench.db"
        session = session_factory_for(url)()
        try:
            seed_demo_data(session)
            return work(session, url)
        finally:
            session.close()


def case_profit_bridge(_session, _url) -> dict:
    def work(session, _url) -> dict:
        report = profit_report(session, US_STORE, CURRENT_START, CURRENT_END, compare=True)
        contributions = {item.code: item.contribution for item in report["bridge"].components}
        expected = {
            "revenue": Decimal("-70"),
            "discounts": Decimal("14"),
            "refunds": Decimal("-300"),
            "net_cogs": Decimal("41.20"),
            "platform_fees": Decimal("10.50"),
            "shipping_fees": Decimal("7"),
            "ad_spend": Decimal("-392"),
            "other_fees": Decimal("0"),
        }
        total = sum(contributions.values(), Decimal(0))

        def plain(value: Decimal) -> str:
            return "0" if value == 0 else format(value, "f")

        actual_parts = ", ".join(f"{code}={plain(contributions[code])}" for code in expected)
        expected_parts = ", ".join(f"{code}={plain(expected[code])}" for code in expected)
        assertions = [
            _check("current_net_profit", report["current"].net_profit == Decimal("682.60"), "682.60", plain(report["current"].net_profit)),
            _check("previous_net_profit", report["previous"].net_profit == Decimal("1371.90"), "1371.90", plain(report["previous"].net_profit)),
            _check("delta", report["bridge"].delta_net_profit == Decimal("-689.30"), "-689.30", plain(report["bridge"].delta_net_profit)),
            _check("components", contributions == expected, expected_parts, actual_parts),
            _check("identity", total == report["bridge"].delta_net_profit, plain(report["bridge"].delta_net_profit), plain(total)),
        ]
        return _case("profit_bridge_us", "US profit bridge is -689.30", 25, formula=True, policy=False, assertions=assertions)

    return _fresh(work)


def case_uk_flat(_session, _url) -> dict:
    def work(session, _url) -> dict:
        report = profit_report(session, UK_STORE, CURRENT_START, CURRENT_END, compare=True)
        assertions = [
            _check("currency", report["currency"] == "GBP", "GBP", report["currency"]),
            _check("flat", report["current"].net_profit == report["previous"].net_profit == Decimal("126"), "126", str(report["current"].net_profit)),
        ]
        return _case("profit_uk_flat", "UK profit stays flat", 8, formula=True, policy=False, assertions=assertions)

    return _fresh(work)


def case_ads(_session, _url) -> dict:
    def work(session, url) -> dict:
        report = ads_report(session, US_STORE, CURRENT_START, CURRENT_END)
        by_id = {row["campaign_external_id"]: row for row in report["campaigns"]}
        exact = by_id["camp-bottle-exact"]
        campaign = session.scalar(select(AdCampaign).where(AdCampaign.external_id == "camp-bottle-exact"))
        before = campaign.daily_budget
        created = create_ad_budget_draft(
            session,
            store_code=US_STORE,
            campaign_external_id="camp-bottle-exact",
            start=CURRENT_START,
            end=CURRENT_END,
            created_by="eval",
        )
        session.refresh(campaign)
        yoga_refused = False
        try:
            create_ad_budget_draft(
                session,
                store_code=US_STORE,
                campaign_external_id="camp-yoga",
                start=CURRENT_START,
                end=CURRENT_END,
                created_by="eval",
            )
        except NoActionRequired:
            yoga_refused = True
        from fastapi.testclient import TestClient

        from commerceops.api.app import create_app

        client = TestClient(create_app(url))
        denied = client.post(
            f"/api/v1/drafts/{created['draft_id']}/execute",
            json={"actor": "eval"},
        )
        audit = client.get(f"/api/v1/drafts/{created['draft_id']}/audit").json()
        assertions = [
            _check("exact_acos", exact["current"].acos.value == Decimal("0.75"), "0.75", str(exact["current"].acos.value)),
            _check("exact_cut", exact["budget"].suggested_daily_budget == Decimal("31.50"), "31.50", str(exact["budget"].suggested_daily_budget)),
            _check("broad_severe", by_id["camp-bottle-broad"]["budget"].reason == "severe_acos", "severe_acos", by_id["camp-bottle-broad"]["budget"].reason),
            _check("yoga_refused", yoga_refused, "no draft", str(yoga_refused)),
            _check("budget_unchanged", campaign.daily_budget == before, str(before), str(campaign.daily_budget)),
            _check("http_409", denied.status_code == 409, "409", str(denied.status_code)),
            _check(
                "audit_rejection",
                any(entry["detail"].get("reason") == "unapproved" for entry in audit["entries"]),
                "unapproved",
                str([entry["event"] for entry in audit["entries"]]),
            ),
        ]
        return _case(
            "ads_anomaly_and_unapproved_guard",
            "High ACOS detection and unapproved execute fails closed",
            30,
            formula=True,
            policy=True,
            assertions=assertions,
        )

    return _fresh(work)


def case_stockout(_session, _url) -> dict:
    def work(session, _url) -> dict:
        report = inventory_report(session, US_STORE, AS_OF)
        cable = next(row for row in report["skus"] if row["sku"] == "NS-CABLE-3PK")
        assertions = [
            _check("at_risk", report["at_risk_skus"] == ["NS-CABLE-3PK", "NS-LAMP-LED"], "cable, lamp", str(report["at_risk_skus"])),
            _check("cover", cable["cover"].days_of_cover == Decimal("3.6"), "3.6", str(cable["cover"].days_of_cover)),
            _check("reorder", cable["replenishment"].reorder_point == Decimal("75"), "75", str(cable["replenishment"].reorder_point)),
            _check("within_14", cable["cover"].days_of_cover <= 14, "<= 14", str(cable["cover"].days_of_cover)),
        ]
        return _case("stockout_14d", "SKUs inside a 14-day cover horizon", 20, formula=True, policy=False, assertions=assertions)

    return _fresh(work)


def case_suppliers(_session, _url) -> dict:
    def work(session, _url) -> dict:
        report = supplier_report(session, US_STORE, "NS-CABLE-3PK", AS_OF)
        ranked = report["rank"].rankings
        assertions = [
            _check("order", [row.supplier_code for row in ranked] == ["SUP-SZR", "SUP-VNF", "SUP-NBV"], "SZR, VNF, NBV", str([row.supplier_code for row in ranked])),
            _check("qty", [row.adjusted_order_qty for row in ranked] == [200, 240, 300], "200, 240, 300", str([row.adjusted_order_qty for row in ranked])),
            _check("landed", ranked[0].landed_cost == Decimal("2.82"), "2.82", str(ranked[0].landed_cost)),
            _check(
                "weights",
                all(row.score == sum(report["rank"].weights[key] * row.components[key] for key in report["rank"].weights) for row in ranked),
                "score equals weights",
                "checked",
            ),
        ]
        return _case("supplier_rank", "Cable supplier ranking and MOQ quantity", 25, formula=True, policy=False, assertions=assertions)

    return _fresh(work)


def case_competitor(_session, _url) -> dict:
    def work(session, _url) -> dict:
        report = competitor_report(session, US_STORE, "NS-LAMP-LED", AS_OF)
        by_asin = {row["competitor_asin"]: row for row in report["comparisons"]}
        primary = by_asin["B0COMP001"]["alerts"]
        assertions = [
            _check("sample", report["sample_data"] is True, "true", str(report["sample_data"])),
            _check("price_bsr_complaints", primary == ["price_drop", "bsr_jump", "complaint_spike"], "three alerts", str(primary)),
            _check("rating", by_asin["B0COMP003"]["alerts"] == ["rating_drop"], "rating_drop", str(by_asin["B0COMP003"]["alerts"])),
            _check("source", by_asin["B0COMP001"]["source"] == "demo_seed", "demo_seed", by_asin["B0COMP001"]["source"]),
        ]
        return _case("competitor_diff", "Competitor price drop, BSR jump, and complaint spike", 15, formula=True, policy=False, assertions=assertions)

    return _fresh(work)


def case_sop(_session, _url) -> dict:
    english = search_sops("acossevere", limit=1)["hits"][0]
    chinese = search_sops("退款尖峰", limit=1)["hits"][0]
    assertions = [
        _check("english_doc", english.doc_id == "sop-acos-optimization", "sop-acos-optimization", english.doc_id),
        _check("english_quote", "acossevere" in english.quote, "quote contains control code", english.quote),
        _check("chinese_doc", chinese.doc_id == "sop-profit-drop", "sop-profit-drop", chinese.doc_id),
        _check("chinese_section", chinese.section == "Refund Spike Check", "Refund Spike Check", chinese.section),
    ]
    return _case("sop_citations", "English and Chinese SOP citations", 10, formula=True, policy=False, assertions=assertions)


def case_replay(_session, _url) -> dict:
    def work(session, _url) -> dict:
        created = create_ad_budget_draft(
            session,
            store_code=US_STORE,
            campaign_external_id="camp-lamp",
            start=CURRENT_START,
            end=CURRENT_END,
            created_by="eval",
        )
        first = approve_and_execute_draft(session, created["draft_id"], "owner", "eval")
        second = approve_and_execute_draft(session, created["draft_id"], "owner", "replay")
        revisions = session.scalar(select(func.count()).select_from(AdBudgetRevision))
        assertions = [
            _check("first", first["replayed"] is False, "false", str(first["replayed"])),
            _check("second", second["replayed"] is True, "true", str(second["replayed"])),
            _check("same_ref", first["execution_ref"] == second["execution_ref"], first["execution_ref"], second["execution_ref"] or ""),
            _check("one_revision", revisions == 1, "1", str(revisions)),
        ]
        return _case("approval_replay", "Duplicate approval does not write twice", 12, formula=False, policy=True, assertions=assertions)

    return _fresh(work)


def case_rejected_and_stale(_session, _url) -> dict:
    def work(session, _url) -> dict:
        lamp = create_ad_budget_draft(
            session,
            store_code=US_STORE,
            campaign_external_id="camp-lamp",
            start=CURRENT_START,
            end=CURRENT_END,
            created_by="eval",
        )
        reject_draft(session, lamp["draft_id"], "owner", "no")
        rejected_code = ""
        try:
            approve_and_execute_draft(session, lamp["draft_id"], "owner", "later")
        except CommerceOpsError as exc:
            rejected_code = exc.code
        broad = create_ad_budget_draft(
            session,
            store_code=US_STORE,
            campaign_external_id="camp-bottle-broad",
            start=CURRENT_START,
            end=CURRENT_END,
            created_by="eval",
        )
        campaign = session.scalar(select(AdCampaign).where(AdCampaign.external_id == "camp-bottle-broad"))
        campaign.daily_budget = Decimal("80")
        session.commit()
        stale_code = ""
        try:
            approve_and_execute_draft(session, broad["draft_id"], "owner", "stale")
        except CommerceOpsError as exc:
            stale_code = exc.code
        revisions = session.scalar(select(func.count()).select_from(AdBudgetRevision))
        assertions = [
            _check("rejected", rejected_code == "draft_rejected", "draft_rejected", rejected_code),
            _check("stale", stale_code == "stale_draft", "stale_draft", stale_code),
            _check("no_revision", revisions == 0, "0", str(revisions)),
        ]
        return _case("rejected_and_stale", "Rejected and stale drafts do not write", 12, formula=False, policy=True, assertions=assertions)

    return _fresh(work)


def case_restart(_session, _url) -> dict:
    def work(session, url) -> dict:
        created = create_purchase_order_draft(
            session,
            store_code=US_STORE,
            sku="NS-CABLE-3PK",
            as_of=AS_OF,
            supplier_code=None,
            created_by="eval",
        )
        draft_id = created["draft_id"]
        session.close()
        reopened = session_factory_for(url)()
        try:
            loaded = get_draft(reopened, draft_id)
            pending_orders = reopened.scalar(select(func.count()).select_from(PurchaseOrder))
            first = approve_and_execute_draft(reopened, draft_id, "owner", "after restart")
            second = approve_and_execute_draft(reopened, draft_id, "owner", "replay after restart")
            orders = reopened.scalar(select(func.count()).select_from(PurchaseOrder))
            audit = [entry["event"] for entry in list_audit(reopened, draft_id)["entries"]]
        finally:
            reopened.close()
        assertions = [
            _check("still_draft", loaded["status"] == "draft", "draft", loaded["status"]),
            _check("no_po_before", pending_orders == 0, "0", str(pending_orders)),
            _check("one_po", orders == 1, "1", str(orders)),
            _check("replay", second["replayed"] is True and second["execution_ref"] == first["execution_ref"], "same ref", second["execution_ref"] or ""),
            _check("audit_has_create", "draft_created" in audit, "draft_created", str(audit)),
        ]
        return _case(
            "restart_pending_draft",
            "A pending draft survives a new session and still writes once",
            15,
            formula=False,
            policy=True,
            assertions=assertions,
        )

    return _fresh(work)


def case_price_sim(_session, _url) -> dict:
    def work(session, _url) -> dict:
        result = price_simulation(session, US_STORE, "NS-BOTTLE-1L", Decimal("18"), CURRENT_START, CURRENT_END)
        by_name = {item.name: item for item in result["scenarios"]}
        margin = Decimal("167.9") / Decimal("669.6")
        assertions = [
            _check("version", result["formula_version"] == "price_sim.v1", "price_sim.v1", result["formula_version"]),
            _check("unit_margin", result["new_unit_margin"].value == margin, "167.9/669.6", str(result["new_unit_margin"].value)),
            _check("profit_delta", result["profit_delta"] == Decimal("-40.81"), "-40.81", str(result["profit_delta"])),
            _check(
                "break_even_acos",
                result["break_even_acos"].value == margin and result["break_even_acos"].status == "ok",
                "167.9/669.6",
                str(result["break_even_acos"].value),
            ),
            _check("base_units", by_name["base"].units == Decimal("61.6"), "61.6", str(by_name["base"].units)),
            _check("conservative_delta", by_name["conservative"].profit_delta == Decimal("-30.736"), "-30.736", str(by_name["conservative"].profit_delta)),
            _check("optimistic_delta", by_name["optimistic"].profit_delta == Decimal("-50.884"), "-50.884", str(by_name["optimistic"].profit_delta)),
            _check("current_acos", result["current_acos"].value == Decimal("665") / Decimal("525"), "665/525", str(result["current_acos"].value)),
        ]
        return _case(
            "price_sim_bottle_cut",
            "Bottle price 20 to 18 keeps Decimal unit margin, delta, and elasticities",
            20,
            formula=True,
            policy=False,
            assertions=assertions,
        )

    return _fresh(work)


def case_price_sim_edges(_session, _url) -> dict:
    def work(session, _url) -> dict:
        same = price_simulation(session, US_STORE, "NS-BOTTLE-1L", Decimal("20.00"), CURRENT_START, CURRENT_END)
        negative = ""
        try:
            price_simulation(session, US_STORE, "NS-BOTTLE-1L", Decimal("-1"), CURRENT_START, CURRENT_END)
        except CommerceOpsError as exc:
            negative = exc.code
        missing = ""
        try:
            price_simulation(session, US_STORE, "NO-SUCH-SKU", Decimal("10"), CURRENT_START, CURRENT_END)
        except CommerceOpsError as exc:
            missing = exc.code
        quiet = price_simulation(session, US_STORE, "NS-BOTTLE-1L", Decimal("18"), date(2026, 1, 1), date(2026, 1, 2))
        assertions = [
            _check(
                "same_price_delta",
                all(item.profit_delta == 0 for item in same["scenarios"]),
                "0",
                str([item.profit_delta for item in same["scenarios"]]),
            ),
            _check(
                "same_margin",
                same["new_unit_margin"].value == same["baseline_unit_margin"].value,
                "unchanged",
                str(same["new_unit_margin"].value),
            ),
            _check("negative_price", negative == "invalid_price", "invalid_price", negative),
            _check("unknown_sku", missing == "sku_not_found", "sku_not_found", missing),
            _check("zero_units", quiet["status"] == "zero_units" and quiet["profit_delta"] is None, "zero_units", quiet["status"]),
        ]
        return _case(
            "price_sim_identity_and_edges",
            "Unchanged price has delta 0 and empty windows do not invent rates",
            12,
            formula=True,
            policy=False,
            assertions=assertions,
        )

    return _fresh(work)


def _markdown_numbers_are_sourced(report: dict) -> tuple[bool, str]:
    import re

    source = {key: value for key, value in report.items() if key not in {"markdown", "feishu_card", "notification"}}
    blob = json.dumps(source, ensure_ascii=False)
    missing = [token for token in re.findall(r"-?\d+\.\d+", report["markdown"]) if token not in blob]
    return not missing, str(missing)


def case_weekly_report(_session, _url) -> dict:
    def work(session, _url) -> dict:
        report = generate_weekly_report(
            session,
            start=CURRENT_START,
            end=CURRENT_END,
            as_of=AS_OF,
            push_feishu=False,
        )
        markdown = report["markdown"]
        us = next(store for store in report["stores"] if store["code"] == US_STORE)
        uk = next(store for store in report["stores"] if store["code"] == UK_STORE)
        sourced, missing = _markdown_numbers_are_sourced(report)
        forbidden = ("approximately", "roughly", "estimated", "maybe", "I think", "大约", "大概")
        leaked = [word for word in forbidden if word.lower() in markdown.lower()]
        assertions = [
            _check("us_profit", "682.60" in markdown and "1371.90" in markdown and "-689.30" in markdown, "bridge figures", "present" if "682.60" in markdown else markdown[:80]),
            _check("uk_flat", uk["profit"]["current_net_profit"] == "126.00" and uk["profit"]["previous_net_profit"] == "126.00" and uk["currency"] == "GBP", "126.00 GBP", uk["profit"]["current_net_profit"]),
            _check("no_fx_sum", report["currencies_are_not_summed"] is True and "combined" not in markdown.lower(), "separate currencies", "ok"),
            _check(
                "ad_cuts",
                [row["campaign_external_id"] for row in us["ad_cuts"]] == ["camp-bottle-broad", "camp-bottle-exact", "camp-lamp"],
                "broad, exact, lamp",
                str([row["campaign_external_id"] for row in us["ad_cuts"]]),
            ),
            _check(
                "stockouts",
                [row["sku"] for row in us["stockouts"]] == ["NS-CABLE-3PK", "NS-LAMP-LED"],
                "cable, lamp",
                str([row["sku"] for row in us["stockouts"]]),
            ),
            _check(
                "supplier",
                us["stockouts"][0]["suppliers"][0]["supplier_code"] == "SUP-SZR",
                "SUP-SZR",
                us["stockouts"][0]["suppliers"][0]["supplier_code"],
            ),
            _check(
                "competitor",
                "B0COMP001" in markdown and "price_drop" in markdown and "NS-LAMP-LED" in markdown,
                "lamp competitor alerts",
                "present" if "B0COMP001" in markdown else "missing",
            ),
            _check("sections", all(heading in markdown for heading in ("## Profit bridge", "## Ad cuts", "## Stockouts under 14 days", "## Competitor alerts", "## Approvals")), "five sections", "checked"),
            _check("sourced", sourced, "every decimal is in the JSON", missing),
            _check("no_narrative", leaked == [], "no invented wording", str(leaked)),
            _check("tokens", report["model_tokens"] == 0, "0", str(report["model_tokens"])),
        ]
        return _case(
            "weekly_report_completeness",
            "Weekly report includes both stores and only sourced figures",
            25,
            formula=True,
            policy=False,
            assertions=assertions,
        )

    return _fresh(work)


def case_weekly_approval_dry_run(_session, _url) -> dict:
    def work(session, _url) -> dict:
        created = create_purchase_order_draft(
            session,
            store_code=US_STORE,
            sku="NS-CABLE-3PK",
            as_of=AS_OF,
            supplier_code=None,
            created_by="eval",
        )
        before_orders = session.scalar(select(func.count()).select_from(PurchaseOrder))
        report = generate_weekly_report(
            session,
            start=CURRENT_START,
            end=CURRENT_END,
            as_of=AS_OF,
            push_feishu=True,
        )
        after_orders = session.scalar(select(func.count()).select_from(PurchaseOrder))
        still = get_draft(session, created["draft_id"])
        assertions = [
            _check("pending", report["approvals"]["pending"] == 1, "1", str(report["approvals"]["pending"])),
            _check("not_executed", report["approvals"]["purchase_orders"] == 0, "0", str(report["approvals"]["purchase_orders"])),
            _check("draft_kept", still["status"] == "draft", "draft", still["status"]),
            _check("no_write", before_orders == after_orders == 0, "0", str(after_orders)),
            _check("dry_run", report["notification"]["mode"] == "dry_run", "dry_run", report["notification"]["mode"]),
            _check("card", report["feishu_card"]["msg_type"] == "interactive", "interactive", report["feishu_card"]["msg_type"]),
            _check("sent_flag", report["approvals"]["purchase_orders_sent"] == 0, "0", str(report["approvals"]["purchase_orders_sent"])),
        ]
        return _case(
            "weekly_report_approval_dry_run",
            "Weekly report counts a pending draft and does not write or send",
            15,
            formula=False,
            policy=True,
            assertions=assertions,
        )

    return _fresh(work)


CASES = (
    case_profit_bridge,
    case_uk_flat,
    case_ads,
    case_stockout,
    case_suppliers,
    case_competitor,
    case_sop,
    case_replay,
    case_rejected_and_stale,
    case_restart,
    case_price_sim,
    case_price_sim_edges,
    case_weekly_report,
    case_weekly_approval_dry_run,
)


def run_bench(out_dir: Path | None = None) -> dict:
    directory = out_dir or Path(os.environ.get("COMMERCEOPS_EVAL_DIR", "commerceops-evals"))
    directory.mkdir(parents=True, exist_ok=True)
    cases = [fn(None, None) for fn in CASES]
    passed = sum(1 for case in cases if case["passed"])
    scorecard = {
        "formula_version": "eval.v1",
        "generated_at": utc_now(),
        "period": {"start": CURRENT_START.isoformat(), "end": CURRENT_END.isoformat(), "as_of": AS_OF.isoformat()},
        "summary": {
            "cases": len(cases),
            "passed": passed,
            "failed": len(cases) - passed,
            "ops_minutes_saved": sum(case["ops_minutes_saved"] for case in cases if case["passed"]),
            "measured_model_tokens": 0,
            "estimated_relay_tokens": sum(case["estimated_relay_tokens"] for case in cases),
            "token_note": (
                "Measured model tokens are 0 because this bench calls the tools directly. "
                "estimated_relay_tokens is a ceiling if a model only copied each tool result."
            ),
        },
        "cases": cases,
    }
    (directory / "scorecard.json").write_text(json.dumps(scorecard, indent=2), encoding="utf-8")
    (directory / "scorecard.html").write_text(render_html(scorecard), encoding="utf-8")
    return scorecard


def load_latest(out_dir: Path | None = None) -> dict | None:
    directory = out_dir or Path(os.environ.get("COMMERCEOPS_EVAL_DIR", "commerceops-evals"))
    path = directory / "scorecard.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def render_html(scorecard: dict) -> str:
    summary = scorecard["summary"]
    rows = []
    for case in scorecard["cases"]:
        status = "pass" if case["passed"] else "fail"
        checks = "".join(
            f"<li class='{ 'pass' if item['passed'] else 'fail' }'>{_esc(item['name'])}: expected {_esc(item['expected'])}; actual {_esc(item['actual'])}</li>"
            for item in case["assertions"]
        )
        rows.append(
            "<article>"
            f"<h2><span class='{status}'>{status}</span> {_esc(case['title'])}</h2>"
            f"<p>{_esc(case['id'])} · formula {case['formula_check']} · policy {case['policy_guard']} · {case['ops_minutes_saved']} min</p>"
            f"<ul>{checks}</ul></article>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>CommerceOps eval scorecard</title>
<style>
body {{ font: 15px/1.5 ui-sans-serif, sans-serif; margin: 2rem auto; max-width: 52rem; color: #1c2430; }}
h1 {{ font-size: 1.4rem; }}
.pass {{ color: #0f6b3c; }} .fail {{ color: #9f1d1d; }}
article {{ border-top: 1px solid #d5dbe3; padding: 0.8rem 0; }}
li {{ margin: 0.2rem 0; }}
</style>
</head>
<body>
<h1>CommerceOps eval scorecard</h1>
<p>{summary['passed']}/{summary['cases']} passed. Ops minutes saved {summary['ops_minutes_saved']}. Measured model tokens {summary['measured_model_tokens']}. Relay ceiling {summary['estimated_relay_tokens']}.</p>
<p>{_esc(summary['token_note'])}</p>
{''.join(rows)}
</body>
</html>
"""


def _esc(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def main() -> None:
    scorecard = run_bench()
    print(json.dumps(scorecard["summary"], indent=2))


if __name__ == "__main__":
    main()
