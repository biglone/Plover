from __future__ import annotations

import json
from pathlib import Path
import unittest

from planner_service.app import create_app


SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


class OpenApiContractTests(unittest.TestCase):
    def test_openapi_snapshot_matches_the_current_app_schema(self) -> None:
        current = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
        snapshot = SNAPSHOT_PATH.read_text(encoding="utf-8")

        self.assertEqual(current, snapshot)


if __name__ == "__main__":
    unittest.main()
