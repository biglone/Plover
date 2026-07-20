from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from PIL import Image, ImageDraw

from executor_service import executor_pb2
from executor_service.driver import MockEnvironmentDriver, SCREEN_HEIGHT, SCREEN_WIDTH
from executor_service.service import ExecutorService
from plover_core.models import PlanStep


@dataclass(frozen=True)
class ExecutorResult:
    ok: bool
    summary: str
    screenshot_png: bytes
    failure_type: str | None = None


@dataclass(frozen=True)
class LiveObservation:
    screenshot_png: bytes
    width: int
    height: int


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

    def __init__(self, service: ExecutorService | None = None) -> None:
        self._drivers: dict[str, MockEnvironmentDriver] = {}
        self._services: dict[str, ExecutorService] = {}
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

    def _actions_for(self, step: PlanStep) -> list[executor_pb2.Action]:
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

    def execute_step(self, run_id: str, step: PlanStep) -> ExecutorResult:
        driver = self._driver_for(run_id)
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
                actions=self._actions_for(step),
            ),
            None,
        )
        return ExecutorResult(
            ok=response.ok,
            summary=response.summary,
            screenshot_png=response.screenshot_png,
            failure_type=response.failure_type or None,
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
