#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PLOVER_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

require_file() {
  if [[ ! -e "$1" ]]; then
    echo "Missing $1" >&2
    exit 1
  fi
}

if [[ "$PYTHON_BIN" != */* ]]; then
  PYTHON_BIN="$(command -v "$PYTHON_BIN" || true)"
fi
require_file "$PYTHON_BIN"

echo "==> Backend unit and acceptance tests"
PYTHONPATH=backend "$PYTHON_BIN" -m unittest discover -s backend/tests -v

echo "==> Frontend unit tests"
npm --prefix "$ROOT_DIR/frontend" run test

echo "==> OpenAPI contract check"
"$ROOT_DIR/scripts/check_openapi.sh"

echo "==> Frontend production build"
npm --prefix "$ROOT_DIR/frontend" run build

echo "==> Browser E2E: manual action flow"
PLOVER_PYTHON_BIN="$PYTHON_BIN" "$ROOT_DIR/scripts/run_browser_e2e.sh"

echo "==> Browser E2E: recovery proposal flow"
PLOVER_PYTHON_BIN="$PYTHON_BIN" "$ROOT_DIR/scripts/run_browser_recovery_e2e.sh"

echo "==> Browser E2E: safety pause resume flow"
PLOVER_PYTHON_BIN="$PYTHON_BIN" "$ROOT_DIR/scripts/run_browser_safety_e2e.sh"

echo "==> Browser E2E: annotation repair flow"
PLOVER_PYTHON_BIN="$PYTHON_BIN" "$ROOT_DIR/scripts/run_browser_annotation_e2e.sh"
