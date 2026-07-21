#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PLOVER_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

exec env PYTHONPATH=backend "$PYTHON_BIN" -m planner_service.migrate
