from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from plover_core.models import (
    Annotation,
    PlanState,
    PlanStep,
    PlanVersion,
    Proposal,
    ReplanCause,
)
from plover_core.plan import replace_pending
from planner_service.store import utc_now


class DeterministicPlanner:
    """Offline planner used until a vision-model adapter is configured."""

    def create_initial(self, task: str) -> PlanVersion:
        steps = (
            PlanStep("step-1", "Capture the current screen before acting"),
            PlanStep("step-2", f"Perform the requested task: {task}"),
            PlanStep("step-3", "Verify the visible outcome and stop"),
        )
        return PlanVersion(
            id=f"version-{uuid4().hex[:10]}",
            plan=PlanState(pending=steps),
            parent_id=None,
            cause=ReplanCause.INITIAL,
            created_at=utc_now(),
            derived_constraints=("Preserve completed steps", "Verify the final visible state"),
        )

    def propose_repair(
        self,
        current: PlanVersion,
        *,
        guidance: str | None,
        annotation: Annotation | None,
        failure_type: str | None,
        screenshots: tuple[str, ...] = (),
        rationale: str | None = None,
    ) -> Proposal:
        if annotation:
            bbox = (
                f"({annotation.x}, {annotation.y}, "
                f"{annotation.width}, {annotation.height})"
            )
            instruction = f"Act on the interface region marked at {bbox}"
            summary = "Use the marked screen region to repair the pending action"
            default_rationale = (
                "The spatial annotation narrows the target while preserving all "
                "completed work."
            )
            cause = ReplanCause.ANNOTATION
            constraints = (f"Use annotation bbox {bbox}", "Preserve completed steps")
        elif failure_type:
            instruction = "Change tactic and retry the failed action using the current screen"
            summary = "Change tactic and retry the failed action"
            default_rationale = (
                f"Repeated non-progress was detected ({failure_type}); a different "
                "interaction path is proposed."
            )
            cause = ReplanCause.SYSTEM_DRIVEN_IR
            constraints = (f"Recover from {failure_type}", "Preserve completed steps")
        else:
            normalized = (guidance or "Revise the pending action using the current screen").strip()
            instruction = normalized[0].upper() + normalized[1:]
            summary = instruction
            default_rationale = "The guidance changes only the editable remainder of the plan."
            cause = ReplanCause.USER_GUIDANCE
            constraints = ("Apply user guidance to pending steps only", "Preserve completed steps")

        pending = [PlanStep(f"step-{uuid4().hex[:8]}", instruction)]
        pending.append(PlanStep(f"step-{uuid4().hex[:8]}", "Verify the visible outcome and stop"))
        new_plan = replace_pending(current.plan, pending)
        version = PlanVersion(
            id=f"version-{uuid4().hex[:10]}",
            plan=new_plan,
            parent_id=current.id,
            cause=cause,
            created_at=utc_now(),
            derived_constraints=constraints,
        )
        return Proposal(
            id=f"proposal-{uuid4().hex[:10]}",
            base_version_id=current.id,
            version=version,
            summary=summary,
            rationale=rationale or default_rationale,
            annotation=annotation,
        )
