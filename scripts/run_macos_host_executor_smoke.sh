#!/usr/bin/env bash
set -euo pipefail

# Verify the Docker Planner -> host macOS Executor observation path without
# sending an Execute request, so this smoke test never clicks, types, or scrolls.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PLOVER_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
COMPOSE_PROJECT="${PLOVER_MACOS_SMOKE_COMPOSE_PROJECT:-plover-macos-smoke-$$}"
EXECUTOR_PORT="${PLOVER_MACOS_SMOKE_EXECUTOR_PORT:-50053}"
PLANNER_PORT="${PLOVER_MACOS_SMOKE_PLANNER_PORT:-18000}"
LOG_DIR="${PLOVER_DEV_LOG_DIR:-$ROOT_DIR/.plover-dev}"
EXECUTOR_LOG="$LOG_DIR/macos-host-executor-smoke-$COMPOSE_PROJECT.log"
EXECUTOR_PID=""
COMPOSE_ARGS=(
  compose
  -p "$COMPOSE_PROJECT"
  -f "$ROOT_DIR/docker-compose.host-executor.yml"
)

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing command: $command_name" >&2
    exit 1
  fi
}

require_port_available() {
  local port="$1"
  if ! python3 - "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_:
    socket_.bind(("127.0.0.1", int(sys.argv[1])))
PY
  then
    echo "Port $port is already in use. Set the matching PLOVER_MACOS_SMOKE_*_PORT variable and retry." >&2
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

with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=0.5):
    pass
PY
    then
      echo "$label is ready at $host:$port"
      return 0
    fi
    sleep 0.5
  done
  echo "$label did not become ready." >&2
  return 1
}

wait_for_planner() {
  local attempt
  for attempt in $(seq 1 90); do
    if "$PYTHON_BIN" - "$PLANNER_PORT" <<'PY' >/dev/null 2>&1
import json
import sys
from urllib.request import urlopen

with urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=1) as response:
    payload = json.load(response)
if payload.get("status") != "ok":
    raise SystemExit(1)
PY
    then
      echo "Dockerized Planner is ready at 127.0.0.1:$PLANNER_PORT"
      return 0
    fi
    sleep 1
  done
  echo "Dockerized Planner did not become ready." >&2
  return 1
}

cleanup() {
  local exit_code=$?
  if [[ "$exit_code" -ne 0 ]]; then
    echo "Smoke test failed; temporary service logs follow." >&2
    docker "${COMPOSE_ARGS[@]}" logs --no-color >&2 || true
    if [[ -f "$EXECUTOR_LOG" ]]; then
      tail -n 120 "$EXECUTOR_LOG" >&2 || true
    fi
  fi
  docker "${COMPOSE_ARGS[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  if [[ -n "$EXECUTOR_PID" ]] && kill -0 "$EXECUTOR_PID" >/dev/null 2>&1; then
    kill "$EXECUTOR_PID" >/dev/null 2>&1 || true
    wait "$EXECUTOR_PID" >/dev/null 2>&1 || true
  fi
  exit "$exit_code"
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This smoke test must run on a macOS host." >&2
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing Python interpreter: $PYTHON_BIN" >&2
  exit 1
fi

require_command docker
require_command python3
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running. Start Docker Desktop and rerun this command." >&2
  exit 1
fi
require_port_available "$EXECUTOR_PORT"
require_port_available "$PLANNER_PORT"

trap cleanup EXIT INT TERM
mkdir -p "$LOG_DIR"

# Isolate the temporary Planner from local model, observation, and database configuration.
export PLOVER_EXECUTOR_TARGET="host.docker.internal:$EXECUTOR_PORT"
export PLOVER_PLANNER_PUBLISH_PORT="$PLANNER_PORT"
export PLOVER_FRONTEND_PUBLISH_PORT=13000
export PLOVER_POSTGRES_DB=plover_smoke
export PLOVER_POSTGRES_USER=plover_smoke
export PLOVER_POSTGRES_PASSWORD=plover_smoke
export PLOVER_DATABASE_URL="postgresql://plover_smoke:plover_smoke@postgres:5432/plover_smoke"
unset PLOVER_OBSERVATION_PATH PLOVER_OBSERVATION_URL PLOVER_OBSERVATION_HEADERS
unset PLOVER_OBSERVATION_TIMEOUT_SECONDS PLOVER_VNC_TARGET
unset PLOVER_LLM_ENDPOINT PLOVER_LLM_MODEL PLOVER_LLM_API_KEY PLOVER_LLM_API_KEY_HEADER
unset PLOVER_LLM_API_KEY_PREFIX PLOVER_LLM_EXTRA_HEADERS PLOVER_LLM_STREAM
unset PLOVER_LLM_BOOTSTRAP_ENDPOINT PLOVER_LLM_BOOTSTRAP_METHOD PLOVER_LLM_BOOTSTRAP_HEADERS
unset PLOVER_LLM_BOOTSTRAP_BODY PLOVER_LLM_BOOTSTRAP_TOKEN_PATH PLOVER_LLM_BOOTSTRAP_EXPIRES_IN_PATH
unset PLOVER_LLM_BOOTSTRAP_HEADER_NAME PLOVER_LLM_BOOTSTRAP_HEADER_PREFIX
unset PLOVER_LLM_BOOTSTRAP_REFRESH_SKEW_SECONDS

"$ROOT_DIR/scripts/run_macos_smoke.sh"

echo "Starting temporary host macOS Executor on 0.0.0.0:$EXECUTOR_PORT"
env \
  PLOVER_EXECUTOR_DRIVER=macos \
  PLOVER_EXECUTOR_BIND=0.0.0.0 \
  PLOVER_EXECUTOR_PORT="$EXECUTOR_PORT" \
  PYTHONPATH=backend \
  "$PYTHON_BIN" -m executor_service >"$EXECUTOR_LOG" 2>&1 &
EXECUTOR_PID=$!
wait_for_port "127.0.0.1" "$EXECUTOR_PORT" "Host macOS Executor"

echo "Starting isolated PostgreSQL and Dockerized Planner"
docker "${COMPOSE_ARGS[@]}" up --build --detach postgres planner
wait_for_planner

"$PYTHON_BIN" - "$PLANNER_PORT" <<'PY'
import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

planner_port = int(sys.argv[1])
base_url = f"http://127.0.0.1:{planner_port}"


def request(method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"content-type": "application/json"} if data is not None else {}
    try:
        with urlopen(Request(base_url + path, data=data, headers=headers, method=method), timeout=15) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {path} returned HTTP {error.code}: {detail}") from error


def assert_live_view(run: dict[str, object], phase: str) -> None:
    live_view = run.get("live_view")
    if not isinstance(live_view, dict):
        raise SystemExit(f"{phase} response is missing live_view")
    image_url = live_view.get("image_url")
    if not isinstance(image_url, str) or not image_url.startswith("data:image/png;base64,"):
        raise SystemExit(f"{phase} response did not include a PNG data URL")
    if live_view.get("width") != 1024 or live_view.get("height") != 768:
        raise SystemExit(f"{phase} screenshot dimensions were not normalized to 1024x768: {live_view}")


created = request("POST", "/api/runs", {"task": "Observe the current desktop only; do not perform any action."})
run_id = created.get("id")
if not isinstance(run_id, str) or not run_id:
    raise SystemExit("create run response is missing an id")
assert_live_view(created, "create run")

refreshed = request("POST", f"/api/runs/{run_id}/observe")
assert_live_view(refreshed, "refresh observation")
events = refreshed.get("events")
if not isinstance(events, list) or not any(
    isinstance(event, dict) and event.get("type") == "live_view_refreshed" for event in events
):
    raise SystemExit("refresh observation response is missing the live_view_refreshed event")

print(f"[ok] Dockerized Planner observed the host macOS desktop twice for {run_id}")
PY

echo "[ok] macOS Host Executor Docker smoke test passed without executing desktop actions"
