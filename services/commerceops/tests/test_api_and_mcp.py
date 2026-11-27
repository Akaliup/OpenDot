import asyncio
from decimal import Decimal
import json
import sys

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from sqlalchemy import func, select

from commerceops.mcp_contract import ALL_TOOLS, FORBIDDEN_TOOLS
from commerceops.mcp_server import mcp
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
    assert health.json()["formula_versions"]["profit"] == "profit.v1"
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
        assert by_name["commerceops_approve_and_execute_draft"].annotations.destructive_hint is True
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
        approved = json.loads(
            _tool_text(
                await mcp.call_tool(
                    "commerceops_approve_and_execute_draft",
                    {"draft_id": created["draft_id"], "approver": "owner", "note": "human approved"},
                )
            )
        )
        replayed = json.loads(
            _tool_text(
                await mcp.call_tool(
                    "commerceops_approve_and_execute_draft",
                    {"draft_id": created["draft_id"], "approver": "owner", "note": "replay"},
                )
            )
        )
        return created, approved, replayed

    _created, approved, replayed = asyncio.run(_roundtrip())
    assert seeded.scalar(select(func.count()).select_from(PurchaseOrder)) == 1
    assert approved["status"] == "executed"
    assert replayed["replayed"] is True
    assert replayed["execution_ref"] == approved["execution_ref"]
    campaign = seeded.scalar(select(AdCampaign).where(AdCampaign.external_id == "camp-bottle-exact"))
    assert campaign.daily_budget == Decimal("45")


def test_mcp_stdio_lists_tools_and_returns_a_citation():
    async def _stdio():
        params = StdioServerParameters(command=sys.executable, args=["-m", "commerceops.mcp_server"])
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
