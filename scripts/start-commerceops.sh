#!/usr/bin/env bash
# Start the CommerceOps API on 127.0.0.1:8077 and seed the demo clock.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/services/commerceops"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -e ".[dev]"

export COMMERCEOPS_DATABASE_URL="${COMMERCEOPS_DATABASE_URL:-sqlite:///$ROOT/services/commerceops/commerceops.db}"
export COMMERCEOPS_NOTIFY_LOG="${COMMERCEOPS_NOTIFY_LOG:-$ROOT/services/commerceops/commerceops-notifications.jsonl}"
export COMMERCEOPS_EVAL_DIR="${COMMERCEOPS_EVAL_DIR:-$ROOT/services/commerceops/evals}"
export COMMERCEOPS_HOST="${COMMERCEOPS_HOST:-127.0.0.1}"
export COMMERCEOPS_PORT="${COMMERCEOPS_PORT:-8077}"

if [[ "${COMMERCEOPS_SKIP_SEED:-0}" != "1" ]]; then
  .venv/bin/commerceops-seed
fi

exec .venv/bin/commerceops-api
