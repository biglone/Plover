#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PLOVER_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
FAILURES=0

load_env_file() {
  local env_file="$1"
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
}

check_command() {
  local command_name="$1"
  if command -v "$command_name" >/dev/null 2>&1; then
    echo "[ok] command available: $command_name"
  else
    echo "[fail] missing command: $command_name"
    FAILURES=$((FAILURES + 1))
  fi
}

check_path() {
  local path="$1"
  local label="$2"
  if [[ -e "$path" ]]; then
    echo "[ok] $label"
  else
    echo "[fail] missing: $path ($label)"
    FAILURES=$((FAILURES + 1))
  fi
}

run_python_check() {
  local label="$1"
  local script="$2"
  if PYTHONPATH=backend "$PYTHON_BIN" -c "$script" >/dev/null 2>&1; then
    echo "[ok] $label"
  else
    echo "[fail] $label"
    FAILURES=$((FAILURES + 1))
  fi
}

load_env_file "$ROOT_DIR/.env"
load_env_file "$ROOT_DIR/.env.local"

echo "Plover dev doctor"
echo "Workspace: $ROOT_DIR"

check_command python3
check_command npm
check_command curl
check_path "$PYTHON_BIN" "backend virtualenv interpreter"
check_path "$ROOT_DIR/frontend/node_modules" "frontend dependencies installed"

if [[ -x "$PYTHON_BIN" ]]; then
  run_python_check "backend dependencies import cleanly" "import fastapi, grpc, PIL"
  run_python_check "planner configuration parses" "from planner_service.model_planner import create_planner; create_planner()"
  run_python_check "repository configuration parses" "from planner_service.store import create_repository; repo = create_repository(); getattr(repo, 'close', lambda: None)()"
  run_python_check "observation source configuration parses" "from planner_service.observation_source import create_observation_source_from_env; create_observation_source_from_env()"
  run_python_check "VNC target configuration parses" "import os; from planner_service.vnc_gateway import VncTarget; target = os.getenv('PLOVER_VNC_TARGET', '').strip(); VncTarget.parse(target) if target else None"
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
  echo "macOS checks"
  if osascript -e 'tell application "System Events" to return UI elements enabled' >/dev/null 2>&1; then
    echo "[ok] System Events GUI scripting is available"
  else
    echo "[warn] System Events GUI scripting is unavailable. Accessibility permission may be missing."
  fi

  if [[ "${PLOVER_EXECUTOR_DRIVER:-mock}" == "macos" && -x "$PYTHON_BIN" ]]; then
    if PYTHONPATH=backend "$PYTHON_BIN" -c 'import pyautogui; pyautogui.size(); pyautogui.screenshot()' >/dev/null 2>&1; then
      echo "[ok] pyautogui can query screen size and capture screenshots"
    else
      echo "[warn] pyautogui could not complete a screenshot. Grant Accessibility and Screen Recording to the terminal or Executor."
    fi
  else
    echo "[ok] macOS desktop control check skipped because PLOVER_EXECUTOR_DRIVER is not set to macos"
  fi
fi

if [[ "$FAILURES" -ne 0 ]]; then
  echo "Doctor found $FAILURES blocking issue(s)."
  exit 1
fi

echo "Doctor finished without blocking issues."
