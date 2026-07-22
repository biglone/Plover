import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from planner_service.app import create_app
from planner_service.executor_gateway import LocalExecutorGateway
from planner_service.planner import DeterministicPlanner
from planner_service.store import PlannerRepository


class ApiAuthTests(unittest.TestCase):
    def test_http_requests_require_a_token_when_configured(self) -> None:
        with patch.dict(os.environ, {"PLOVER_API_TOKEN": "secret-token"}, clear=False):
            client = TestClient(create_app(PlannerRepository(), DeterministicPlanner(), LocalExecutorGateway()))

            rejected = client.post("/api/runs", json={"task": "Open a report"})
            accepted = client.post(
                "/api/runs",
                json={"task": "Open a report"},
                headers={"Authorization": "Bearer secret-token"},
            )

        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(accepted.status_code, 201)

    def test_live_websocket_requires_the_token_query_parameter(self) -> None:
        with patch.dict(os.environ, {"PLOVER_API_TOKEN": "secret-token"}, clear=False):
            client = TestClient(create_app(PlannerRepository(), DeterministicPlanner(), LocalExecutorGateway()))
            run = client.post(
                "/api/runs",
                json={"task": "Open a report"},
                headers={"Authorization": "Bearer secret-token"},
            ).json()

            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect(f"/api/runs/{run['id']}/live") as websocket:
                    websocket.receive_json()

            with client.websocket_connect(f"/api/runs/{run['id']}/live?token=secret-token") as websocket:
                frame = websocket.receive_json()

        self.assertEqual(frame["type"], "frame")
        self.assertEqual(frame["run_id"], run["id"])


if __name__ == "__main__":
    unittest.main()
