import unittest

from plover_core.models import ExecutionStatus, PlanState, PlanStep, PlanVersion, ReplanCause
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
