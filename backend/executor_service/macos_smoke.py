from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import platform
import subprocess
from typing import Callable

from PIL import Image

from executor_service import executor_pb2
from executor_service.driver import EnvironmentDriver, SCREEN_HEIGHT, SCREEN_WIDTH
from executor_service.drivers import create_driver
from executor_service.service import ExecutorService


class MacOSSmokeError(RuntimeError):
    """Raised when a macOS-only smoke check is run on another platform."""


@dataclass(frozen=True)
class MacOSSmokeResult:
    accessibility_enabled: bool
    display_width: int
    display_height: int
    screenshot_width: int
    screenshot_height: int


def _accessibility_enabled() -> bool:
    completed = subprocess.run(
        ["/usr/bin/osascript", "-e", 'tell application "System Events" to return UI elements enabled'],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0 and completed.stdout.strip().lower() == "true"


def _display_size() -> tuple[int, int]:
    import pyautogui

    size = pyautogui.size()
    return size.width, size.height


def run_macos_smoke(
    *,
    system_name: str | None = None,
    driver_factory: Callable[[str], EnvironmentDriver] = create_driver,
    accessibility_checker: Callable[[], bool] = _accessibility_enabled,
    display_size: Callable[[], tuple[int, int]] = _display_size,
) -> MacOSSmokeResult:
    """Capture one frame through the real driver without sending desktop input."""
    if (system_name or platform.system()) != "Darwin":
        raise MacOSSmokeError("macOS smoke tests must run on a Darwin host")

    driver = driver_factory("macos")
    try:
        response = ExecutorService(driver).Observe(
            executor_pb2.ObserveRequest(run_id="macos-smoke"),
            None,
        )
    except Exception as error:
        raise RuntimeError(
            "macOS screenshot capture failed; grant Screen Recording to the terminal or Executor process"
        ) from error
    if not response.ok or not response.screenshot_png:
        raise RuntimeError("Executor could not capture a macOS screenshot")
    if (response.width, response.height) != (SCREEN_WIDTH, SCREEN_HEIGHT):
        raise RuntimeError("Executor did not report the normalized live-view dimensions")

    with Image.open(BytesIO(response.screenshot_png)) as image:
        screenshot_width, screenshot_height = image.size
    if (screenshot_width, screenshot_height) != (SCREEN_WIDTH, SCREEN_HEIGHT):
        raise RuntimeError("Executor did not return a normalized PNG screenshot")

    display_width, display_height = display_size()
    if display_width <= 0 or display_height <= 0:
        raise RuntimeError("macOS did not report a usable display size")

    return MacOSSmokeResult(
        accessibility_enabled=accessibility_checker(),
        display_width=display_width,
        display_height=display_height,
        screenshot_width=screenshot_width,
        screenshot_height=screenshot_height,
    )


def main() -> int:
    try:
        result = run_macos_smoke()
    except (MacOSSmokeError, RuntimeError, OSError) as error:
        print(f"[fail] macOS smoke check failed: {error}")
        return 1

    print("[ok] macOS driver initialized without desktop input")
    print(f"[ok] display size: {result.display_width} x {result.display_height}")
    print(f"[ok] Screen Recording screenshot: {result.screenshot_width} x {result.screenshot_height}")
    if not result.accessibility_enabled:
        print("[fail] Accessibility is unavailable for System Events")
        return 1
    print("[ok] Accessibility is available for System Events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
