from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
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
        if not self.screenshot_bytes:
            from PIL import Image, ImageDraw

            image = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), color=(248, 244, 236))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle(
                (28, 28, SCREEN_WIDTH - 28, SCREEN_HEIGHT - 28),
                radius=28,
                fill=(255, 252, 247),
                outline=(53, 86, 74),
                width=3,
            )
            draw.text((72, 76), "Plover Executor Live View", fill=(53, 86, 74))
            output = BytesIO()
            image.save(output, format="PNG")
            self.screenshot_bytes = output.getvalue()
        return self.screenshot_bytes
