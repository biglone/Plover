import unittest

from plover_core.models import ExecutionStatus, PlanState, PlanStep, ReplanCause, StepAction
from plover_core.plan import PlanInvariantError, approve_proposal, complete_next_step, replace_pending


class PlanStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.first = PlanStep("step-1", "Open the settings panel")
        self.second = PlanStep("step-2", "Select the second option")
        self.current = PlanState(pending=(self.first, self.second))

    def test_completing_a_step_moves_only_the_head(self) -> None:
        updated = complete_next_step(self.current, ui_summary="Opening settings panel")

        self.assertEqual([step.id for step in updated.completed], ["step-1"])
        self.assertEqual([step.id for step in updated.pending], ["step-2"])
        self.assertEqual(updated.completed[0].status, ExecutionStatus.COMPLETED)

    def test_replacing_pending_preserves_completed_fingerprint(self) -> None:
        progressed = complete_next_step(self.current)
        repaired = replace_pending(progressed, [PlanStep("step-3", "Choose the visible recovery option")])

        self.assertEqual(
            progressed.completed_fingerprint(),
            repaired.completed_fingerprint(),
        )
        self.assertEqual([step.id for step in repaired.pending], ["step-3"])

    def test_pending_completed_step_is_rejected(self) -> None:
        with self.assertRaises(PlanInvariantError):
            replace_pending(
                self.current,
                [PlanStep("step-3", "Already done", status=ExecutionStatus.COMPLETED)],
            )

    def test_approval_rejects_stale_or_mutated_history(self) -> None:
        from plover_core.models import PlanVersion, Proposal

        base = PlanVersion("v1", complete_next_step(self.current), None, ReplanCause.INITIAL, "now")
        bad_plan = PlanState(
            completed=(PlanStep("different", "Changed history", ExecutionStatus.COMPLETED),),
            pending=(),
        )
        proposal_version = PlanVersion("v2", bad_plan, "v1", ReplanCause.USER_GUIDANCE, "now")
        proposal = Proposal("proposal-1", "v1", proposal_version, "Change", "Because")

        with self.assertRaises(PlanInvariantError):
            approve_proposal(base, proposal)

    def test_approval_rejects_mutated_completed_actions(self) -> None:
        from plover_core.models import PlanVersion, Proposal

        completed = PlanStep(
            "step-1",
            "Open the settings panel",
            ExecutionStatus.COMPLETED,
            actions=(StepAction("click", x=12, y=20),),
        )
        base = PlanVersion(
            "v1",
            PlanState(completed=(completed,), pending=()),
            None,
            ReplanCause.INITIAL,
            "now",
        )
        mutated = PlanStep(
            "step-1",
            "Open the settings panel",
            ExecutionStatus.COMPLETED,
            actions=(StepAction("click", x=24, y=36),),
        )
        proposal = Proposal(
            "proposal-1",
            "v1",
            PlanVersion(
                "v2",
                PlanState(completed=(mutated,), pending=()),
                "v1",
                ReplanCause.USER_GUIDANCE,
                "now",
            ),
            "Change",
            "Because",
        )

        with self.assertRaises(PlanInvariantError):
            approve_proposal(base, proposal)
