from __future__ import annotations

from io import BytesIO
import unittest

from PIL import Image

from executor_service.driver import MockEnvironmentDriver
from executor_service.macos_smoke import MacOSSmokeError, run_macos_motion_smoke, run_macos_smoke


def _png(size: tuple[int, int]) -> bytes:
    image = Image.new("RGB", size, color=(248, 244, 236))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class MacOSSmokeTests(unittest.TestCase):
    def test_rejects_non_macos_hosts(self) -> None:
        with self.assertRaisesRegex(MacOSSmokeError, "Darwin"):
            run_macos_smoke(system_name="Linux")

    def test_captures_a_normalized_frame_without_desktop_input(self) -> None:
        driver = MockEnvironmentDriver(screenshot_bytes=_png((1440, 900)))

        result = run_macos_smoke(
            system_name="Darwin",
            driver_factory=lambda platform_name: driver,
            accessibility_checker=lambda: True,
            display_size=lambda: (3024, 1964),
        )

        self.assertTrue(result.accessibility_enabled)
        self.assertEqual((result.display_width, result.display_height), (3024, 1964))
        self.assertEqual((result.screenshot_width, result.screenshot_height), (1024, 768))
        self.assertEqual(driver.actions, [("screenshot", ())])

    def test_reports_missing_accessibility_without_touching_the_desktop(self) -> None:
        driver = MockEnvironmentDriver(screenshot_bytes=_png((1024, 768)))

        result = run_macos_smoke(
            system_name="Darwin",
            driver_factory=lambda platform_name: driver,
            accessibility_checker=lambda: False,
            display_size=lambda: (1512, 982),
        )

        self.assertFalse(result.accessibility_enabled)
        self.assertEqual(driver.actions, [("screenshot", ())])

    def test_explains_screen_recording_failures(self) -> None:
        class BrokenScreenshotDriver(MockEnvironmentDriver):
            def screenshot(self) -> bytes:
                raise OSError("display capture denied")

        with self.assertRaisesRegex(RuntimeError, "Screen Recording"):
            run_macos_smoke(
                system_name="Darwin",
                driver_factory=lambda platform_name: BrokenScreenshotDriver(),
                accessibility_checker=lambda: True,
                display_size=lambda: (1512, 982),
            )

    def test_moves_only_to_the_current_cursor_coordinate(self) -> None:
        driver = MockEnvironmentDriver()

        result = run_macos_motion_smoke(
            system_name="Darwin",
            driver_factory=lambda platform_name: driver,
            accessibility_checker=lambda: True,
            cursor_position=lambda: (713, 422),
        )

        self.assertEqual((result.cursor_x, result.cursor_y), (713, 422))
        self.assertEqual(driver.actions, [("move", (713, 422))])

    def test_motion_requires_accessibility(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Accessibility"):
            run_macos_motion_smoke(
                system_name="Darwin",
                driver_factory=lambda platform_name: MockEnvironmentDriver(),
                accessibility_checker=lambda: False,
                cursor_position=lambda: (713, 422),
            )
