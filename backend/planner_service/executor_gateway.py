from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from typing import Protocol

import grpc
from PIL import Image, ImageDraw

from executor_service import executor_pb2
from executor_service import executor_pb2_grpc
from executor_service.driver import MockEnvironmentDriver, SCREEN_HEIGHT, SCREEN_WIDTH
from executor_service.service import ExecutorService
from plover_core.models import PlanStep, StepAction
from planner_service.observation_source import (
    LiveObservation,
    ObservationSource,
    ObservationSourceError,
    create_observation_source_from_env,
)


@dataclass(frozen=True)
class ExecutorResult:
    ok: bool
    summary: str
    screenshot_png: bytes
    failure_type: str | None = None
    events: tuple["ExecutorEvent", ...] = ()
    width: int = SCREEN_WIDTH
    height: int = SCREEN_HEIGHT


@dataclass(frozen=True)
class ExecutorEvent:
    kind: str
    ui_summary: str
    detail: str
    created_at: str
    step_id: str


class ExecutorGateway(Protocol):
    def execute_step(self, run_id: str, step: PlanStep) -> ExecutorResult: ...

    def observe(self, run_id: str) -> LiveObservation: ...


def _placeholder_png(lines: list[str]) -> bytes:
    image = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), color=(248, 244, 236))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 28, 996, 740), radius=28, fill=(255, 252, 247), outline=(53, 86, 74), width=3)
    draw.rounded_rectangle((64, 64, 960, 128), radius=20, fill=(223, 234, 225))
    draw.text((88, 86), "Plover Live View", fill=(53, 86, 74))
    y = 172
    for line in lines[:8]:
        draw.rounded_rectangle((84, y, 940, y + 54), radius=18, fill=(247, 233, 220))
        draw.text((108, y + 18), line, fill=(31, 41, 55))
        y += 76
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class LocalExecutorGateway:
    """In-process executor gateway for a runnable local prototype."""

    def __init__(self, service: ExecutorService | None = None, *, scenario: str | None = None) -> None:
        self._drivers: dict[str, MockEnvironmentDriver] = {}
        self._services: dict[str, ExecutorService] = {}
        self._event_offsets: dict[str, int] = {}
        self._scenario = (scenario or "").strip().lower() or None
        self._failed_runs: set[str] = set()
        if service is not None:
            self._services["__shared__"] = service

    def _service_for(self, run_id: str) -> ExecutorService:
        if "__shared__" in self._services:
            return self._services["__shared__"]
        service = self._services.get(run_id)
        if service is None:
            driver = MockEnvironmentDriver(screenshot_bytes=_placeholder_png(["Waiting for execution..."]))
            service = ExecutorService(driver)
            self._drivers[run_id] = driver
            self._services[run_id] = service
        return service

    def _driver_for(self, run_id: str) -> MockEnvironmentDriver:
        self._service_for(run_id)
        return self._drivers[run_id]

    def _take_events(self, run_id: str) -> tuple[ExecutorEvent, ...]:
        events = list(
            self._service_for(run_id).WatchEvents(
                executor_pb2.WatchEventsRequest(run_id=run_id),
                None,
            )
        )
        offset = self._event_offsets.get(run_id, 0)
        self._event_offsets[run_id] = len(events)
        return tuple(
            ExecutorEvent(
                kind=event.kind,
                ui_summary=event.ui_summary,
                detail=event.detail,
                created_at=event.created_at,
                step_id=event.step_id,
            )
            for event in events[offset:]
            if event.kind in {"action_started", "action_completed", "failure_detected"}
        )

    def execute_step(self, run_id: str, step: PlanStep) -> ExecutorResult:
        driver = self._driver_for(run_id)
        if self._scenario == "fail_once" and run_id not in self._failed_runs:
            self._failed_runs.add(run_id)
            driver.screenshot_bytes = _placeholder_png(
                [
                    f"Run: {run_id}",
                    f"Step: {step.id}",
                    "Executor mode: local mock",
                    "Injected failure: REPEAT_CLICK_MENU",
                ]
            )
            return ExecutorResult(
                ok=False,
                summary="Retry with a different tactic",
                screenshot_png=driver.screenshot_bytes,
                failure_type="REPEAT_CLICK_MENU",
                events=(
                    ExecutorEvent(
                        kind="failure_detected",
                        ui_summary="Retry with a different tactic",
                        detail="Injected fail_once scenario for browser recovery testing",
                        created_at="2026-07-21T00:00:00+00:00",
                        step_id=step.id,
                    ),
                ),
                width=SCREEN_WIDTH,
                height=SCREEN_HEIGHT,
            )
        driver.screenshot_bytes = _placeholder_png(
            [
                f"Run: {run_id}",
                f"Step: {step.id}",
                f"Instruction: {step.instruction[:72]}",
                "Executor mode: local mock",
            ]
        )
        response = self._service_for(run_id).Execute(
            executor_pb2.ExecuteRequest(
                run_id=run_id,
                step_id=step.id,
                actions=actions_for_step(step),
            ),
            None,
        )
        return ExecutorResult(
            ok=response.ok,
            summary=response.summary,
            screenshot_png=response.screenshot_png,
            failure_type=response.failure_type or None,
            events=self._take_events(run_id),
            width=SCREEN_WIDTH,
            height=SCREEN_HEIGHT,
        )

    def observe(self, run_id: str) -> LiveObservation:
        driver = self._driver_for(run_id)
        if not driver.screenshot_bytes:
            driver.screenshot_bytes = _placeholder_png(
                [
                    f"Run: {run_id}",
                    "Live observation ready",
                    "Draw a box to target a local repair.",
                ]
            )
        response = self._service_for(run_id).Observe(
            executor_pb2.ObserveRequest(run_id=run_id),
            None,
        )
        return LiveObservation(
            screenshot_png=response.screenshot_png,
            width=response.width,
            height=response.height,
        )


def _action_message(action: StepAction) -> executor_pb2.Action:
    if action.kind == "click":
        return executor_pb2.Action(
            pointer=executor_pb2.PointerAction(
                kind=executor_pb2.PointerAction.CLICK,
                x=action.x,
                y=action.y,
            )
        )
    if action.kind == "double_click":
        return executor_pb2.Action(
            pointer=executor_pb2.PointerAction(
                kind=executor_pb2.PointerAction.DOUBLE_CLICK,
                x=action.x,
                y=action.y,
            )
        )
    if action.kind == "move":
        return executor_pb2.Action(
            pointer=executor_pb2.PointerAction(
                kind=executor_pb2.PointerAction.MOVE,
                x=action.x,
                y=action.y,
            )
        )
    if action.kind == "drag":
        return executor_pb2.Action(
            pointer=executor_pb2.PointerAction(
                kind=executor_pb2.PointerAction.DRAG,
                x=action.x,
                y=action.y,
                end_x=action.end_x,
                end_y=action.end_y,
            )
        )
    if action.kind == "type":
        return executor_pb2.Action(keyboard=executor_pb2.KeyboardAction(text=action.text))
    if action.kind == "keys":
        return executor_pb2.Action(keyboard=executor_pb2.KeyboardAction(keys=action.keys))
    if action.kind == "scroll":
        return executor_pb2.Action(scroll=executor_pb2.ScrollAction(delta=action.delta))
    if action.kind == "wait":
        return executor_pb2.Action(wait=executor_pb2.WaitAction(milliseconds=action.milliseconds))
    return executor_pb2.Action(observe=executor_pb2.ObserveAction())


def actions_for_step(step: PlanStep) -> list[executor_pb2.Action]:
    """Compile the deterministic prototype step language into executor primitives."""
    if step.actions:
        return [_action_message(action) for action in step.actions]
    instruction = step.instruction.lower()
    if "capture" in instruction or "screen" in instruction or "verify" in instruction:
        return [executor_pb2.Action(observe=executor_pb2.ObserveAction())]
    if "type" in instruction or "enter" in instruction:
        return [executor_pb2.Action(keyboard=executor_pb2.KeyboardAction(text=step.instruction[:48]))]
    if "click" in instruction or "select" in instruction or "choose" in instruction:
        return [
            executor_pb2.Action(
                pointer=executor_pb2.PointerAction(
                    kind=executor_pb2.PointerAction.CLICK,
                    x=420,
                    y=280,
                )
            )
        ]
    return [
        executor_pb2.Action(wait=executor_pb2.WaitAction(milliseconds=250)),
        executor_pb2.Action(observe=executor_pb2.ObserveAction()),
    ]


class GrpcExecutorGateway:
    """Network gateway used when Planner and Executor run as separate services."""

    def __init__(self, target: str) -> None:
        self._channel = grpc.insecure_channel(target)
        self._stub = executor_pb2_grpc.ExecutorStub(self._channel)
        self._event_offsets: dict[str, int] = {}

    def _take_events(self, run_id: str) -> tuple[ExecutorEvent, ...]:
        events = list(self._stub.WatchEvents(executor_pb2.WatchEventsRequest(run_id=run_id)))
        offset = self._event_offsets.get(run_id, 0)
        self._event_offsets[run_id] = len(events)
        return tuple(
            ExecutorEvent(
                kind=event.kind,
                ui_summary=event.ui_summary,
                detail=event.detail,
                created_at=event.created_at,
                step_id=event.step_id,
            )
            for event in events[offset:]
            if event.kind in {"action_started", "action_completed", "failure_detected"}
        )

    def execute_step(self, run_id: str, step: PlanStep) -> ExecutorResult:
        response = self._stub.Execute(
            executor_pb2.ExecuteRequest(
                run_id=run_id,
                step_id=step.id,
                actions=actions_for_step(step),
            )
        )
        return ExecutorResult(
            ok=response.ok,
            summary=response.summary,
            screenshot_png=response.screenshot_png,
            failure_type=response.failure_type or None,
            events=self._take_events(run_id),
            width=SCREEN_WIDTH,
            height=SCREEN_HEIGHT,
        )

    def observe(self, run_id: str) -> LiveObservation:
        response = self._stub.Observe(executor_pb2.ObserveRequest(run_id=run_id))
        return LiveObservation(
            screenshot_png=response.screenshot_png,
            width=response.width,
            height=response.height,
        )

    def close(self) -> None:
        self._channel.close()


class ObservationBackedExecutorGateway:
    """Gateway wrapper that prefers an external observation feed for Live View."""

    def __init__(self, gateway: ExecutorGateway, source: ObservationSource | None = None) -> None:
        self._gateway = gateway
        self._source = source or create_observation_source_from_env()

    def _capture(self, run_id: str) -> LiveObservation | None:
        if self._source is None:
            return None
        try:
            return self._source.observe(run_id)
        except ObservationSourceError:
            return None

    def execute_step(self, run_id: str, step: PlanStep) -> ExecutorResult:
        result = self._gateway.execute_step(run_id, step)
        observation = self._capture(run_id)
        if observation is None:
            return result
        return ExecutorResult(
            ok=result.ok,
            summary=result.summary,
            screenshot_png=observation.screenshot_png,
            failure_type=result.failure_type,
            events=result.events,
            width=observation.width,
            height=observation.height,
        )

    def observe(self, run_id: str) -> LiveObservation:
        observation = self._capture(run_id)
        if observation is not None:
            return observation
        return self._gateway.observe(run_id)

    def close(self) -> None:
        closer = getattr(self._gateway, "close", None)
        if callable(closer):
            closer()


def create_executor_gateway_from_env() -> ExecutorGateway:
    executor_target = os.getenv("PLOVER_EXECUTOR_TARGET")
    local_scenario = os.getenv("PLOVER_LOCAL_EXECUTOR_SCENARIO")
    gateway: ExecutorGateway = (
        GrpcExecutorGateway(executor_target) if executor_target else LocalExecutorGateway(scenario=local_scenario)
    )
    source = create_observation_source_from_env()
    if source is None:
        return gateway
    return ObservationBackedExecutorGateway(gateway, source)
