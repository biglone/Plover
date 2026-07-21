#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${PLOVER_DEV_LOG_DIR:-$ROOT_DIR/.plover-dev}"
PYTHON_BIN="${PLOVER_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
COMPOSE_BIN="${PLOVER_DOCKER_COMPOSE_BIN:-docker compose}"
EXECUTOR_LOG="$LOG_DIR/macos-executor.log"
EXECUTOR_PID_FILE="$LOG_DIR/macos-executor.pid"

load_env_file() {
  local env_file="$1"
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing command: $command_name" >&2
    exit 1
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

wait_for_port() {
  local host="$1"
  local port="$2"
  local label="$3"
  local attempt
  for attempt in $(seq 1 60); do
    if python3 - "$host" "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
with socket.create_connection((host, port), timeout=0.5):
    pass
PY
    then
      echo "$label is ready at $host:$port"
      return 0
    fi
    sleep 0.5
  done
  echo "$label did not become ready. Check $EXECUTOR_LOG" >&2
  return 1
}

cleanup() {
  if [[ -f "$EXECUTOR_PID_FILE" ]]; then
    local pid
    pid="$(cat "$EXECUTOR_PID_FILE")"
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      wait "$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$EXECUTOR_PID_FILE"
  fi
}

trap cleanup EXIT INT TERM

load_env_file "$ROOT_DIR/.env"
load_env_file "$ROOT_DIR/.env.local"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This launcher is intended for macOS hosts." >&2
  exit 1
fi

PLOVER_EXECUTOR_DRIVER="${PLOVER_EXECUTOR_DRIVER:-macos}"
PLOVER_EXECUTOR_BIND="${PLOVER_EXECUTOR_BIND:-0.0.0.0}"
PLOVER_EXECUTOR_PORT="${PLOVER_EXECUTOR_PORT:-50051}"
PLOVER_EXECUTOR_TARGET="${PLOVER_EXECUTOR_TARGET:-host.docker.internal:${PLOVER_EXECUTOR_PORT}}"

export PLOVER_EXECUTOR_DRIVER
export PLOVER_EXECUTOR_BIND
export PLOVER_EXECUTOR_PORT
export PLOVER_EXECUTOR_TARGET

require_command docker
require_command python3
require_file "$PYTHON_BIN" "Create the virtual environment and install backend requirements first."

mkdir -p "$LOG_DIR"

if [[ "$PLOVER_EXECUTOR_DRIVER" != "macos" ]]; then
  echo "Overriding PLOVER_EXECUTOR_DRIVER to macos for host desktop control."
  export PLOVER_EXECUTOR_DRIVER="macos"
fi

echo "Starting host macOS Executor on ${PLOVER_EXECUTOR_BIND}:${PLOVER_EXECUTOR_PORT}"
env PYTHONPATH=backend "$PYTHON_BIN" -m executor_service >"$EXECUTOR_LOG" 2>&1 &
EXECUTOR_PID=$!
echo "$EXECUTOR_PID" >"$EXECUTOR_PID_FILE"
wait_for_port "127.0.0.1" "$PLOVER_EXECUTOR_PORT" "Host macOS Executor"

echo "Launching Docker compose with Planner pointed at ${PLOVER_EXECUTOR_TARGET}"
exec $COMPOSE_BIN \
  -f "$ROOT_DIR/docker-compose.host-executor.yml" \
  up --build
