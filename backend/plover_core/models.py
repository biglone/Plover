from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class ReplanCause(str, Enum):
    INITIAL = "initial"
    USER_GUIDANCE = "user_guidance"
    ANNOTATION = "annotation"
    SYSTEM_DRIVEN_IR = "system_driven_ir"
    MANUAL_EDIT = "manual_edit"


@dataclass(frozen=True)
class PlanStep:
    id: str
    instruction: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    ui_summary: str | None = None
    failure_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "instruction": self.instruction,
            "status": self.status.value,
            "ui_summary": self.ui_summary,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class PlanState:
    completed: tuple[PlanStep, ...] = ()
    pending: tuple[PlanStep, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "completed": [step.as_dict() for step in self.completed],
            "pending": [step.as_dict() for step in self.pending],
        }

    def completed_fingerprint(self) -> tuple[tuple[str, str, str, str | None, str | None], ...]:
        return tuple(
            (
                step.id,
                step.instruction,
                step.status.value,
                step.ui_summary,
                step.failure_reason,
            )
            for step in self.completed
        )


@dataclass(frozen=True)
class Annotation:
    screenshot: str
    x: int
    y: int
    width: int
    height: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "screenshot": self.screenshot,
            "bbox": {
                "x": self.x,
                "y": self.y,
                "width": self.width,
                "height": self.height,
            },
        }


@dataclass(frozen=True)
class PlanVersion:
    id: str
    plan: PlanState
    parent_id: str | None
    cause: ReplanCause
    created_at: str
    derived_constraints: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "cause": self.cause.value,
            "created_at": self.created_at,
            "derived_constraints": list(self.derived_constraints),
            "plan": self.plan.as_dict(),
        }


@dataclass(frozen=True)
class Proposal:
    id: str
    base_version_id: str
    version: PlanVersion
    summary: str
    rationale: str
    status: str = "pending"
    annotation: Annotation | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "base_version_id": self.base_version_id,
            "summary": self.summary,
            "rationale": self.rationale,
            "status": self.status,
            "annotation": self.annotation.as_dict() if self.annotation else None,
            "version": self.version.as_dict(),
        }

