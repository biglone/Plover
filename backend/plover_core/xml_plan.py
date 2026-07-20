from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from uuid import uuid4
from xml.etree import ElementTree

from .models import ExecutionStatus, PlanState, PlanStep, PlanVersion


class PlanParseError(ValueError):
    """Raised when a model response does not satisfy the Plover plan schema."""


@dataclass(frozen=True)
class ParsedPlan:
    analysis: str
    state: PlanState


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _node_text(node: ElementTree.Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _parse_step_node(node: ElementTree.Element) -> PlanStep | None:
    instruction_node = node.find("instruction")
    instruction = _node_text(instruction_node) if instruction_node is not None else _node_text(node)
    if not instruction:
        return None
    ui_summary_node = node.find("ui_summary")
    ui_summary = _node_text(ui_summary_node) if ui_summary_node is not None else None
    return PlanStep(
        id=node.attrib.get("id", f"step-{uuid4().hex[:8]}"),
        instruction=unescape(instruction),
        status=ExecutionStatus.PENDING,
        ui_summary=ui_summary,
    )


def _parse_steps(container: ElementTree.Element, status: ExecutionStatus) -> tuple[PlanStep, ...]:
    nodes = [
        node
        for node in list(container)
        if node.tag in {"step", "action", "item"}
    ]
    if nodes:
        parsed = [_parse_step_node(node) for node in nodes]
        steps = [step for step in parsed if step is not None]
    else:
        steps = [
            PlanStep(
                id=f"step-{uuid4().hex[:8]}",
                instruction=line.lstrip("-*0123456789. ").strip(),
                status=ExecutionStatus.PENDING,
            )
            for line in _node_text(container).splitlines()
            if line.strip()
        ]
    return tuple(
        PlanStep(
            id=step.id,
            instruction=step.instruction,
            status=status,
            ui_summary=step.ui_summary,
            failure_reason=step.failure_reason,
        )
        for step in steps
    )


def parse_plan_response(response: str, *, current: PlanVersion | None = None) -> ParsedPlan:
    cleaned = _strip_code_fence(response)
    try:
        root = ElementTree.fromstring(f"<response>{cleaned}</response>")
    except ElementTree.ParseError as error:
        raise PlanParseError(f"invalid XML plan response: {error}") from error

    analysis_node = root.find("analysis")
    steps_node = root.find("steps")
    if analysis_node is None or steps_node is None:
        raise PlanParseError("response must contain <analysis> and <steps> blocks")
    completed_node = steps_node.find("completed")
    pending_node = steps_node.find("pending")
    if completed_node is None or pending_node is None:
        raise PlanParseError("<steps> must contain <completed> and <pending> blocks")

    parsed_completed = _parse_steps(completed_node, ExecutionStatus.COMPLETED)
    parsed_pending = _parse_steps(pending_node, ExecutionStatus.PENDING)
    if not parsed_pending:
        raise PlanParseError("plan must contain at least one pending step")

    if current is not None:
        expected = tuple(step.instruction for step in current.plan.completed)
        received = tuple(step.instruction for step in parsed_completed)
        if expected != received:
            raise PlanParseError("model response attempted to change completed plan history")
        completed = current.plan.completed
    else:
        completed = parsed_completed

    return ParsedPlan(
        analysis=_node_text(analysis_node),
        state=PlanState(completed=completed, pending=parsed_pending),
    )
