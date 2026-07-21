#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PLOVER_E2E_PLANNER_PORT="${PLOVER_E2E_PLANNER_PORT:-8013}" \
PLOVER_E2E_FRONTEND_PORT="${PLOVER_E2E_FRONTEND_PORT:-5176}" \
PLOVER_E2E_TARGET="${PLOVER_E2E_TARGET:-$ROOT_DIR/e2e/test_safety_pause_flow.py}" \
  "$ROOT_DIR/scripts/run_browser_e2e.sh"
