from __future__ import annotations

import subprocess
from io import BytesIO

from executor_service.driver import EnvironmentDriver


class XdotoolDriver(EnvironmentDriver):
    """Ubuntu driver backed by xdotool and ImageMagick's import utility."""

    def __init__(self, screenshot_command: tuple[str, ...] = ("import", "-window", "root", "png:-")):
        self._screenshot_command = screenshot_command

    def _run(self, *args: str) -> None:
        subprocess.run(["xdotool", *args], check=True)

    def click(self, x: int, y: int, *, double: bool = False) -> None:
        self._run("mousemove", str(x), str(y))
        self._run("click", "2" if double else "1")

    def move(self, x: int, y: int) -> None:
        self._run("mousemove", str(x), str(y))

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        self._run("mousemove", str(start_x), str(start_y))
        self._run("mousedown", "1")
        self._run("mousemove", "--sync", str(end_x), str(end_y))
        self._run("mouseup", "1")

    def type_text(self, text: str) -> None:
        self._run("type", "--delay", "1", text)

    def press_keys(self, keys: list[str]) -> None:
        self._run("key", "+".join(keys))

    def scroll(self, delta: int) -> None:
        button = "4" if delta > 0 else "5"
        for _ in range(max(abs(delta), 1)):
            self._run("click", button)

    def wait(self, milliseconds: int) -> None:
        import time

        time.sleep(milliseconds / 1000)

    def screenshot(self) -> bytes:
        return subprocess.run(
            list(self._screenshot_command),
            check=True,
            capture_output=True,
        ).stdout


class PyAutoGuiDriver(EnvironmentDriver):
    """Windows driver backed by pyautogui, imported only when selected."""

    def __init__(self) -> None:
        try:
            import pyautogui
        except ImportError as error:  # pragma: no cover - platform dependency
            raise RuntimeError("Install pyautogui to use the Windows driver") from error
        self._pyautogui = pyautogui

    def click(self, x: int, y: int, *, double: bool = False) -> None:
        self._pyautogui.click(x, y, clicks=2 if double else 1)

    def move(self, x: int, y: int) -> None:
        self._pyautogui.moveTo(x, y)

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        self._pyautogui.moveTo(start_x, start_y)
        self._pyautogui.dragTo(end_x, end_y, duration=0.2, button="left")

    def type_text(self, text: str) -> None:
        self._pyautogui.write(text)

    def press_keys(self, keys: list[str]) -> None:
        self._pyautogui.hotkey(*keys)

    def scroll(self, delta: int) -> None:
        self._pyautogui.scroll(delta)

    def wait(self, milliseconds: int) -> None:
        self._pyautogui.sleep(milliseconds / 1000)

    def screenshot(self) -> bytes:
        output = BytesIO()
        self._pyautogui.screenshot().save(output, format="PNG")
        return output.getvalue()
