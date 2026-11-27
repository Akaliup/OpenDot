# CommerceOps demo runbook

Use this when showing the interview build. Both processes must share one
SQLite file, or a draft created by the agent will not appear on the approval page.

## Start

From the repository root:

```bash
cd services/commerceops
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
export COMMERCEOPS_DATABASE_URL="sqlite:///$PWD/commerceops.db"
export COMMERCEOPS_NOTIFY_LOG="$PWD/commerceops-notifications.jsonl"
export COMMERCEOPS_EVAL_DIR="$PWD/commerceops-evals"
.venv/bin/commerceops-seed
.venv/bin/commerceops-api
```

The API listens on `127.0.0.1:8077`. Leave `FEISHU_WEBHOOK_URL` unset for the dry run. In another terminal, from the repository root:

```bash
export COMMERCEOPS_API_URL="http://127.0.0.1:8077"
npm run dev
```

And the web app:

```bash
npm run dev:web
```

Sign in, open 高级功能 → 经营.

Optional MCP registration, only if you want the agent to call the tools. In 能力库 → MCP, add a server with the body in `services/commerceops/opendot/mcp-server.example.json`. Set `COMMERCEOPS_DATABASE_URL` to the same absolute SQLite URL as the API. This adds one server. It does not edit servers that are already saved.

The CommerceOps skill is already a project skill at `container/skills/commerceops/SKILL.md`. Enable it on the Dot you use for the demo.

## Three-minute script

1. Overview, store `us-main`. The current net profit is 682.60 and the previous is 1371.90. The bridge is -689.30, and ad spend plus refunds are the two largest drags. Point at the identity flag.
2. Show Bottle Exact and Bottle Broad as the high-ACOS rows, then `NS-CABLE-3PK` with Shenzhen Rapid as the first supplier quote. Show competitor `B0COMP001` with the price drop, BSR jump, and complaint spike, labeled as demo seed data.
3. Click 飞书简报. With no webhook, the API records a dry-run card. Say that a real webhook URL would send the same card.
4. Switch to 审批. If a draft is pending, read the exact budget or quantity. Click 批准并执行 once. The audit gains `approved` and `executed`. The button becomes 再次批准. Click it. The status stays executed and the audit gains `replay_noop`. No second purchase order or budget revision is written.
5. On 概览, leave the bottle SKU and target price `18.00`, then click 计算价格. The base profit delta is -40.81. The three rows are conservative, base, and optimistic.
6. Click 生成周报 / 推送飞书. With no webhook, the card mode is `dry_run`. The markdown contains both stores and does not add USD to GBP.
7. Open 评测 and run it. The scorecard should be 14/14, with measured model tokens at 0.

## Restart in the middle of an approval

1. On 概览, or from a tool call, create a purchase draft and stop before approving it. Note the draft id.
2. Stop only the Python API: `lsof -ti:8077 -sTCP:LISTEN | xargs kill`. The 经营 page then shows that CommerceOps is offline. OpenDot itself stays up.
3. Start `commerceops-api` again with the same `COMMERCEOPS_DATABASE_URL`.
4. Refresh 审批. The draft is still `draft`, and there is still no purchase order.
5. Approve it once, then approve it again. One simulated purchase order exists, `sent_to_supplier` stays 0, and the second call is `replayed`.

## Checks before the interview

```bash
cd services/commerceops && .venv/bin/pytest
cd ../.. && npm run typecheck && npm run build:web
```
