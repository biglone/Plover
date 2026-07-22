#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PLOVER_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
PYTHON_LABEL="$PYTHON_BIN"
SNAPSHOT_FILE="$ROOT_DIR/backend/openapi.json"
TMP_FILE="$(mktemp "${TMPDIR:-/tmp}/plover-openapi.XXXXXX.json")"

cleanup() {
  rm -f "$TMP_FILE"
}
trap cleanup EXIT

if [[ "$PYTHON_BIN" != */* ]]; then
  RESOLVED_PYTHON_BIN="$(command -v "$PYTHON_BIN" || true)"
  if [[ -z "$RESOLVED_PYTHON_BIN" && "$PYTHON_BIN" == "python" ]]; then
    RESOLVED_PYTHON_BIN="$(command -v python3 || true)"
  fi
  if [[ -n "$RESOLVED_PYTHON_BIN" ]]; then
    PYTHON_BIN="$RESOLVED_PYTHON_BIN"
  fi
fi

if [[ ! -e "$PYTHON_BIN" ]]; then
  echo "Missing Python interpreter: $PYTHON_LABEL" >&2
  exit 1
fi

"$PYTHON_BIN" "$ROOT_DIR/scripts/export_openapi.py" --output "$TMP_FILE"

if [[ ! -f "$SNAPSHOT_FILE" ]]; then
  echo "Missing OpenAPI snapshot: $SNAPSHOT_FILE" >&2
  exit 1
fi

diff -u "$SNAPSHOT_FILE" "$TMP_FILE"
