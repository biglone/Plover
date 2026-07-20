from __future__ import annotations

from datetime import datetime, timezone
from hashlib import blake2b
from typing import Iterable

from grpc import ServicerContext

from executor_service import executor_pb2, executor_pb2_grpc
from executor_service.driver import EnvironmentDriver, SCREEN_HEIGHT, SCREEN_WIDTH
from plover_core.detection import Action, NonProgressDetector


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _action_summary(action: executor_pb2.Action) -> str:
    operation = action.WhichOneof("operation")
    if operation == "pointer":
        pointer = action.pointer
        verb = {
            executor_pb2.PointerAction.CLICK: "Clicking",
            executor_pb2.PointerAction.DOUBLE_CLICK: "Double-clicking",
            executor_pb2.PointerAction.MOVE: "Moving",
            executor_pb2.PointerAction.DRAG: "Dragging",
        }[pointer.kind]
        return f"{verb} at ({pointer.x}, {pointer.y})"
    if operation == "keyboard":
        keyboard = action.keyboard
        if keyboard.text:
            return f"Typing {keyboard.text}"
        return f"Pressing {'+'.join(keyboard.keys)}"
    if operation == "scroll":
        return f"Scrolling {action.scroll.delta}"
    if operation == "wait":
        return f"Waiting {action.wait.milliseconds} ms"
    return "Capturing the current screen"


def _canonical_action(action: executor_pb2.Action) -> Action:
    operation = action.WhichOneof("operation")
    if operation == "pointer":
        pointer = action.pointer
        kind = executor_pb2.PointerAction.Kind.Name(pointer.kind).lower()
        return Action(kind, f"{pointer.x},{pointer.y}")
    if operation == "keyboard":
        keyboard = action.keyboard
        return Action("type" if keyboard.text else "keys", value=keyboard.text or "+".join(keyboard.keys))
    if operation == "scroll":
        return Action("scroll", value=str(action.scroll.delta))
    if operation == "wait":
        return Action("wait", value=str(action.wait.milliseconds))
    return Action("observe")


def _screenshot_hash(screenshot: bytes) -> int:
    digest = blake2b(screenshot, digest_size=8).digest() if screenshot else b"\x00" * 8
    return int.from_bytes(digest, "big")


class ExecutorService(executor_pb2_grpc.ExecutorServicer):
    def __init__(self, driver: EnvironmentDriver) -> None:
        self._driver = driver
        self._detectors: dict[str, NonProgressDetector] = {}
        self._events: dict[str, list[executor_pb2.ExecutionEvent]] = {}

    def _record_event(self, run_id: str, step_id: str, kind: str, summary: str, detail: str = "") -> None:
        self._events.setdefault(run_id, []).append(
            executor_pb2.ExecutionEvent(
                run_id=run_id,
                step_id=step_id,
                kind=kind,
                ui_summary=summary,
                detail=detail,
                created_at=_now(),
            )
        )

    def Execute(
        self,
        request: executor_pb2.ExecuteRequest,
        context: ServicerContext,
    ) -> executor_pb2.ExecuteResponse:
        detector = self._detectors.setdefault(request.run_id, NonProgressDetector())
        screenshot = b""
        for action in request.actions:
            summary = _action_summary(action)
            self._record_event(request.run_id, request.step_id, "action_started", summary)
            operation = action.WhichOneof("operation")
            if operation == "pointer":
                pointer = action.pointer
                if pointer.kind == executor_pb2.PointerAction.CLICK:
                    self._driver.click(pointer.x, pointer.y)
                elif pointer.kind == executor_pb2.PointerAction.DOUBLE_CLICK:
                    self._driver.click(pointer.x, pointer.y, double=True)
                elif pointer.kind == executor_pb2.PointerAction.MOVE:
                    self._driver.move(pointer.x, pointer.y)
                else:
                    self._driver.drag(pointer.x, pointer.y, pointer.end_x, pointer.end_y)
            elif operation == "keyboard":
                if action.keyboard.text:
                    self._driver.type_text(action.keyboard.text)
                else:
                    self._driver.press_keys(list(action.keyboard.keys))
            elif operation == "scroll":
                self._driver.scroll(action.scroll.delta)
            elif operation == "wait":
                self._driver.wait(action.wait.milliseconds)
            else:
                screenshot = self._driver.screenshot()

            screenshot = self._driver.screenshot()
            self._record_event(request.run_id, request.step_id, "action_completed", summary)
            detection = detector.observe(_canonical_action(action), screenshot_hash=_screenshot_hash(screenshot))
            if detection:
                detail = f"Stuck after {detection.repeated_action}; screenshot distances={detection.screenshot_distances}"
                self._record_event(request.run_id, request.step_id, "failure_detected", summary, detail)
                return executor_pb2.ExecuteResponse(
                    ok=False,
                    summary=summary,
                    failure_type=detection.failure_type,
                    screenshot_png=screenshot,
                )

        return executor_pb2.ExecuteResponse(ok=True, summary="; ".join(_action_summary(action) for action in request.actions), screenshot_png=screenshot)

    def Observe(
        self,
        request: executor_pb2.ObserveRequest,
        context: ServicerContext,
    ) -> executor_pb2.ObserveResponse:
        screenshot = self._driver.screenshot()
        self._record_event(request.run_id, "", "observation", "Capturing the current screen")
        return executor_pb2.ObserveResponse(
            ok=True,
            screenshot_png=screenshot,
            width=SCREEN_WIDTH,
            height=SCREEN_HEIGHT,
        )

    def WatchEvents(
        self,
        request: executor_pb2.WatchEventsRequest,
        context: ServicerContext,
    ) -> Iterable[executor_pb2.ExecutionEvent]:
        yield from self._events.get(request.run_id, ())
