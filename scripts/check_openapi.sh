#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PLOVER_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
SNAPSHOT_FILE="$ROOT_DIR/backend/openapi.json"
TMP_FILE="$(mktemp "${TMPDIR:-/tmp}/plover-openapi.XXXXXX.json")"

cleanup() {
  rm -f "$TMP_FILE"
}
trap cleanup EXIT

if [[ ! -x "$PYTHON_BIN" && ! -e "$PYTHON_BIN" ]]; then
  echo "Missing Python interpreter: $PYTHON_BIN" >&2
  exit 1
fi

"$PYTHON_BIN" "$ROOT_DIR/scripts/export_openapi.py" --output "$TMP_FILE"

if [[ ! -f "$SNAPSHOT_FILE" ]]; then
  echo "Missing OpenAPI snapshot: $SNAPSHOT_FILE" >&2
  exit 1
fi

diff -u "$SNAPSHOT_FILE" "$TMP_FILE"
