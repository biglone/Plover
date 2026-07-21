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
class StepAction:
    """A deterministic executor primitive attached to a plan step."""

    kind: str
    x: int | None = None
    y: int | None = None
    end_x: int | None = None
    end_y: int | None = None
    text: str | None = None
    keys: tuple[str, ...] = ()
    delta: int | None = None
    milliseconds: int | None = None

    def __post_init__(self) -> None:
        kind = self.kind.strip().lower()
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "keys", tuple(key.strip() for key in self.keys if key.strip()))

        if kind in {"click", "double_click", "move"}:
            if self.x is None or self.y is None:
                raise ValueError(f"{kind} action requires x and y coordinates")
        elif kind == "drag":
            if None in {self.x, self.y, self.end_x, self.end_y}:
                raise ValueError("drag action requires start and end coordinates")
        elif kind == "type":
            if not self.text:
                raise ValueError("type action requires text")
        elif kind == "keys":
            if not self.keys:
                raise ValueError("keys action requires at least one key")
        elif kind == "scroll":
            if self.delta is None:
                raise ValueError("scroll action requires delta")
        elif kind == "wait":
            if self.milliseconds is None or self.milliseconds < 0:
                raise ValueError("wait action requires non-negative milliseconds")
        elif kind != "observe":
            raise ValueError(f"unsupported step action: {kind}")

    def fingerprint(self) -> tuple[Any, ...]:
        return (
            self.kind,
            self.x,
            self.y,
            self.end_x,
            self.end_y,
            self.text,
            self.keys,
            self.delta,
            self.milliseconds,
        )

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        for field_name in ("x", "y", "end_x", "end_y", "text", "delta", "milliseconds"):
            value = getattr(self, field_name)
            if value is not None:
                payload[field_name] = value
        if self.keys:
            payload["keys"] = list(self.keys)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StepAction":
        kind = data.get("kind")
        if not isinstance(kind, str):
            raise ValueError("step action kind must be a string")
        keys = data.get("keys", [])
        if isinstance(keys, tuple):
            keys = list(keys)
        if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
            raise ValueError("step action keys must be a list")

        def optional_int(name: str) -> int | None:
            value = data.get(name)
            if value is None:
                return None
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"step action {name} must be an integer")
            return value

        text = data.get("text")
        if text is not None and not isinstance(text, str):
            raise ValueError("step action text must be a string")
        return cls(
            kind=kind,
            x=optional_int("x"),
            y=optional_int("y"),
            end_x=optional_int("end_x"),
            end_y=optional_int("end_y"),
            text=text,
            keys=tuple(keys),
            delta=optional_int("delta"),
            milliseconds=optional_int("milliseconds"),
        )


@dataclass(frozen=True)
class PlanStep:
    id: str
    instruction: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    ui_summary: str | None = None
    failure_reason: str | None = None
    actions: tuple[StepAction, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "instruction": self.instruction,
            "status": self.status.value,
            "ui_summary": self.ui_summary,
            "failure_reason": self.failure_reason,
            "actions": [action.as_dict() for action in self.actions],
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

    def completed_fingerprint(self) -> tuple[tuple[Any, ...], ...]:
        return tuple(
            (
                step.id,
                step.instruction,
                step.status.value,
                step.ui_summary,
                step.failure_reason,
                tuple(action.fingerprint() for action in step.actions),
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
