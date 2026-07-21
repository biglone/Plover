import unittest
from io import BytesIO

from executor_service import executor_pb2
from executor_service.driver import MockEnvironmentDriver
from executor_service.service import ExecutorService
from PIL import Image


def _png(width: int, height: int) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), color=(17, 34, 51)).save(output, format="PNG")
    return output.getvalue()


class ExecutorServiceTests(unittest.TestCase):
    def test_execute_uses_shared_primitives_and_emits_summary(self) -> None:
        driver = MockEnvironmentDriver(screenshot_bytes=_png(320, 200))
        service = ExecutorService(driver)
        request = executor_pb2.ExecuteRequest(
            run_id="run-1",
            step_id="step-1",
            actions=[
                executor_pb2.Action(
                    pointer=executor_pb2.PointerAction(
                        kind=executor_pb2.PointerAction.CLICK,
                        x=10,
                        y=20,
                    )
                ),
                executor_pb2.Action(
                    keyboard=executor_pb2.KeyboardAction(text="hello")
                ),
            ],
        )

        response = service.Execute(request, None)

        self.assertTrue(response.ok)
        self.assertIn("Clicking", response.summary)
        with Image.open(BytesIO(response.screenshot_png)) as screenshot:
            self.assertEqual(screenshot.size, (1024, 768))
        self.assertEqual(
            driver.actions,
            [("click", (10, 20)), ("screenshot", ()), ("type_text", ("hello",)), ("screenshot", ())],
        )
        events = list(
            service.WatchEvents(
                executor_pb2.WatchEventsRequest(run_id="run-1"),
                None,
            )
        )
        self.assertEqual([event.kind for event in events], [
            "action_started",
            "action_completed",
            "action_started",
            "action_completed",
        ])

    def test_observe_normalizes_screenshot_dimensions(self) -> None:
        service = ExecutorService(MockEnvironmentDriver(screenshot_bytes=_png(200, 320)))

        response = service.Observe(executor_pb2.ObserveRequest(run_id="run-1"), None)

        self.assertEqual((response.width, response.height), (1024, 768))
        with Image.open(BytesIO(response.screenshot_png)) as screenshot:
            self.assertEqual(screenshot.size, (1024, 768))


if __name__ == "__main__":
    unittest.main()
