"""Scripted tool-selection chain. This is not a live LLM evaluation."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from commerceops.mcp_contract import FORBIDDEN_TOOLS
from commerceops.mcp_server import commerceops_profit_report, commerceops_search_sops, mcp
from commerceops.seed import CURRENT_END, CURRENT_START, US_STORE

LABEL = "scripted_invocation_chain"


def _route(question: str) -> str:
    text = question.lower()
    if "sop" in text or "流程" in question:
        return "commerceops_search_sops"
    if "profit" in text or "利润" in question:
        return "commerceops_profit_report"
    if "approve" in text or "批准" in question:
        return "refuse_approval"
    return "refuse_insufficient_data"


def test_scripted_chain_is_not_labeled_as_a_live_llm_eval():
    assert LABEL != "live_llm_agent_evaluation"
    assert _route("what is the profit bridge") == "commerceops_profit_report"
    assert _route("引用 SOP") == "commerceops_search_sops"
    assert _route("请批准并执行") == "refuse_approval"
    assert _route("???") == "refuse_insufficient_data"


def test_scripted_chain_uses_real_tools_and_blocks_agent_approval(seeded, database_url, monkeypatch):
    del seeded
    monkeypatch.setenv("COMMERCEOPS_DATABASE_URL", database_url)
    profit = json.loads(commerceops_profit_report(US_STORE, CURRENT_START.isoformat(), CURRENT_END.isoformat()))
    assert profit["current"]["net_profit"] == "682.60"
    follow_up = json.loads(commerceops_search_sops("退款尖峰", 1))
    assert follow_up["hits"][0]["doc_id"] == "sop-profit-drop"
    assert follow_up["hits"][0]["section"]
    citation = json.loads(commerceops_search_sops("acossevere", 1))
    assert citation["hits"][0]["doc_id"] == "sop-acos-optimization"
    assert "acossevere" in citation["hits"][0]["quote"]

    async def _missing():
        listed = {tool.name for tool in await mcp.list_tools()}
        assert "commerceops_approve_and_execute_draft" not in listed
        assert "commerceops_approve_and_execute_draft" in FORBIDDEN_TOOLS
        with pytest.raises(ToolError):
            await mcp.call_tool(
                "commerceops_approve_and_execute_draft",
                {"draft_id": "missing", "approver": "owner"},
            )

    asyncio.run(_missing())
