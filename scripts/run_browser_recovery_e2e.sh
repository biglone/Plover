#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PLOVER_E2E_PLANNER_PORT="${PLOVER_E2E_PLANNER_PORT:-8012}" \
PLOVER_E2E_FRONTEND_PORT="${PLOVER_E2E_FRONTEND_PORT:-5175}" \
PLOVER_E2E_TARGET="${PLOVER_E2E_TARGET:-$ROOT_DIR/e2e/test_failure_recovery_flow.py}" \
PLOVER_LOCAL_EXECUTOR_SCENARIO="${PLOVER_LOCAL_EXECUTOR_SCENARIO:-fail_once}" \
  "$ROOT_DIR/scripts/run_browser_e2e.sh"
