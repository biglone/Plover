from __future__ import annotations

from dataclasses import replace

from .models import ExecutionStatus, PlanState, PlanStep, PlanVersion, Proposal


class PlanInvariantError(ValueError):
    """Raised when an operation would mutate committed plan history."""


def _validate_pending(pending: tuple[PlanStep, ...]) -> None:
    for step in pending:
        if step.status == ExecutionStatus.COMPLETED:
            raise PlanInvariantError("pending steps cannot be completed")


def replace_pending(current: PlanState, pending: list[PlanStep] | tuple[PlanStep, ...]) -> PlanState:
    """Return a plan with the exact same completed history and a new suffix."""
    new_pending = tuple(pending)
    _validate_pending(new_pending)
    return PlanState(completed=current.completed, pending=new_pending)


def complete_next_step(current: PlanState, *, ui_summary: str | None = None) -> PlanState:
    if not current.pending:
        return current
    next_step = current.pending[0]
    completed_step = replace(next_step, status=ExecutionStatus.COMPLETED, ui_summary=ui_summary)
    return PlanState(completed=current.completed + (completed_step,), pending=current.pending[1:])


def fail_next_step(current: PlanState, reason: str) -> PlanState:
    if not current.pending:
        return current
    failed_step = replace(
        current.pending[0],
        status=ExecutionStatus.FAILED,
        failure_reason=reason,
    )
    return PlanState(completed=current.completed, pending=(failed_step,) + current.pending[1:])


def approve_proposal(current: PlanVersion, proposal: Proposal) -> PlanVersion:
    if proposal.base_version_id != current.id:
        raise PlanInvariantError("proposal is based on a stale plan version")
    if proposal.version.plan.completed_fingerprint() != current.plan.completed_fingerprint():
        raise PlanInvariantError("proposal attempts to mutate completed history")
    return replace(proposal.version, parent_id=current.id)

