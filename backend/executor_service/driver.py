from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


SCREEN_WIDTH = 1024
SCREEN_HEIGHT = 768


class EnvironmentDriver(Protocol):
    def click(self, x: int, y: int, *, double: bool = False) -> None: ...

    def move(self, x: int, y: int) -> None: ...

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None: ...

    def type_text(self, text: str) -> None: ...

    def press_keys(self, keys: list[str]) -> None: ...

    def scroll(self, delta: int) -> None: ...

    def wait(self, milliseconds: int) -> None: ...

    def screenshot(self) -> bytes: ...


@dataclass
class MockEnvironmentDriver:
    """Deterministic driver for local development and service tests."""

    screenshot_bytes: bytes = b""

    def __post_init__(self) -> None:
        self.actions: list[tuple[str, tuple[object, ...]]] = []

    def click(self, x: int, y: int, *, double: bool = False) -> None:
        self.actions.append(("double_click" if double else "click", (x, y)))

    def move(self, x: int, y: int) -> None:
        self.actions.append(("move", (x, y)))

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        self.actions.append(("drag", (start_x, start_y, end_x, end_y)))

    def type_text(self, text: str) -> None:
        self.actions.append(("type_text", (text,)))

    def press_keys(self, keys: list[str]) -> None:
        self.actions.append(("press_keys", tuple(keys)))

    def scroll(self, delta: int) -> None:
        self.actions.append(("scroll", (delta,)))

    def wait(self, milliseconds: int) -> None:
        self.actions.append(("wait", (milliseconds,)))

    def screenshot(self) -> bytes:
        self.actions.append(("screenshot", ()))
        return self.screenshot_bytes

