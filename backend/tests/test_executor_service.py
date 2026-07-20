import unittest

from executor_service import executor_pb2
from executor_service.driver import MockEnvironmentDriver
from executor_service.service import ExecutorService


class ExecutorServiceTests(unittest.TestCase):
    def test_execute_uses_shared_primitives_and_emits_summary(self) -> None:
        driver = MockEnvironmentDriver(screenshot_bytes=b"png")
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


if __name__ == "__main__":
    unittest.main()
