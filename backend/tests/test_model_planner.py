import unittest

from plover_core.models import ExecutionStatus, PlanState, PlanStep, PlanVersion, ReplanCause
from planner_service.model_planner import ModelPlanner


class FakeChatModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def complete(self, *, system: str, user: str, image_urls: tuple[str, ...] = ()) -> str:
        self.calls.append({"system": system, "user": user, "image_urls": image_urls})
        return self.response


class ModelPlannerTests(unittest.TestCase):
    def test_model_planner_creates_initial_plan_from_xml(self) -> None:
        model = FakeChatModel(
            """
            <analysis>Inspect then act.</analysis>
            <steps>
              <completed />
              <pending>
                <step>Capture the current screen</step>
                <step>Verify the visible outcome</step>
              </pending>
            </steps>
            """
        )

        plan = ModelPlanner(model).create_initial("Open a report")

        self.assertEqual(len(plan.plan.pending), 2)
        self.assertIn("Plover Planner", model.calls[0]["system"])

    def test_model_replan_preserves_completed_steps_and_passes_context(self) -> None:
        current = PlanVersion(
            id="version-1",
            plan=PlanState(
                completed=(PlanStep("step-1", "Open the report", ExecutionStatus.COMPLETED),),
                pending=(PlanStep("step-2", "Select the wrong option"),),
            ),
            parent_id=None,
            cause=ReplanCause.INITIAL,
            created_at="now",
        )
        model = FakeChatModel(
            """
            <analysis>The marked region identifies the replacement option.</analysis>
            <steps>
              <completed><step id="step-1">Open the report</step></completed>
              <pending><step>Click the marked replacement option</step></pending>
            </steps>
            """
        )

        proposal = ModelPlanner(model).propose_repair(
            current,
            guidance="Use the marked option",
            annotation=None,
            failure_type=None,
            screenshots=(
                "data:image/png;base64,one",
                "data:image/png;base64,two",
                "data:image/png;base64,three",
            ),
        )

        self.assertEqual(proposal.version.plan.completed, current.plan.completed)
        self.assertEqual(proposal.version.cause, ReplanCause.USER_GUIDANCE)
        self.assertIn("<current_plan>", model.calls[0]["user"])
        self.assertIn("<recent_screenshots count=\"3\" />", model.calls[0]["user"])
        self.assertEqual(
            model.calls[0]["image_urls"],
            (
                "data:image/png;base64,one",
                "data:image/png;base64,two",
                "data:image/png;base64,three",
            ),
        )
