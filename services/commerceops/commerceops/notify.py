"""Feishu interactive-card notifier with a credential-free dry run.

When FEISHU_WEBHOOK_URL is unset, the card is stored and logged and nothing
is sent. Set COMMERCEOPS_NOTIFY_LOG to append the same records to a jsonl
file so a restarted API can still show them.
"""

from __future__ import annotations

from collections import deque
import json
import logging
import os
from pathlib import Path
from typing import Callable
from urllib import request as urlrequest

from commerceops.clock import utc_now

logger = logging.getLogger("commerceops.notify")
_RECORDS: deque[dict] = deque(maxlen=50)
Sender = Callable[[str, dict], None]


def clear_notifications() -> None:
    _RECORDS.clear()


def recent_notifications() -> list[dict]:
    if _RECORDS:
        return list(_RECORDS)
    path = _log_path()
    if path is None or not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-50:]
    records = []
    for line in lines:
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def notify_draft(event: str, draft: dict) -> dict:
    decision = draft.get("decision") or {}
    return dispatch(
        event,
        f"CommerceOps {event}",
        _decision_text(decision),
        {
            "draft_id": str(draft.get("draft_id") or ""),
            "action_type": str(draft.get("action_type") or ""),
            "status": str(draft.get("status") or ""),
            "replayed": str(bool(draft.get("replayed"))).lower(),
        },
    )


def notify_anomalies(brief: dict) -> dict:
    lines = [
        f"- {item['code']}: {item['detail']}" for item in brief.get("alerts", [])
    ]
    return dispatch(
        "anomaly_scan",
        f"CommerceOps anomalies {brief.get('store_code', '')}",
        "\n".join(lines) or "No anomalies.",
        {"store_code": str(brief.get("store_code") or ""), "count": str(len(brief.get("alerts", [])))},
    )


def dispatch(
    event: str,
    title: str,
    body: str,
    fields: dict[str, str],
    *,
    sender: Sender | None = None,
) -> dict:
    card = build_card(title, body, fields)
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    record = {
        "event": event,
        "created_at": utc_now(),
        "mode": "dry_run",
        "title": title,
        "card": card,
    }
    if webhook:
        (sender or _post_webhook)(webhook, card)
        record["mode"] = "sent"
    _RECORDS.append(record)
    _append_log(record)
    logger.info(
        "commerceops.notify event=%s mode=%s title=%s",
        event,
        record["mode"],
        title,
    )
    return record


def build_card(title: str, body: str, fields: dict[str, str]) -> dict:
    field_nodes = [
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**{key}**\n{value}"}}
        for key, value in fields.items()
        if value
    ]
    elements: list[dict] = [{"tag": "div", "text": {"tag": "lark_md", "content": body or " "}}]
    if field_nodes:
        elements.append({"tag": "div", "fields": field_nodes})
    return {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": title[:120]}},
            "elements": elements,
        },
    }


def _decision_text(decision: dict) -> str:
    if "to_daily_budget" in decision:
        return (
            f"{decision.get('campaign_external_id')} "
            f"{decision.get('from_daily_budget')} -> {decision.get('to_daily_budget')} "
            f"({decision.get('reason')})"
        )
    if "supplier_code" in decision:
        return (
            f"{decision.get('sku')} via {decision.get('supplier_code')} "
            f"qty {decision.get('quantity')} landed {decision.get('unit_landed_cost')}"
        )
    actions = decision.get("actions") or []
    return ", ".join(
        f"{item.get('competitor_asin')} {item.get('alert')}" for item in actions
    ) or "draft"


def _log_path() -> Path | None:
    raw = os.environ.get("COMMERCEOPS_NOTIFY_LOG", "").strip()
    return Path(raw) if raw else None


def _append_log(record: dict) -> None:
    path = _log_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _post_webhook(url: str, card: dict) -> None:
    payload = json.dumps(card).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=8) as response:
        if response.status >= 300:
            raise RuntimeError(f"feishu webhook status {response.status}")
