import unittest
from unittest.mock import patch

from plover_core.models import ExecutionStatus, PlanState, PlanStep, PlanVersion, ReplanCause
from planner_service.model_planner import ModelPlanner, OpenAICompatibleChatModel, create_planner


class FakeChatModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def complete(self, *, system: str, user: str, image_urls: tuple[str, ...] = ()) -> str:
        self.calls.append({"system": system, "user": user, "image_urls": image_urls})
        return self.response


class FakeHttpResponse:
    def __init__(self, body: bytes | None = None, *, lines: tuple[bytes, ...] = ()) -> None:
        self._body = body or b""
        self._lines = lines

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def __iter__(self):
        return iter(self._lines)

    def read(self) -> bytes:
        return self._body


class ModelPlannerTests(unittest.TestCase):
    def test_model_planner_creates_initial_plan_from_xml(self) -> None:
        model = FakeChatModel(
            """
            <analysis>Inspect then act.</analysis>
            <steps>
              <completed />
              <pending>
                <step>Capture the current screen</step>
                <step>Verify the visible outcome</step>
              </pending>
            </steps>
            """
        )

        plan = ModelPlanner(model).create_initial("Open a report")

        self.assertEqual(len(plan.plan.pending), 2)
        self.assertIn("Plover Planner", model.calls[0]["system"])

    def test_model_replan_preserves_completed_steps_and_passes_context(self) -> None:
        current = PlanVersion(
            id="version-1",
            plan=PlanState(
                completed=(PlanStep("step-1", "Open the report", ExecutionStatus.COMPLETED),),
                pending=(PlanStep("step-2", "Select the wrong option"),),
            ),
            parent_id=None,
            cause=ReplanCause.INITIAL,
            created_at="now",
        )
        model = FakeChatModel(
            """
            <analysis>The marked region identifies the replacement option.</analysis>
            <steps>
              <completed><step id="step-1">Open the report</step></completed>
              <pending><step>Click the marked replacement option</step></pending>
            </steps>
            """
        )

        proposal = ModelPlanner(model).propose_repair(
            current,
            guidance="Use the marked option",
            annotation=None,
            failure_type=None,
            screenshots=(
                "data:image/png;base64,one",
                "data:image/png;base64,two",
                "data:image/png;base64,three",
            ),
        )

        self.assertEqual(proposal.version.plan.completed, current.plan.completed)
        self.assertEqual(proposal.version.cause, ReplanCause.USER_GUIDANCE)
        self.assertIn("<current_plan>", model.calls[0]["user"])
        self.assertIn("<recent_screenshots count=\"3\" />", model.calls[0]["user"])
        self.assertEqual(
            model.calls[0]["image_urls"],
            (
                "data:image/png;base64,one",
                "data:image/png;base64,two",
                "data:image/png;base64,three",
            ),
        )

    def test_openai_compatible_model_uses_custom_auth_and_extra_headers(self) -> None:
        captured: dict[str, object] = {}

        def opener(http_request, *, timeout=None):
            captured["timeout"] = timeout
            captured["headers"] = {key.lower(): value for key, value in http_request.header_items()}
            captured["payload"] = http_request.data.decode("utf-8")
            return FakeHttpResponse(
                b'{"choices":[{"message":{"content":"<analysis>ok</analysis><steps><completed /><pending><step>Act</step></pending></steps>"}}]}'
            )

        model = OpenAICompatibleChatModel(
            endpoint="https://example.test/v1/chat/completions",
            model="computer-use",
            api_key="secret-token",
            api_key_header="x-api-key",
            api_key_prefix="",
            extra_headers={"x-deployment": "staging"},
            opener=opener,
        )

        content = model.complete(system="sys", user="hello")

        headers = captured["headers"]
        self.assertEqual(content, "<analysis>ok</analysis><steps><completed /><pending><step>Act</step></pending></steps>")
        self.assertIsInstance(headers, dict)
        self.assertEqual(headers["x-api-key"], "secret-token")
        self.assertEqual(headers["x-deployment"], "staging")
        self.assertEqual(captured["timeout"], 90)

    def test_openai_compatible_model_concatenates_streamed_chunks(self) -> None:
        captured: dict[str, object] = {}
        stream_lines = (
            b'data: {"choices":[{"delta":{"content":"<analysis>Inspect.</analysis>"}}]}\n',
            b'data: {"choices":[{"delta":{"content":"<steps><completed /><pending><step>Act</step></pending></steps>"}}]}\n',
            b"data: [DONE]\n",
        )

        def opener(http_request, *, timeout=None):
            captured["payload"] = http_request.data.decode("utf-8")
            return FakeHttpResponse(lines=stream_lines)

        model = OpenAICompatibleChatModel(
            endpoint="https://example.test/v1/chat/completions",
            model="computer-use",
            stream=True,
            opener=opener,
        )

        content = model.complete(system="sys", user="hello")

        self.assertEqual(
            content,
            "<analysis>Inspect.</analysis><steps><completed /><pending><step>Act</step></pending></steps>",
        )
        self.assertIn('"stream": true', captured["payload"])

    def test_create_planner_reads_stream_and_header_configuration_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PLOVER_LLM_ENDPOINT": "https://example.test/v1/chat/completions",
                "PLOVER_LLM_MODEL": "computer-use",
                "PLOVER_LLM_API_KEY": "secret-token",
                "PLOVER_LLM_API_KEY_HEADER": "x-api-key",
                "PLOVER_LLM_API_KEY_PREFIX": "",
                "PLOVER_LLM_EXTRA_HEADERS": '{"x-deployment":"staging"}',
                "PLOVER_LLM_STREAM": "true",
            },
            clear=False,
        ):
            planner = create_planner()

        self.assertIsInstance(planner, ModelPlanner)
        self.assertIsInstance(planner._model, OpenAICompatibleChatModel)
        self.assertEqual(planner._model.api_key_header, "x-api-key")
        self.assertEqual(planner._model.api_key_prefix, "")
        self.assertEqual(planner._model.extra_headers, {"x-deployment": "staging"})
        self.assertTrue(planner._model.stream)

    def test_create_planner_rejects_non_object_extra_headers(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PLOVER_LLM_ENDPOINT": "https://example.test/v1/chat/completions",
                "PLOVER_LLM_EXTRA_HEADERS": '["x-deployment"]',
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                create_planner()
