#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${PLOVER_DEV_LOG_DIR:-$ROOT_DIR/.plover-dev}"
PYTHON_BIN="${PLOVER_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
NPM_BIN="${PLOVER_NPM_BIN:-npm}"

load_env_file() {
  local env_file="$1"
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
}

require_file() {
  local path="$1"
  local hint="$2"
  if [[ ! -e "$path" ]]; then
    echo "Missing $path. $hint" >&2
    exit 1
  fi
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing command: $command_name" >&2
    exit 1
  fi
}

wait_for_http() {
  local url="$1"
  local label="$2"
  local attempt
  for attempt in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$label is ready at $url"
      return 0
    fi
    sleep 0.25
  done
  echo "$label did not become ready. Check logs in $LOG_DIR" >&2
  return 1
}

start_process() {
  local name="$1"
  shift
  local log_file="$LOG_DIR/$name.log"
  "$@" >"$log_file" 2>&1 &
  local pid=$!
  PIDS+=("$pid")
  echo "$pid" >"$LOG_DIR/$name.pid"
  echo "Started $name (pid $pid). Log: $log_file"
}

cleanup() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      wait "$pid" >/dev/null 2>&1 || true
    fi
  done
}

PIDS=()
handle_signal() {
  cleanup
  exit 0
}
trap cleanup EXIT
trap handle_signal INT TERM

load_env_file "$ROOT_DIR/.env"
load_env_file "$ROOT_DIR/.env.local"

PLOVER_PLANNER_HOST="${PLOVER_PLANNER_HOST:-127.0.0.1}"
PLOVER_PLANNER_PORT="${PLOVER_PLANNER_PORT:-8000}"
PLOVER_PLANNER_RELOAD="${PLOVER_PLANNER_RELOAD:-0}"
PLOVER_EXECUTOR_HOST="${PLOVER_EXECUTOR_HOST:-127.0.0.1}"
PLOVER_EXECUTOR_BIND="${PLOVER_EXECUTOR_BIND:-${PLOVER_EXECUTOR_HOST}}"
PLOVER_EXECUTOR_PORT="${PLOVER_EXECUTOR_PORT:-50051}"
PLOVER_EXECUTOR_DRIVER="${PLOVER_EXECUTOR_DRIVER:-mock}"
PLOVER_FRONTEND_HOST="${PLOVER_FRONTEND_HOST:-127.0.0.1}"
PLOVER_FRONTEND_PORT="${PLOVER_FRONTEND_PORT:-5173}"
PLOVER_START_EXECUTOR="${PLOVER_START_EXECUTOR:-1}"
PLOVER_START_FRONTEND="${PLOVER_START_FRONTEND:-1}"
PLOVER_PLANNER_ORIGIN="${PLOVER_PLANNER_ORIGIN:-http://${PLOVER_PLANNER_HOST}:${PLOVER_PLANNER_PORT}}"
PLOVER_EXECUTOR_TARGET="${PLOVER_EXECUTOR_TARGET:-}"
if [[ -z "$PLOVER_EXECUTOR_TARGET" && "$PLOVER_START_EXECUTOR" == "1" ]]; then
  PLOVER_EXECUTOR_TARGET="${PLOVER_EXECUTOR_HOST}:${PLOVER_EXECUTOR_PORT}"
fi

export PLOVER_PLANNER_HOST
export PLOVER_PLANNER_PORT
export PLOVER_PLANNER_RELOAD
export PLOVER_EXECUTOR_BIND
export PLOVER_EXECUTOR_PORT
export PLOVER_EXECUTOR_DRIVER
export PLOVER_FRONTEND_PORT
export PLOVER_PLANNER_ORIGIN
if [[ -n "$PLOVER_EXECUTOR_TARGET" ]]; then
  export PLOVER_EXECUTOR_TARGET
else
  unset PLOVER_EXECUTOR_TARGET || true
fi

require_file "$PYTHON_BIN" "Create the virtual environment and install backend requirements first."
require_command curl
require_file "$ROOT_DIR/frontend/package.json" "The frontend workspace is missing."
if [[ "$PLOVER_START_FRONTEND" == "1" ]]; then
  require_command "$NPM_BIN"
  require_file "$ROOT_DIR/frontend/node_modules" "Run 'npm --prefix frontend install' first."
fi

mkdir -p "$LOG_DIR"

if [[ "$PLOVER_START_EXECUTOR" == "1" ]]; then
  start_process executor env PYTHONPATH=backend "$PYTHON_BIN" -m executor_service
fi

start_process planner env PYTHONPATH=backend "$PYTHON_BIN" -m planner_service
wait_for_http "$PLOVER_PLANNER_ORIGIN/health" "Planner"

if [[ "$PLOVER_START_FRONTEND" == "1" ]]; then
  start_process frontend "$NPM_BIN" --prefix "$ROOT_DIR/frontend" run dev -- --host "$PLOVER_FRONTEND_HOST" --port "$PLOVER_FRONTEND_PORT"
fi

echo
echo "Plover local development stack is running."
echo "Planner:  $PLOVER_PLANNER_ORIGIN"
if [[ "$PLOVER_START_FRONTEND" == "1" ]]; then
  echo "Frontend: http://${PLOVER_FRONTEND_HOST}:${PLOVER_FRONTEND_PORT}"
fi
if [[ "$PLOVER_START_EXECUTOR" == "1" ]]; then
  echo "Executor: ${PLOVER_EXECUTOR_TARGET} (${PLOVER_EXECUTOR_DRIVER})"
elif [[ -n "$PLOVER_EXECUTOR_TARGET" ]]; then
  echo "Executor target: ${PLOVER_EXECUTOR_TARGET}"
else
  echo "Executor: in-process local gateway"
fi
echo "Press Ctrl-C to stop all local services."

while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      wait "$pid" || true
      echo "A local service exited unexpectedly. Check logs in $LOG_DIR" >&2
      exit 1
    fi
  done
  sleep 1
done
