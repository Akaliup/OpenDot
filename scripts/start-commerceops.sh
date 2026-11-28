#!/usr/bin/env bash
# Start the CommerceOps API on 127.0.0.1:8077 and seed the demo clock.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/services/commerceops"

load_env() {
  local file="$1"
  if [[ -f "$file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$file"
    set +a
  fi
}

load_env "$ROOT/.env.commerceops"
export COMMERCEOPS_WORKSPACE_ID="${COMMERCEOPS_WORKSPACE_ID:-main}"
export COMMERCEOPS_AUTO_SEED="${COMMERCEOPS_AUTO_SEED:-1}"

if [[ "${COMMERCEOPS_ALLOW_PUBLIC_BIND:-0}" != "1" ]]; then
  export COMMERCEOPS_HOST=127.0.0.1
fi

venv="${COMMERCEOPS_VENV:-.venv}"
if [[ ! -d "$venv" ]]; then
  python3 -m venv "$venv"
fi
python="$venv/bin/python"
if [[ ! -x "$python" ]]; then python="$venv/Scripts/python.exe"; fi
if ! "$python" -m pip --version >/dev/null 2>&1; then "$python" -m ensurepip; fi
"$python" -m pip install -e ".[dev]"

export COMMERCEOPS_DATABASE_URL="${COMMERCEOPS_DATABASE_URL:-sqlite:///$ROOT/services/commerceops/commerceops.db}"
export COMMERCEOPS_NOTIFY_LOG="${COMMERCEOPS_NOTIFY_LOG:-$ROOT/services/commerceops/commerceops-notifications.jsonl}"
export COMMERCEOPS_EVAL_DIR="${COMMERCEOPS_EVAL_DIR:-$ROOT/services/commerceops/evals}"
export COMMERCEOPS_HOST="${COMMERCEOPS_HOST:-127.0.0.1}"
export COMMERCEOPS_PORT="${COMMERCEOPS_PORT:-8077}"

if [[ "${COMMERCEOPS_SKIP_SEED:-0}" == "1" ]]; then
  export COMMERCEOPS_AUTO_SEED=0
fi

exec "$python" -m commerceops.api.app
