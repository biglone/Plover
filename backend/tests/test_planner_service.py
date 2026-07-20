import unittest

from fastapi.testclient import TestClient

from planner_service.app import create_app
from planner_service.store import PlannerRepository


class PlannerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        from planner_service.planner import DeterministicPlanner

        self.repository = PlannerRepository()
        self.client = TestClient(create_app(self.repository, DeterministicPlanner()))

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


if __name__ == "__main__":
    unittest.main()
