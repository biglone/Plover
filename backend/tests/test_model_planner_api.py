import unittest

from fastapi.testclient import TestClient

from planner_service.app import create_app
from planner_service.executor_gateway import LocalExecutorGateway
from planner_service.store import PlannerRepository


class InvalidPlanner:
    def create_initial(self, task: str):
        from plover_core.xml_plan import PlanParseError

        raise PlanParseError("missing pending block")


class ModelPlannerApiTests(unittest.TestCase):
    def test_invalid_model_plan_is_rejected_without_creating_a_run(self) -> None:
        repository = PlannerRepository()
        client = TestClient(create_app(repository, InvalidPlanner(), LocalExecutorGateway()))

        response = client.post("/api/runs", json={"task": "Open a report"})

        self.assertEqual(response.status_code, 422)
        self.assertIsNone(next(iter(repository._runs.values()), None))


if __name__ == "__main__":
    unittest.main()
