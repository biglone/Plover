from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import unittest

import grpc
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from executor_service import executor_pb2_grpc
from executor_service.driver import MockEnvironmentDriver
from executor_service.service import ExecutorService
from planner_service.app import create_app
from planner_service.executor_gateway import ExecutorEvent, ExecutorResult, LiveObservation
from planner_service.planner import DeterministicPlanner
from planner_service.store import PlannerRepository


def _png(label: str, size: tuple[int, int] = (1024, 768)) -> bytes:
    image = Image.new("RGB", size, color=(246, 244, 236))
    draw = ImageDraw.Draw(image)
    draw.text((40, 40), label, fill=(42, 58, 68))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class FlakyExecutorGateway:
    def __init__(self) -> None:
        self._failed_runs: set[str] = set()

    def observe(self, run_id: str) -> LiveObservation:
        return LiveObservation(
            screenshot_png=_png(f"observe {run_id}"),
            width=1024,
            height=768,
        )

    def execute_step(self, run_id: str, step) -> ExecutorResult:
        if run_id not in self._failed_runs:
            self._failed_runs.add(run_id)
            return ExecutorResult(
                ok=False,
                summary="Retry with a different tactic",
                screenshot_png=_png(f"failed {step.id}"),
                failure_type="REPEAT_CLICK_MENU",
                events=(
                    ExecutorEvent(
                        kind="failure_detected",
                        ui_summary="Retry with a different tactic",
                        detail="Repeated clicks were detected",
                        created_at="2026-07-21T00:00:00+00:00",
                        step_id=step.id,
                    ),
                ),
            )
        return ExecutorResult(
            ok=True,
            summary=f"Recovered {step.instruction}",
            screenshot_png=_png(f"success {step.id}"),
        )


class AcceptanceTests(unittest.TestCase):
    def test_remote_executor_happy_path_completes_a_run(self) -> None:
        server = grpc.server(ThreadPoolExecutor(max_workers=2))
        executor_pb2_grpc.add_ExecutorServicer_to_server(
            ExecutorService(MockEnvironmentDriver(screenshot_bytes=_png("executor"))),
            server,
        )
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        from planner_service.executor_gateway import GrpcExecutorGateway

        remote = GrpcExecutorGateway(f"127.0.0.1:{port}")
        try:
            client = TestClient(create_app(PlannerRepository(), DeterministicPlanner(), remote))
            run = client.post("/api/runs", json={"task": "Open a report"}).json()
            self.assertTrue(run["live_view"]["image_url"].startswith("data:image/png;base64,"))

            for _ in range(3):
                response = client.post(f"/api/runs/{run['id']}/execute-next")
                self.assertEqual(response.status_code, 200)
                run = response.json()

            self.assertEqual(run["status"], "completed")
            self.assertEqual(
                [step["id"] for step in run["active_version"]["plan"]["completed"]],
                ["step-1", "step-2", "step-3"],
            )
            self.assertIn("executor_action_started", [event["type"] for event in run["events"]])
        finally:
            remote.close()
            server.stop(0)

    def test_annotation_flow_can_approve_and_finish(self) -> None:
        client = TestClient(create_app(PlannerRepository(), DeterministicPlanner()))

        run = client.post("/api/runs", json={"task": "Fill the form"}).json()
        proposal = client.post(
            f"/api/runs/{run['id']}/replan",
            json={
                "annotation": {
                    "screenshot": "data:image/png;base64,annotation",
                    "x": 20,
                    "y": 30,
                    "width": 40,
                    "height": 50,
                }
            },
        ).json()
        self.assertEqual(proposal["version"]["cause"], "annotation")

        approved = client.post(f"/api/runs/{run['id']}/proposals/{proposal['id']}/approve").json()
        self.assertEqual(approved["active_version"]["cause"], "annotation")

        first = client.post(f"/api/runs/{run['id']}/execute-next").json()
        second = client.post(f"/api/runs/{run['id']}/execute-next").json()

        self.assertEqual(len(first["active_version"]["plan"]["completed"]), 1)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(len(second["active_version"]["plan"]["completed"]), 2)

    def test_safety_pause_resume_acceptance_path(self) -> None:
        client = TestClient(create_app(PlannerRepository(), DeterministicPlanner()))

        run = client.post(
            "/api/runs",
            json={"task": "Enter the password into the login form"},
        ).json()
        self.assertEqual(run["status"], "paused")
        self.assertEqual(run["active_safety_stop"]["category"], "sensitive_data")

        proposal = client.post(
            f"/api/runs/{run['id']}/resume",
            json={
                "handled_outside": True,
                "guidance": "The login step was handled manually outside the agent.",
            },
        ).json()
        self.assertEqual(proposal["version"]["cause"], "user_guidance")

        approved = client.post(f"/api/runs/{run['id']}/proposals/{proposal['id']}/approve").json()
        self.assertEqual(approved["status"], "running")
        progressed = client.post(f"/api/runs/{run['id']}/execute-next").json()
        self.assertEqual(len(progressed["active_version"]["plan"]["completed"]), 1)
        self.assertEqual(progressed["status"], "running")

    def test_executor_failure_recovery_acceptance_path(self) -> None:
        client = TestClient(create_app(PlannerRepository(), DeterministicPlanner(), FlakyExecutorGateway()))

        run = client.post("/api/runs", json={"task": "Open a report"}).json()
        failed = client.post(f"/api/runs/{run['id']}/execute-next").json()
        self.assertEqual(failed["status"], "paused")
        self.assertEqual(failed["events"][-1]["type"], "step_execution_failed")

        proposal = next(proposal for proposal in failed["proposals"] if proposal["status"] == "pending")
        self.assertEqual(proposal["version"]["cause"], "system_driven_ir")

        approved = client.post(f"/api/runs/{run['id']}/proposals/{proposal['id']}/approve").json()
        self.assertEqual(approved["status"], "running")
        recovered = client.post(f"/api/runs/{run['id']}/execute-next").json()
        self.assertEqual(len(recovered["active_version"]["plan"]["completed"]), 1)
        self.assertIn("Recovered", recovered["active_version"]["plan"]["completed"][0]["ui_summary"])


if __name__ == "__main__":
    unittest.main()
