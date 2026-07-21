import unittest

from executor_service import executor_pb2
from planner_service.executor_gateway import LocalExecutorGateway, actions_for_step
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
