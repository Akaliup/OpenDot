import json

from commerceops.evals.bench import CASES, load_latest, run_bench
from commerceops.notify import build_card, clear_notifications, dispatch, recent_notifications


def test_feishu_dry_run_does_not_call_the_network(monkeypatch, tmp_path):
    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("COMMERCEOPS_NOTIFY_LOG", str(tmp_path / "notify.jsonl"))
    clear_notifications()
    called = {"n": 0}

    def sender(_url, _card):
        called["n"] += 1

    record = dispatch("draft_created", "CommerceOps draft", "budget 45 -> 31.50", {"draft_id": "d1"}, sender=sender)
    assert record["mode"] == "dry_run"
    assert called["n"] == 0
    assert record["card"]["msg_type"] == "interactive"
    assert recent_notifications()[0]["title"] == "CommerceOps draft"
    lines = (tmp_path / "notify.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["mode"] == "dry_run"
    card = build_card("t", "body", {"k": "v"})
    assert card["card"]["elements"][1]["fields"][0]["text"]["content"].startswith("**k**")


def test_feishu_webhook_uses_the_sender(monkeypatch):
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://example.invalid/hook")
    monkeypatch.delenv("COMMERCEOPS_NOTIFY_LOG", raising=False)
    clear_notifications()
    seen = {}

    def sender(url, card):
        seen["url"] = url
        seen["card"] = card

    record = dispatch("draft_executed", "done", "applied", {"draft_id": "d2"}, sender=sender)
    assert record["mode"] == "sent"
    assert seen["url"] == "https://example.invalid/hook"
    assert seen["card"]["card"]["header"]["title"]["content"] == "done"


def test_eval_bench_scorecard_passes(tmp_path, monkeypatch):
    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("COMMERCEOPS_EVAL_DIR", str(tmp_path))
    scorecard = run_bench(tmp_path)
    assert len(CASES) >= 12
    assert scorecard["summary"]["cases"] == len(CASES)
    assert scorecard["summary"]["failed"] == 0
    assert scorecard["summary"]["passed"] == len(CASES)
    assert scorecard["summary"]["measured_model_tokens"] == 0
    assert scorecard["summary"]["ops_minutes_saved"] > 0
    raw = (tmp_path / "scorecard.json").read_text(encoding="utf-8")
    assert "profit_bridge_us" in raw
    assert "price_sim_bottle_cut" in raw
    assert "weekly_report_completeness" in raw
    html = (tmp_path / "scorecard.html").read_text(encoding="utf-8")
    assert html.count("<span class='pass'>") == len(CASES)
    latest = load_latest(tmp_path)
    assert latest["summary"]["failed"] == 0
