import os
import unittest
from unittest.mock import patch

from executor_service import executor_pb2
from planner_service.executor_gateway import LocalExecutorGateway, actions_for_step, create_executor_gateway_from_env
from plover_core.models import PlanStep, StepAction


class ExecutorGatewayTests(unittest.TestCase):
    def test_actions_for_step_prefers_structured_executor_actions(self) -> None:
        step = PlanStep(
            "step-1",
            "Ignore the fallback heuristics",
            actions=(
                StepAction("click", x=12, y=20),
                StepAction("type", text="hello"),
                StepAction("keys", keys=("CTRL", "ENTER")),
                StepAction("observe"),
            ),
        )

        actions = actions_for_step(step)

        self.assertEqual(actions[0].pointer.kind, executor_pb2.PointerAction.CLICK)
        self.assertEqual((actions[0].pointer.x, actions[0].pointer.y), (12, 20))
        self.assertEqual(actions[1].keyboard.text, "hello")
        self.assertEqual(list(actions[2].keyboard.keys), ["CTRL", "ENTER"])
        self.assertTrue(actions[3].HasField("observe"))

    def test_local_gateway_executes_structured_actions_without_keyword_guessing(self) -> None:
        gateway = LocalExecutorGateway()
        step = PlanStep(
            "step-1",
            "This sentence does not mention click or type",
            actions=(
                StepAction("click", x=33, y=44),
                StepAction("type", text="structured input"),
            ),
        )

        result = gateway.execute_step("run-1", step)
        driver = gateway._driver_for("run-1")

        self.assertTrue(result.ok)
        self.assertIn("Clicking at (33, 44)", result.summary)
        self.assertIn("Typing structured input", result.summary)
        self.assertEqual(
            driver.actions,
            [
                ("click", (33, 44)),
                ("screenshot", ()),
                ("type_text", ("structured input",)),
                ("screenshot", ()),
            ],
        )

    def test_local_gateway_fail_once_scenario_only_fails_the_first_execution_per_run(self) -> None:
        gateway = LocalExecutorGateway(scenario="fail_once")
        step = PlanStep(
            "step-1",
            "Try the primary path once",
            actions=(StepAction("observe"),),
        )

        first = gateway.execute_step("run-1", step)
        second = gateway.execute_step("run-1", step)
        third = gateway.execute_step("run-2", step)

        self.assertFalse(first.ok)
        self.assertEqual(first.failure_type, "REPEAT_CLICK_MENU")
        self.assertIn("Retry with a different tactic", first.summary)
        self.assertEqual(first.events[0].kind, "failure_detected")

        self.assertTrue(second.ok)
        self.assertIn("Capturing the current screen", second.summary)
        self.assertFalse(third.ok)

    def test_create_executor_gateway_from_env_applies_local_scenario(self) -> None:
        with patch.dict(os.environ, {"PLOVER_LOCAL_EXECUTOR_SCENARIO": "fail_once"}, clear=False):
            gateway = create_executor_gateway_from_env()

        self.assertIsInstance(gateway, LocalExecutorGateway)
        self.assertEqual(gateway._scenario, "fail_once")
