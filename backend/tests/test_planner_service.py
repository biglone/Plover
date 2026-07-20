import unittest
from concurrent.futures import ThreadPoolExecutor
from os import environ
from tempfile import TemporaryDirectory
from unittest.mock import patch

import grpc
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from planner_service.app import create_app
from planner_service.executor_gateway import GrpcExecutorGateway, LocalExecutorGateway
from planner_service.planner import DeterministicPlanner
from planner_service.store import PlannerRepository, SqlitePlannerRepository


class PlannerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        from planner_service.planner import DeterministicPlanner

        self.repository = PlannerRepository()
        self.client = TestClient(create_app(self.repository, DeterministicPlanner(), LocalExecutorGateway()))

    def test_create_run_and_replan_preserve_completed_history(self) -> None:
        created = self.client.post("/api/runs", json={"task": "Open a report"})
        self.assertEqual(created.status_code, 201)
        run = created.json()
        run_id = run["id"]

        progressed = self.client.post(f"/api/runs/{run_id}/steps/complete")
        self.assertEqual(progressed.status_code, 200)
        progressed_json = progressed.json()
        completed = progressed_json["active_version"]["plan"]["completed"]
        self.assertEqual([step["id"] for step in completed], ["step-1"])

        proposal_response = self.client.post(
            f"/api/runs/{run_id}/replan",
            json={"guidance": "Select the second option instead"},
        )
        self.assertEqual(proposal_response.status_code, 201)
        proposal = proposal_response.json()
        proposal_completed = proposal["version"]["plan"]["completed"]
        self.assertEqual([step["id"] for step in proposal_completed], ["step-1"])

        approved = self.client.post(
            f"/api/runs/{run_id}/proposals/{proposal['id']}/approve",
        )
        self.assertEqual(approved.status_code, 200)
        approved_json = approved.json()
        active_completed = approved_json["active_version"]["plan"]["completed"]
        self.assertEqual([step["id"] for step in active_completed], ["step-1"])
        self.assertEqual(approved_json["status"], "running")

    def test_annotation_replan_tracks_recent_screenshots(self) -> None:
        run = self.client.post("/api/runs", json={"task": "Fill the form"}).json()
        run_id = run["id"]

        for index in range(4):
            response = self.client.post(
                f"/api/runs/{run_id}/replan",
                json={
                    "annotation": {
                        "screenshot": f"screen-{index}.png",
                        "x": 10,
                        "y": 20,
                        "width": 30,
                        "height": 40,
                    }
                },
            )
            self.assertEqual(response.status_code, 201)

        state = self.client.get(f"/api/runs/{run_id}")
        self.assertEqual(state.status_code, 200)
        stored = self.repository.get(run_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.screenshots, ["screen-1.png", "screen-2.png", "screen-3.png"])

    def test_replan_requires_a_trigger(self) -> None:
        run = self.client.post("/api/runs", json={"task": "Fill the form"}).json()
        run_id = run["id"]

        response = self.client.post(f"/api/runs/{run_id}/replan", json={})

        self.assertEqual(response.status_code, 422)

    def test_executor_failure_creates_system_driven_recovery_proposal(self) -> None:
        run = self.client.post("/api/runs", json={"task": "Navigate the dashboard"}).json()

        response = self.client.post(
            f"/api/runs/{run['id']}/failures",
            json={"failure_type": "REPEAT_CLICK_MENU"},
        )

        self.assertEqual(response.status_code, 201)
        proposal = response.json()
        self.assertEqual(proposal["version"]["cause"], "system_driven_ir")
        self.assertIn("REPEAT_CLICK_MENU", proposal["rationale"])

    def test_execute_next_step_updates_live_view_and_completed_step(self) -> None:
        run = self.client.post("/api/runs", json={"task": "Open a report"}).json()

        response = self.client.post(f"/api/runs/{run['id']}/execute-next")

        self.assertEqual(response.status_code, 200)
        updated = response.json()
        self.assertEqual(updated["active_version"]["plan"]["completed"][0]["id"], "step-1")
        self.assertTrue(updated["active_version"]["plan"]["completed"][0]["ui_summary"])
        self.assertTrue(updated["live_view"]["image_url"].startswith("data:image/png;base64,"))

    def test_observe_refreshes_live_view(self) -> None:
        run = self.client.post("/api/runs", json={"task": "Open a report"}).json()

        response = self.client.post(f"/api/runs/{run['id']}/observe")

        self.assertEqual(response.status_code, 200)
        observed = response.json()
        self.assertEqual(observed["live_view"]["width"], 1024)
        self.assertEqual(observed["live_view"]["height"], 768)

    def test_live_websocket_streams_a_frame(self) -> None:
        run = self.client.post("/api/runs", json={"task": "Open a report"}).json()

        with self.client.websocket_connect(f"/api/runs/{run['id']}/live") as websocket:
            frame = websocket.receive_json()

        self.assertEqual(frame["type"], "frame")
        self.assertEqual(frame["run_id"], run["id"])
        self.assertEqual(frame["width"], 1024)
        self.assertTrue(frame["image_url"].startswith("data:image/png;base64,"))

    def test_vnc_websocket_closes_cleanly_when_target_is_missing(self) -> None:
        run = self.client.post("/api/runs", json={"task": "Open a report"}).json()

        with patch.dict(environ, {"PLOVER_VNC_TARGET": ""}):
            with self.client.websocket_connect(f"/api/runs/{run['id']}/vnc") as websocket:
                with self.assertRaises(WebSocketDisconnect) as closed:
                    websocket.receive_bytes()

        self.assertEqual(closed.exception.code, 1013)
        self.assertEqual(closed.exception.reason, "PLOVER_VNC_TARGET is not configured")

    def test_remote_grpc_gateway_executes_against_executor_service(self) -> None:
        from executor_service import executor_pb2_grpc
        from executor_service.driver import MockEnvironmentDriver
        from executor_service.service import ExecutorService

        server = grpc.server(ThreadPoolExecutor(max_workers=2))
        executor_pb2_grpc.add_ExecutorServicer_to_server(
            ExecutorService(MockEnvironmentDriver(screenshot_bytes=b"png")),
            server,
        )
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        gateway = GrpcExecutorGateway(f"127.0.0.1:{port}")
        try:
            run = self.client.post("/api/runs", json={"task": "Use the remote executor"}).json()
            remote_app = TestClient(
                create_app(
                    PlannerRepository(),
                    executor=gateway,
                )
            )
            remote_run = remote_app.post("/api/runs", json={"task": "Use the remote executor"}).json()
            response = remote_app.post(f"/api/runs/{remote_run['id']}/execute-next")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["active_version"]["plan"]["completed"][0]["id"],
                "step-1",
            )
            self.assertTrue(run["live_view"]["image_url"])
        finally:
            gateway.close()
            server.stop(0)

    def test_sqlite_repository_restores_run_artifacts_after_reopen(self) -> None:
        with TemporaryDirectory() as directory:
            path = f"{directory}/plover.sqlite3"
            first_repository = SqlitePlannerRepository(path)
            first_client = TestClient(
                create_app(
                    first_repository,
                    DeterministicPlanner(),
                    LocalExecutorGateway(),
                )
            )
            created = first_client.post("/api/runs", json={"task": "Persist this run"}).json()
            run_id = created["id"]
            first_client.post(f"/api/runs/{run_id}/execute-next")
            proposal = first_client.post(
                f"/api/runs/{run_id}/replan",
                json={"guidance": "Use the alternate visible option"},
            ).json()
            first_repository.close()

            second_repository = SqlitePlannerRepository(path)
            restored = second_repository.get(run_id)
            self.assertIsNotNone(restored)
            self.assertEqual(restored.task, "Persist this run")
            self.assertEqual(len(restored.versions), 2)
            self.assertIn(proposal["id"], restored.proposals)
            self.assertTrue(restored.latest_screenshot_png)
            self.assertGreaterEqual(len(restored.events), 3)
            second_repository.close()

    def test_sensitive_task_is_paused_before_execution(self) -> None:
        run = self.client.post(
            "/api/runs",
            json={"task": "Enter the password into the login form"},
        ).json()

        self.assertEqual(run["status"], "paused")
        self.assertEqual(run["events"][-1]["type"], "safety_stop")
        self.assertEqual(run["active_safety_stop"]["category"], "sensitive_data")

        blocked = self.client.post(f"/api/runs/{run['id']}/execute-next").json()

        self.assertEqual(blocked["status"], "paused")
        self.assertEqual(blocked["events"][-1]["type"], "execution_blocked")

    def test_safety_paused_run_can_resume_after_external_handling(self) -> None:
        run = self.client.post(
            "/api/runs",
            json={"task": "Enter the password into the login form"},
        ).json()

        response = self.client.post(
            f"/api/runs/{run['id']}/resume",
            json={
                "handled_outside": True,
                "guidance": "The password was entered manually outside the agent.",
            },
        )

        self.assertEqual(response.status_code, 201)
        proposal = response.json()
        self.assertEqual(proposal["version"]["cause"], "user_guidance")
        self.assertIn("pending suffix", proposal["rationale"])

        state = self.client.get(f"/api/runs/{run['id']}").json()
        self.assertEqual(state["status"], "paused")
        self.assertEqual(state["active_safety_stop"], None)
        self.assertEqual(state["events"][-1]["type"], "safety_resume_proposed")

    def test_safety_resume_requires_clarification_when_not_handled_outside(self) -> None:
        run = self.client.post(
            "/api/runs",
            json={"task": "Choose whatever looks best"},
        ).json()

        response = self.client.post(
            f"/api/runs/{run['id']}/resume",
            json={"handled_outside": False},
        )

        self.assertEqual(response.status_code, 422)

    def test_sensitive_replan_is_rejected(self) -> None:
        run = self.client.post("/api/runs", json={"task": "Open the report"}).json()

        response = self.client.post(
            f"/api/runs/{run['id']}/replan",
            json={"guidance": "Enter the API key now"},
        )

        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
