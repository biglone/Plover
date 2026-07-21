#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PLOVER_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
NPM_BIN="${PLOVER_NPM_BIN:-npm}"
PLANNER_PORT="${PLOVER_E2E_PLANNER_PORT:-8011}"
FRONTEND_PORT="${PLOVER_E2E_FRONTEND_PORT:-5174}"
PLANNER_URL="http://127.0.0.1:${PLANNER_PORT}"
FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"
LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/plover-browser-e2e.XXXXXX")"
PIDS=()
BROWSER_CHANNEL="${PLOVER_E2E_BROWSER_CHANNEL:-}"

cleanup() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      wait "$pid" >/dev/null 2>&1 || true
    fi
  done
  rm -rf "$LOG_DIR"
}
trap cleanup EXIT INT TERM

require_file() {
  if [[ ! -e "$1" ]]; then
    echo "Missing $1" >&2
    exit 1
  fi
}

wait_for_http() {
  local url="$1"
  local label="$2"
  local attempt
  for attempt in $(seq 1 80); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  echo "$label did not become ready. Logs are in $LOG_DIR" >&2
  return 1
}

require_file "$PYTHON_BIN"
require_file "$ROOT_DIR/frontend/node_modules"
command -v "$NPM_BIN" >/dev/null 2>&1 || {
  echo "Missing npm command: $NPM_BIN" >&2
  exit 1
}
command -v curl >/dev/null 2>&1 || {
  echo "Missing curl" >&2
  exit 1
}
"$PYTHON_BIN" -c "import playwright.sync_api" || {
  echo "Install the browser test dependency with: $PYTHON_BIN -m pip install -r backend/requirements.txt" >&2
  exit 1
}

if [[ -z "$BROWSER_CHANNEL" ]]; then
  if [[ -d "/Applications/Google Chrome.app" ]]; then
    BROWSER_CHANNEL="chrome"
  elif [[ -d "/Applications/Microsoft Edge.app" ]]; then
    BROWSER_CHANNEL="msedge"
  fi
fi

env \
  PYTHONPATH=backend \
  PLOVER_PLANNER_HOST=127.0.0.1 \
  PLOVER_PLANNER_PORT="$PLANNER_PORT" \
  "$PYTHON_BIN" -m planner_service >"$LOG_DIR/planner.log" 2>&1 &
PIDS+=("$!")
wait_for_http "$PLANNER_URL/health" "Planner"

env \
  PLOVER_PLANNER_ORIGIN="$PLANNER_URL" \
  PLOVER_FRONTEND_PORT="$FRONTEND_PORT" \
  "$NPM_BIN" --prefix "$ROOT_DIR/frontend" run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" \
  >"$LOG_DIR/frontend.log" 2>&1 &
PIDS+=("$!")
wait_for_http "$FRONTEND_URL" "Frontend"

PLOVER_E2E_BASE_URL="$FRONTEND_URL" \
PLOVER_E2E_BROWSER_CHANNEL="$BROWSER_CHANNEL" \
  "$PYTHON_BIN" "$ROOT_DIR/e2e/test_manual_action_flow.py"
