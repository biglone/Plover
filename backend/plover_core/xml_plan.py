from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from uuid import uuid4
from xml.etree import ElementTree

from .models import ExecutionStatus, PlanState, PlanStep, PlanVersion, StepAction


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


def _integer_attribute(node: ElementTree.Element, name: str) -> int:
    value = node.attrib.get(name)
    if value is None:
        raise ValueError(f"<{node.tag}> requires {name}")
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"<{node.tag}> {name} must be an integer") from error


def _parse_actions(node: ElementTree.Element) -> tuple[StepAction, ...]:
    container = node.find("actions")
    if container is None:
        return ()
    if not list(container):
        raise PlanParseError("<actions> must contain at least one executor primitive")

    actions: list[StepAction] = []
    for action_node in container:
        kind = action_node.tag.strip().lower()
        try:
            if kind in {"click", "double_click", "move"}:
                action = StepAction(
                    kind,
                    x=_integer_attribute(action_node, "x"),
                    y=_integer_attribute(action_node, "y"),
                )
            elif kind == "drag":
                action = StepAction(
                    kind,
                    x=_integer_attribute(action_node, "x"),
                    y=_integer_attribute(action_node, "y"),
                    end_x=_integer_attribute(action_node, "end_x"),
                    end_y=_integer_attribute(action_node, "end_y"),
                )
            elif kind == "type":
                action = StepAction(
                    kind,
                    text=action_node.attrib.get("text", _node_text(action_node)),
                )
            elif kind == "keys":
                keys = action_node.attrib.get("keys", _node_text(action_node))
                action = StepAction(kind, keys=tuple(key.strip() for key in keys.split(",")))
            elif kind == "scroll":
                action = StepAction(kind, delta=_integer_attribute(action_node, "delta"))
            elif kind == "wait":
                action = StepAction(
                    kind,
                    milliseconds=_integer_attribute(action_node, "milliseconds"),
                )
            elif kind == "observe":
                action = StepAction(kind)
            else:
                raise ValueError(f"unsupported <actions> primitive: <{kind}>")
        except ValueError as error:
            raise PlanParseError(str(error)) from error
        actions.append(action)
    return tuple(actions)


def _parse_step_node(node: ElementTree.Element) -> PlanStep | None:
    instruction_node = node.find("instruction")
    instruction = _node_text(instruction_node) if instruction_node is not None else _node_text(node)
    if not instruction:
        return None
    ui_summary_node = node.find("ui_summary")
    ui_summary = _node_text(ui_summary_node) if ui_summary_node is not None else None
    actions = _parse_actions(node)
    return PlanStep(
        id=node.attrib.get("id", f"step-{uuid4().hex[:8]}"),
        instruction=unescape(instruction),
        status=ExecutionStatus.PENDING,
        ui_summary=ui_summary,
        actions=actions,
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
            actions=step.actions,
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
        expected = current.plan.completed
        if len(expected) != len(parsed_completed):
            raise PlanParseError("model response attempted to change completed plan history")
        for expected_step, received_step in zip(expected, parsed_completed):
            if expected_step.id != received_step.id or expected_step.instruction != received_step.instruction:
                raise PlanParseError("model response attempted to change completed plan history")
            if received_step.actions and received_step.actions != expected_step.actions:
                raise PlanParseError("model response attempted to change completed plan history")
        completed = current.plan.completed
    else:
        completed = parsed_completed

    return ParsedPlan(
        analysis=_node_text(analysis_node),
        state=PlanState(completed=completed, pending=parsed_pending),
    )
