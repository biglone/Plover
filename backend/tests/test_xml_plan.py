import unittest

from plover_core.models import ExecutionStatus, PlanState, PlanStep, PlanVersion, ReplanCause, StepAction
from plover_core.xml_plan import PlanParseError, parse_plan_response


class XmlPlanTests(unittest.TestCase):
    def test_parses_initial_plan_with_ui_summary(self) -> None:
        response = """
        <analysis>Inspect the current form before making a change.</analysis>
        <steps>
          <completed />
          <pending>
            <step id="step-a">
              <instruction>Capture the current screen</instruction>
              <ui_summary>Capturing the current screen</ui_summary>
            </step>
            <step>Verify the visible result</step>
          </pending>
        </steps>
        """

        parsed = parse_plan_response(response)

        self.assertEqual(parsed.analysis, "Inspect the current form before making a change.")
        self.assertEqual(len(parsed.state.pending), 2)
        self.assertEqual(parsed.state.pending[0].id, "step-a")
        self.assertEqual(parsed.state.pending[0].status, ExecutionStatus.PENDING)
        self.assertEqual(parsed.state.pending[0].ui_summary, "Capturing the current screen")

    def test_parses_structured_executor_actions(self) -> None:
        response = """
        <analysis>Use the visible search field.</analysis>
        <steps>
          <completed />
          <pending>
            <step id="step-a">
              <instruction>Search for the report and inspect the result</instruction>
              <ui_summary>Typing the report name into search</ui_summary>
              <actions>
                <click x="120" y="240" />
                <type text="quarterly report" />
                <keys keys="CTRL,ENTER" />
                <wait milliseconds="250" />
                <observe />
              </actions>
            </step>
          </pending>
        </steps>
        """

        parsed = parse_plan_response(response)

        self.assertEqual(
            parsed.state.pending[0].actions,
            (
                StepAction("click", x=120, y=240),
                StepAction("type", text="quarterly report"),
                StepAction("keys", keys=("CTRL", "ENTER")),
                StepAction("wait", milliseconds=250),
                StepAction("observe"),
            ),
        )

    def test_completed_history_must_match_current_plan(self) -> None:
        current = PlanVersion(
            id="version-1",
            plan=PlanState(
                completed=(PlanStep("step-1", "Open the report", ExecutionStatus.COMPLETED),),
                pending=(PlanStep("step-2", "Select the second option"),),
            ),
            parent_id=None,
            cause=ReplanCause.INITIAL,
            created_at="now",
        )
        response = """
        <analysis>Repair the pending selection.</analysis>
        <steps>
          <completed><step id="step-1">Open a different report</step></completed>
          <pending><step>Select the second option</step></pending>
        </steps>
        """

        with self.assertRaises(PlanParseError):
            parse_plan_response(response, current=current)

    def test_malformed_or_empty_plan_is_rejected(self) -> None:
        with self.assertRaises(PlanParseError):
            parse_plan_response("<analysis>Missing steps</analysis>")
        with self.assertRaises(PlanParseError):
            parse_plan_response(
                "<analysis>Empty</analysis><steps><completed /><pending /></steps>"
            )
        with self.assertRaises(PlanParseError):
            parse_plan_response(
                """
                <analysis>Invalid action.</analysis>
                <steps><completed /><pending>
                  <step><instruction>Click the button</instruction><actions><click x="1" /></actions></step>
                </pending></steps>
                """
            )

    def test_completed_history_rejects_action_mutation(self) -> None:
        current = PlanVersion(
            id="version-1",
            plan=PlanState(
                completed=(
                    PlanStep(
                        "step-1",
                        "Open the report",
                        ExecutionStatus.COMPLETED,
                        actions=(StepAction("click", x=12, y=20),),
                    ),
                ),
                pending=(PlanStep("step-2", "Select the second option"),),
            ),
            parent_id=None,
            cause=ReplanCause.INITIAL,
            created_at="now",
        )
        response = """
        <analysis>Repair the pending selection.</analysis>
        <steps>
          <completed>
            <step id="step-1">
              <instruction>Open the report</instruction>
              <actions><click x="90" y="90" /></actions>
            </step>
          </completed>
          <pending><step>Select the second option</step></pending>
        </steps>
        """

        with self.assertRaises(PlanParseError):
            parse_plan_response(response, current=current)

    def test_completed_history_can_omit_existing_actions(self) -> None:
        current = PlanVersion(
            id="version-1",
            plan=PlanState(
                completed=(
                    PlanStep(
                        "step-1",
                        "Open the report",
                        ExecutionStatus.COMPLETED,
                        actions=(StepAction("click", x=12, y=20),),
                    ),
                ),
                pending=(PlanStep("step-2", "Select the second option"),),
            ),
            parent_id=None,
            cause=ReplanCause.INITIAL,
            created_at="now",
        )
        response = """
        <analysis>Repair the pending selection.</analysis>
        <steps>
          <completed><step id="step-1">Open the report</step></completed>
          <pending><step>Select the second option</step></pending>
        </steps>
        """

        parsed = parse_plan_response(response, current=current)

        self.assertEqual(parsed.state.completed[0].actions, (StepAction("click", x=12, y=20),))
