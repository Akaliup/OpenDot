# CommerceOps

Deterministic commerce service for the OpenDot CommerceOps AI slice. It owns
the SQL data, the profit / ads / inventory / supplier / competitor engines,
SOP citations, and the approval gate. OpenDot keeps the agent runtime,
scheduler, Feishu channel, and UI. This package does not call a model.

The architecture and the Phase 2 boundary are in
[docs/commerceops-architecture.md](../../docs/commerceops-architecture.md).

## Run

```bash
cd services/commerceops
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/commerceops-seed
.venv/bin/commerceops-api
```

The API listens on `127.0.0.1:8077`. Override the host with `COMMERCEOPS_HOST`,
the port with `COMMERCEOPS_PORT`, and the database with
`COMMERCEOPS_DATABASE_URL` (default `sqlite:///./commerceops.db`). Seed is
idempotent and does not delete drafts.

From the repository root, the same process is:

```bash
./scripts/start-commerceops.sh
```

Docker, from the repository root:

```bash
docker compose -f docker-compose.commerceops.yml up --build
```

The image listens on `0.0.0.0:8077`, seeds the demo database when the volume
is empty, and exposes `/health`. Copy `.env.commerceops.example` if you want
to override the compose environment. Leave `FEISHU_WEBHOOK_URL` unset for a
dry-run card.

OpenDot proxies `/api/commerceops` to `COMMERCEOPS_API_URL` (default
`http://127.0.0.1:8077`).

The MCP server speaks stdio, which is the transport OpenDot already registers:

```bash
.venv/bin/commerceops-mcp
```

## Tests

```bash
cd services/commerceops
.venv/bin/pytest
```

Money stays in `Decimal`. A zero denominator is a status (`zero_net_sales`,
`zero_attributed_sales`, `undefined_no_velocity`, …), not a fabricated 0 or
infinity. Draft tools do not change budgets, purchase orders, or competitor
snapshots. `approve_and_execute_draft` is the only writeback, and repeating it
does not apply the draft twice.

## Agent evaluation

From the repository root, install the locked Node dependencies and the CommerceOps
Python package with its dev extra. Select that Python interpreter via
`COMMERCEOPS_EVAL_PYTHON` if it is not the default `python`.

```sh
python services/commerceops/evals/scripted_scorecard.py
node --import tsx services/commerceops/evals/live_agent.mjs --check-mcp
node --import tsx services/commerceops/evals/live_agent.mjs
```

The middle command exercises OpenDot managed MCP discovery and dispatch against
a temporary seeded database without making a model request. For the last command,
provide `DEEPSEEK_API_KEY` and `DEEPSEEK_BASE_URL` through the process environment.
The runner accepts the official HTTPS API origin with an optional /v1 suffix.
`DEEPSEEK_MODEL` defaults to deepseek-chat. Missing configuration produces eight
skipped rows. Each case gets its own workspace database and tool catalog.
The run allows at most 45 completion requests, 900 completion tokens per request
and 1.1 MB of cumulative request bodies. Estimated cost is null.
The evaluation page reads the scripted and live JSON files from
`COMMERCEOPS_EVAL_DIR` or the bundled evals directory. Its run button triggers the
deterministic bench only.
