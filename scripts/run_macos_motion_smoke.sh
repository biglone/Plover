#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PLOVER_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This smoke test must run on a macOS host." >&2
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing Python interpreter: $PYTHON_BIN" >&2
  exit 1
fi

PLOVER_EXECUTOR_DRIVER=macos \
PYTHONPATH=backend \
  "$PYTHON_BIN" -m executor_service.macos_smoke --verify-motion
