import asyncio
from decimal import Decimal
import json
import sys

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from sqlalchemy import func, select

from commerceops.mcp_contract import ALL_TOOLS, FORBIDDEN_TOOLS
from commerceops.mcp_server import mcp
from commerceops.db import session_factory_for
from commerceops.models import AdCampaign, PurchaseOrder
from commerceops.seed import AS_OF, CURRENT_END, CURRENT_START, US_STORE, seed_demo_data


def _tool_text(result) -> str:
    assert result.is_error is not True
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    assert parts, result
    return "".join(parts)


def test_health_profit_import_and_execute_contract(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["service"] == "commerceops"
    assert "formula_versions" not in health.json()
    assert "bridge" in client.get("/api/v1/formulas").json()["formulas"]["profit.v1"]
    assert client.post("/api/v1/seed").status_code == 200
    profit = client.get(
        "/api/v1/profit",
        params={"store_code": US_STORE, "start_date": CURRENT_START.isoformat(), "end_date": CURRENT_END.isoformat()},
    )
    assert profit.status_code == 200
    body = profit.json()
    assert Decimal(body["current"]["net_profit"]) == Decimal("682.60")
    assert Decimal(body["previous"]["net_profit"]) == Decimal("1371.90")
    assert body["bridge"]["identity_ok"] is True
    assert client.get("/api/v1/sops/search", params={"q": "acossevere"}).json()["hits"][0]["doc_id"] == "sop-acos-optimization"

    missing = client.post(
        "/api/v1/import/orders",
        content="store_code,sku\n",
        headers={"content-type": "text/csv"},
    )
    assert missing.status_code == 422
    assert missing.json()["error"] == "import_invalid"

    draft = client.post(
        "/api/v1/ads/budget-drafts",
        json={
            "store_code": US_STORE,
            "campaign_external_id": "camp-bottle-exact",
            "start_date": CURRENT_START.isoformat(),
            "end_date": CURRENT_END.isoformat(),
            "created_by": "api",
        },
    )
    assert draft.status_code == 200
    draft_id = draft.json()["draft_id"]
    denied = client.post(f"/api/v1/drafts/{draft_id}/execute", json={"actor": "api"})
    assert denied.status_code == 409
    assert denied.json()["error"] == "unapproved_execution"
    approved = client.post(
        f"/api/v1/drafts/{draft_id}/approve-and-execute",
        json={"approver": "owner", "note": "apply the cut"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "executed"
    replay = client.post(
        f"/api/v1/drafts/{draft_id}/approve-and-execute",
        json={"approver": "owner", "note": "again"},
    )
    assert replay.json()["replayed"] is True
    assert replay.json()["execution_ref"] == approved.json()["execution_ref"]


def test_mcp_tool_surface_and_in_process_writeback(seeded, database_url, monkeypatch):
    monkeypatch.setenv("COMMERCEOPS_DATABASE_URL", database_url)

    async def _roundtrip():
        listed = await mcp.list_tools()
        names = tuple(tool.name for tool in listed)
        assert names == ALL_TOOLS
        assert not set(names) & set(FORBIDDEN_TOOLS)
        by_name = {tool.name: tool for tool in listed}
        assert by_name["commerceops_profit_report"].annotations.read_only_hint is True
        assert by_name["commerceops_create_purchase_order_draft"].annotations.destructive_hint is False
        assert "commerceops_approve_and_execute_draft" not in names
        sop = await mcp.call_tool("commerceops_search_sops", {"query": "stockoutreorder", "limit": 1})
        quote = json.loads(_tool_text(sop))["hits"][0]
        assert quote["doc_id"] == "sop-stockout-supplier"
        assert "stockoutreorder" in quote["quote"]
        created = json.loads(
            _tool_text(
                await mcp.call_tool(
                    "commerceops_create_purchase_order_draft",
                    {"store_code": US_STORE, "sku": "NS-CABLE-3PK", "as_of": AS_OF.isoformat(), "created_by": "agent"},
                )
            )
        )
        assert created["status"] == "draft"
        from mcp.server.mcpserver.exceptions import ToolError

        with pytest.raises(ToolError):
            await mcp.call_tool(
                "commerceops_approve_and_execute_draft",
                {"draft_id": created["draft_id"], "approver": "owner", "note": "agent must not approve"},
            )
        return created

    created = asyncio.run(_roundtrip())
    from commerceops.api.app import create_app
    from tests.conftest import SignedClient

    client = SignedClient(create_app(database_url))
    approved = client.post(
        f"/api/v1/drafts/{created['draft_id']}/approve-and-execute",
        json={"approver": "member", "note": "human approved"},
    )
    assert approved.status_code == 200
    replay = client.post(
        f"/api/v1/drafts/{created['draft_id']}/approve-and-execute",
        json={"approver": "owner", "note": "replay"},
    )
    assert replay.status_code == 200
    assert seeded.scalar(select(func.count()).select_from(PurchaseOrder)) == 1
    assert approved.json()["status"] == "executed"
    assert replay.json()["replayed"] is True
    assert replay.json()["execution_ref"] == approved.json()["execution_ref"]
    campaign = seeded.scalar(select(AdCampaign).where(AdCampaign.external_id == "camp-bottle-exact"))
    assert campaign.daily_budget == Decimal("45")


def test_mcp_stdio_price_sim_and_weekly_report(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path}/stdio.db"
    session = session_factory_for(database_url)()
    try:
        seed_demo_data(session)
    finally:
        session.close()
    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)

    async def _stdio():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "commerceops.mcp_server"],
            env={
                "COMMERCEOPS_DATABASE_URL": database_url,
                "COMMERCEOPS_NOTIFY_LOG": str(tmp_path / "notify.jsonl"),
                "COMMERCEOPS_WORKSPACE_ID": "ws-demo",
                "COMMERCEOPS_SIGNING_SECRET": "test-signing-secret-32chars",
            },
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as mcp_session:
                await mcp_session.initialize()
                listed = await mcp_session.list_tools()
                names = {tool.name for tool in listed.tools}
                assert "simulate_price_change" in names
                assert "generate_weekly_report" in names
                simulated = json.loads(
                    _tool_text(
                        await mcp_session.call_tool(
                            "simulate_price_change",
                            {
                                "store_code": US_STORE,
                                "sku": "NS-BOTTLE-1L",
                                "target_price": "18.00",
                                "start_date": CURRENT_START.isoformat(),
                                "end_date": CURRENT_END.isoformat(),
                            },
                        )
                    )
                )
                weekly = json.loads(
                    _tool_text(
                        await mcp_session.call_tool(
                            "generate_weekly_report",
                            {"push_feishu": True, "as_of": AS_OF.isoformat()},
                        )
                    )
                )
                return simulated, weekly

    simulated, weekly = asyncio.run(_stdio())
    assert simulated["formula_version"] == "price_sim.v1"
    assert Decimal(simulated["profit_delta"]) == Decimal("-40.81")
    assert [row["name"] for row in simulated["scenarios"]] == ["conservative", "base", "optimistic"]
    assert "682.60" in weekly["markdown"]
    assert weekly["notification"]["mode"] == "dry_run"
    assert weekly["approvals"]["purchase_orders"] == 0
    assert weekly["model_tokens"] == 0


def test_mcp_stdio_lists_tools_and_returns_a_citation():
    async def _stdio():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "commerceops.mcp_server"],
            env={
                "COMMERCEOPS_WORKSPACE_ID": "ws-demo",
                "COMMERCEOPS_SIGNING_SECRET": "test-signing-secret-32chars",
            },
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                assert set(ALL_TOOLS) <= names
                assert not names & set(FORBIDDEN_TOOLS)
                result = await session.call_tool("commerceops_search_sops", {"query": "competitorpricedrop", "limit": 1})
                payload = json.loads(_tool_text(result))
                hit = payload["hits"][0]
                assert hit["doc_id"] == "sop-competitor-response"
                assert "competitorpricedrop" in hit["quote"]

    asyncio.run(_stdio())
