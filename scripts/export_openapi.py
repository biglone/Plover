#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from planner_service.app import create_app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the Planner OpenAPI contract.")
    parser.add_argument("--output", type=Path, help="Write the schema to this file instead of stdout.")
    args = parser.parse_args()

    schema = create_app().openapi()
    payload = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
        return 0
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
