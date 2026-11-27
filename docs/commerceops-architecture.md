# CommerceOps phase 1

CommerceOps is a cross-border commerce operating slice on top of OpenDot.
Phase 1 adds one Python service and this document. It does not change the
OpenDot runtime, schema, routes, or React app.

## What was already in OpenDot

OpenDot is the agent runtime. The pieces Phase 2 will attach to, and that
this phase deliberately leaves alone:

| Concern | Where it lives |
| --- | --- |
| Product runtime, channels, scheduler, IPC | `src/index.ts`, `src/task-scheduler.ts`, `src/feishu.ts` |
| HTTP app and auth | `src/web.ts`, `docs/API.md`, `docs/ACL-MATRIX.md` |
| User MCP registration (stdio command, args, env) | `src/routes/mcp-servers.ts` |
| In-process agent tools | `container/agent-runner/src/mcp-tools.ts` |
| External MCP client and approval ledger | `docs/mcp-integration.md`, `docs/mcp-approvals.md` |
| Web routes | `web/src/App.tsx` |

Managed MCP servers are stdio or HTTP processes with an explicit command.
Tool calls still go through OpenDot's owner, session, and approval ledger.
Phase 1 does not register a server and does not weaken that ledger.

## Two layers

```text
OpenDot (TypeScript)
  agent runtime, skills, scheduler, Feishu, HITL approval, React
        │  stdio MCP, added in phase 2
        ▼
services/commerceops (Python)
  FastAPI + MCPServer
  SQLite by default, SQLAlchemy
  deterministic engines
  BM25 SOP citations
  draft → approval record → writeback + audit
```

OpenDot decides who may talk to a tool. CommerceOps decides whether a
business write is legal. A draft tool cannot change a budget, insert a
purchase order, or edit a competitor snapshot. The only apply path is
`approve_and_execute_draft`, and it writes an approval row in the same
transaction as the operational row.

Phase 2 should not give that apply tool to the model by itself. The model
creates drafts. A person approves in OpenDot, and OpenDot then calls apply.
The Python gate still refuses a bare execute, so a missed UI check fails
closed.

## What this phase does not build

- No LangGraph and no seven specialist agents. One OpenDot profile can call
  these tools later.
- No PostgreSQL or pgvector requirement. SQLite is the zero-config database.
  Money columns use `ExactNumeric`: a decimal string on SQLite, `NUMERIC(18, 6)`
  on other dialects. Reports sum in Python so SQLite `SUM` never turns money
  into a float.
- No Amazon, Shopify, or TikTok OAuth clients, and no scraper. Competitor
  rows are imported. `collection_method` is `demo_seed`, `manual_import`, or
  `licensed_feed`. A source that says scrape is rejected.

## Data

| Table | Role |
| --- | --- |
| `stores`, `products` | Marketplace and SKU / ASIN catalog |
| `orders`, `refunds` | Profit facts. Orders have no ad-spend column |
| `ad_campaigns`, `ad_metric_days` | Campaign budget plus daily delivery and attribution |
| `inventory_snapshots` | On-hand, reserved, inbound, safety stock, planning lead time |
| `suppliers`, `supplier_quotes` | Tiered price, duty, freight, MOQ, lead time, on-time sample |
| `competitor_snapshots` | Imported price, BSR, rating, review-hit history |
| `sop_documents` | The four markdown procedures, also read from disk for citations |
| `action_drafts`, `approval_records` | Draft payload and the explicit approval or rejection |
| `writeback_audit_logs` | Append-only. SQLite triggers reject update and delete |
| `ad_budget_revisions`, `purchase_orders`, `competitor_responses` | The only operational writebacks |

`ad_metric_days` is the daily child of `ad_campaigns`. Period math needs it.
`purchase_orders.sent_to_supplier` cannot be set: triggers abort an insert or
update that tries. A purchase order is simulated and is not sent.

CSV and JSON import upsert on natural keys and validate the whole batch
before writing. That path is operator ingest, not an agent tool. It is not
in the MCP tool list. Re-importing the same key updates the row. A bad row
fails the batch and leaves the previous rows in place. JSON money must be a
string or an integer; floats are rejected.

`POST /api/v1/seed` loads a fixed demo clock:

- as-of `2026-03-15`
- current window `2026-03-08` .. `2026-03-14`
- previous window `2026-03-01` .. `2026-03-07`
- `us-main` (USD) profit falls from 1371.90 to 682.60
- the bridge is -689.30, led by ad spend (-392.00) and refunds (-300.00)
- `uk-main` (GBP) stays at 126.00 in both windows
- `camp-bottle-exact`, `camp-bottle-broad`, and `camp-lamp` are the ad anomalies
- `NS-CABLE-3PK` and `NS-LAMP-LED` cover fewer than 14 days
- cable quotes rank Shenzhen Rapid, then Vietnam Flex, then Ningbo Value
- competitor `B0COMP001` drops price, improves BSR, and spikes complaint hits

Running the seed again upserts those keys. It does not delete drafts or audits.

## Engines

The engines live in `services/commerceops/commerceops/engines/`. They do not
import SQLAlchemy. `GET /api/v1/formulas` returns the same versions.

### profit.v1

```text
net_sales = revenue - discounts - refunds
net_cogs = cogs - recovered_cogs
net_profit = net_sales - net_cogs - platform_fees - shipping_fees - ad_spend - other_fees
```

Ad spend is the sum of `ad_metric_days` for that store and window. Margin is
`net_profit / net_sales` when net sales are not zero, with status `ok` or
`negative_net_sales`. When net sales are zero the margin is null and the
status is `zero_net_sales`. Recovered COGS may exceed the period's COGS when
a refund belongs to an earlier sale; net COGS is then negative and the bridge
still balances.

The bridge contribution of revenue is `current - previous`. The contribution
of every cost is `-(current - previous)`. Those eight contributions equal
`current net profit - previous net profit`. The service raises if they do not.

### ads.v1

```text
ACOS = spend / attributed_sales
ROAS = attributed_sales / spend
TACOS = spend / sales denominator
CTR = clicks / impressions
CPC = spend / clicks
CVR = attributed_orders / clicks
CPA = spend / attributed_orders
```

A zero denominator returns null and a status (`zero_attributed_sales`,
`zero_spend`, `zero_tacos_sales`, `zero_impressions`, `zero_clicks`,
`zero_orders`). It is not coerced to zero. Store TACOS uses product sales
(gross revenue minus discounts). Campaign TACOS uses that SKU's product sales.
Attributed sales summed across campaigns are labeled as not deduplicated.

Flags:

- `spend_up_cvr_down` when spend is at least 50, spend rose, and both CVRs exist and the current one is lower
- `acos_above_high` at or above 0.40, `acos_above_target` at or above 0.35
- `acos_deteriorated` when both ACOSs exist and the current one is higher

Budget ladder, applied to the current daily budget and rounded to cents:

| Condition | Multiplier | Reason |
| --- | --- | --- |
| ACOS >= 0.80 | 0.50 | `severe_acos` |
| ACOS >= 0.40 | 0.70 | `high_acos` |
| else spend-up and CVR-down | 0.80 | `cvr_decline` |
| else | 1 | `no_adjustment` |

`no_adjustment` does not create a draft.

### inventory.v1

```text
available = max(on_hand - reserved, 0)
average_daily_sales = units ordered in the lookback / lookback_days
days_of_cover = available / average_daily_sales
reorder_point = average_daily_sales * planning_lead_time + safety_stock
need = average_daily_sales * (lead_time + target_cover) + safety_stock - available - inbound
```

Refunds are not removed from demand. The lookback ends the day before `as_of`.
Average daily sales of zero yields status `undefined_no_velocity`: days of
cover and reorder point are null, and the SKU is not marked at risk. A SKU
with sales and zero available has cover 0 and is at risk. Reserved above
on-hand is oversold, and available is 0 rather than negative. Inbound quantity
reduces the need even when its ETA is after the stockout date; that case sets
`inbound_late`. Suggested units are the ceiling of the need. MOQ is not
applied here.

### supplier.v1

```text
landed = unit_price * (1 + duty_rate) + freight_per_unit
score = 0.40 * cost + 0.25 * lead + 0.20 * MOQ fit + 0.15 * on-time
```

Cost and lead are normalized against the cheapest and fastest quote in the
set. MOQ fit is raw need / MOQ, capped at 1. On-time rate is used only when
`sample_size >= 8`; otherwise that component is 0 and the status is
`insufficient_sample`. Weights sum to 1 and are not redistributed. Ties break
by landed cost, then supplier code.

The buy quantity uses that supplier's lead time, then snaps up to the order
multiple and, if still short, to MOQ. Raw need of zero stays zero. The price
tier is the highest tier whose minimum quantity the buy still reaches. Lead
time longer than days of cover is `arrives_after_stockout`.

### competitor.v1

The latest snapshot at or before `as_of` is diffed with the one before it.
One snapshot is `insufficient_history` and raises no alert.

| Alert | Rule |
| --- | --- |
| `price_drop` | percent change <= -3% |
| `bsr_jump` | rank number fell by at least 200 (the product became more competitive) |
| `rating_drop` | rating fell by at least 0.2 |
| `complaint_spike` | negative-review hits rose by at least 10 |

A zero starting price is `zero_base_price` and is not a price-drop alert.
Each alert maps to one action code. The action text includes the source,
collection method, timestamps, and the numbers. Demo rows stay `sample_data`.

## SOP citations

Four markdown files in `services/commerceops/commerceops/sop/docs/` cover
profit-drop investigation, ACOS cuts, stockout and supplier choice, and
competitor response. Search is BM25 (`sop.bm25.v1`, k1 1.5, b 0.75) over
Latin words and CJK bigrams. A hit returns `doc_id`, `section`, `quote`, and
the file sha256. The quote is an exact slice of the file. There is no
embedding service.

## MCP and HTTP

Read tools: list stores, profit report, ads diagnosis, inventory risk,
supplier comparison, competitor diff, SOP search.

Draft tools: `commerceops_create_ad_budget_draft`,
`commerceops_create_purchase_order_draft`,
`commerceops_create_competitor_response_draft`.

Apply tool: `commerceops_approve_and_execute_draft`.

There is no execute tool, no import tool, and no "send purchase order" tool.
Read tools are marked read-only. Draft tools are not marked destructive.
The apply tool is. Repeating apply on an executed draft returns the same
`execution_ref` and writes `replay_noop` instead of a second revision or
purchase order. A draft whose recomputed decision no longer matches is
`stale_draft` and is not applied. Rejected drafts stay rejected.

HTTP mirrors the same functions under `/api/v1`. `POST /api/v1/drafts/{id}/execute`
is the fail-closed check: without an approval row it returns 409
`unapproved_execution` and still appends an audit entry. The MCP server does
not expose that call.

## OpenDot wiring

Logged-in requests to `/api/commerceops/*` are proxied by
`src/routes/commerceops.ts` to `COMMERCEOPS_API_URL` (default
`http://127.0.0.1:8077`). If that process is down the proxy returns 503
`commerceops_offline`. `GET /api/commerceops/meta` stays inside OpenDot and
returns the stdio preset. Saving that preset is a separate MCP settings
action; existing server entries are not rewritten.

The project skill is `container/skills/commerceops/SKILL.md`. It requires tool
numbers, SOP quotes, and a stop at draft creation. The pages live at
`/commerce`, `/commerce/approvals`, and `/commerce/evals`.

Feishu cards are sent only when `FEISHU_WEBHOOK_URL` is set. Otherwise the
same card is a dry-run record on `GET /api/v1/notifications`. The eval bench
in `services/commerceops/commerceops/evals/bench.py` runs ten tool-contract
cases and writes `scorecard.json` plus `scorecard.html`. `GET /api/v1/evals/latest`
reads that file.

The click-through script is [commerceops-demo-runbook.md](commerceops-demo-runbook.md).

## Local check

From `services/commerceops`, `pytest` covers the engines, seed and CSV
upserts, SOP citations, the approval gate, FastAPI, MCP stdio, the Feishu
dry run, and the eval scorecard.
