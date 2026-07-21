import unittest
from unittest.mock import patch

from plover_core.models import ExecutionStatus, PlanState, PlanStep, PlanVersion, ReplanCause, StepAction
from planner_service.model_planner import (
    BootstrapRequestStep,
    HeaderBootstrapper,
    ModelPlanner,
    OpenAICompatibleChatModel,
    create_planner,
)


class FakeChatModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def complete(self, *, system: str, user: str, image_urls: tuple[str, ...] = ()) -> str:
        self.calls.append({"system": system, "user": user, "image_urls": image_urls})
        return self.response


class FakeHttpResponse:
    def __init__(
        self,
        body: bytes | None = None,
        *,
        lines: tuple[bytes, ...] = (),
        headers: dict[str, list[str]] | None = None,
    ) -> None:
        self._body = body or b""
        self._lines = lines
        self.headers = FakeHeaders(headers or {})

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def __iter__(self):
        return iter(self._lines)

    def read(self) -> bytes:
        return self._body


class FakeHeaders:
    def __init__(self, headers: dict[str, list[str]]) -> None:
        self._headers = {key.lower(): values for key, values in headers.items()}

    def get_all(self, name: str) -> list[str] | None:
        return self._headers.get(name.lower())


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
                completed=(
                    PlanStep(
                        "step-1",
                        "Open the report",
                        ExecutionStatus.COMPLETED,
                        actions=(StepAction("click", x=12, y=20),),
                    ),
                ),
                pending=(PlanStep("step-2", "Select the wrong option", actions=(StepAction("observe"),)),),
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
        self.assertIn("<click x=\"12\" y=\"20\" />", model.calls[0]["user"])
        self.assertIn("<observe />", model.calls[0]["user"])
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

    def test_openai_compatible_model_bootstraps_and_refreshes_auth_headers(self) -> None:
        requests_seen: list[tuple[str, dict[str, str]]] = []
        clock_value = [100.0]
        session_responses = iter(
            (
                b'{"session":{"token":"boot-token-1","expires_in":120}}',
                b'{"session":{"token":"boot-token-2","expires_in":120}}',
            )
        )

        def opener(http_request, *, timeout=None):
            headers = {key.lower(): value for key, value in http_request.header_items()}
            headers["cookie"] = http_request.get_header("Cookie") or ""
            requests_seen.append((http_request.full_url, headers))
            if http_request.full_url.endswith("/session"):
                cookies = {"Set-Cookie": [f"session_id=seed-{len([url for url, _ in requests_seen if url.endswith('/session')])}; Path=/"]}
                return FakeHttpResponse(next(session_responses), headers=cookies)
            if http_request.full_url.endswith("/chat/completions"):
                cookies = {"Set-Cookie": [f"request_seen={len([url for url, _ in requests_seen if url.endswith('/chat/completions')])}; Path=/"]}
                return FakeHttpResponse(
                    b'{"choices":[{"message":{"content":"<analysis>ok</analysis><steps><completed /><pending><step>Act</step></pending></steps>"}}]}',
                    headers=cookies,
                )
            return FakeHttpResponse(b"{}")

        bootstrapper = HeaderBootstrapper(
            endpoint="https://example.test/session",
            header_name="authorization",
            header_prefix="Bearer ",
            token_json_path="session.token",
            expires_in_json_path="session.expires_in",
            opener=opener,
            clock=lambda: clock_value[0],
        )
        model = OpenAICompatibleChatModel(
            endpoint="https://example.test/v1/chat/completions",
            model="computer-use",
            bootstrapper=bootstrapper,
            opener=opener,
        )

        model.complete(system="sys", user="first")
        clock_value[0] = 150.0
        model.complete(system="sys", user="second")
        clock_value[0] = 205.0
        model.complete(system="sys", user="third")

        session_calls = [headers for url, headers in requests_seen if url.endswith("/session")]
        model_calls = [headers for url, headers in requests_seen if url.endswith("/v1/chat/completions")]
        self.assertEqual(len(session_calls), 2)
        self.assertEqual(model_calls[0]["authorization"], "Bearer boot-token-1")
        self.assertEqual(model_calls[1]["authorization"], "Bearer boot-token-1")
        self.assertEqual(model_calls[2]["authorization"], "Bearer boot-token-2")
        self.assertEqual(model_calls[0]["cookie"], "session_id=seed-1")
        self.assertEqual(model_calls[1]["cookie"], "request_seen=1; session_id=seed-1")
        self.assertEqual(model_calls[2]["cookie"], "request_seen=2; session_id=seed-2")

    def test_openai_compatible_model_supports_multi_step_bootstrap_flow(self) -> None:
        requests_seen: list[tuple[str, dict[str, str], str | None]] = []
        stage_responses = iter(
            (
                b'{"stage":{"ticket":"ticket-1"}}',
                b'{"stage":{"ticket":"ticket-2"}}',
            )
        )
        exchange_responses = iter(
            (
                b'{"session":{"token":"boot-token-1","expires_in":120}}',
                b'{"session":{"token":"boot-token-2","expires_in":120}}',
            )
        )
        clock_value = [100.0]

        def opener(http_request, *, timeout=None):
            headers = {key.lower(): value for key, value in http_request.header_items()}
            headers["cookie"] = http_request.get_header("Cookie") or ""
            body = http_request.data.decode("utf-8") if http_request.data else None
            requests_seen.append((http_request.full_url, headers, body))
            if http_request.full_url.endswith("/session"):
                cookies = {"Set-Cookie": [f"seed=stage-{len([url for url, _, _ in requests_seen if url.endswith('/session')])}; Path=/"]}
                return FakeHttpResponse(next(stage_responses), headers=cookies)
            if http_request.full_url.endswith("/exchange"):
                cookies = {"Set-Cookie": [f"exchange=done-{len([url for url, _, _ in requests_seen if url.endswith('/exchange')])}; Path=/"]}
                return FakeHttpResponse(next(exchange_responses), headers=cookies)
            return FakeHttpResponse(
                b'{"choices":[{"message":{"content":"<analysis>ok</analysis><steps><completed /><pending><step>Act</step></pending></steps>"}}]}'
            )

        bootstrapper = HeaderBootstrapper(
            header_name="authorization",
            header_prefix="Bearer ",
            token_json_path="session.token",
            expires_in_json_path="session.expires_in",
            opener=opener,
            clock=lambda: clock_value[0],
            steps=(
                BootstrapRequestStep(
                    endpoint="https://example.test/session",
                    capture_json_paths={"ticket": "stage.ticket"},
                ),
                BootstrapRequestStep(
                    endpoint="https://example.test/exchange",
                    method="POST",
                    headers={"x-ticket": "${ticket}"},
                    body='{"ticket":"${ticket}"}',
                ),
            ),
        )
        model = OpenAICompatibleChatModel(
            endpoint="https://example.test/v1/chat/completions",
            model="computer-use",
            bootstrapper=bootstrapper,
            opener=opener,
        )

        model.complete(system="sys", user="first")
        clock_value[0] = 205.0
        model.complete(system="sys", user="second")

        bootstrap_calls = [(url, headers, body) for url, headers, body in requests_seen if not url.endswith("/v1/chat/completions")]
        model_calls = [headers for url, headers, _ in requests_seen if url.endswith("/v1/chat/completions")]
        self.assertEqual(
            [url for url, _, _ in bootstrap_calls],
            [
                "https://example.test/session",
                "https://example.test/exchange",
                "https://example.test/session",
                "https://example.test/exchange",
            ],
        )
        self.assertEqual(bootstrap_calls[1][1]["x-ticket"], "ticket-1")
        self.assertEqual(bootstrap_calls[1][2], '{"ticket":"ticket-1"}')
        self.assertEqual(bootstrap_calls[1][1]["cookie"], "seed=stage-1")
        self.assertEqual(bootstrap_calls[3][2], '{"ticket":"ticket-2"}')
        self.assertEqual(model_calls[0]["authorization"], "Bearer boot-token-1")
        self.assertEqual(model_calls[0]["cookie"], "exchange=done-1; seed=stage-1")
        self.assertEqual(model_calls[1]["authorization"], "Bearer boot-token-2")
        self.assertEqual(model_calls[1]["cookie"], "exchange=done-2; seed=stage-2")

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

    def test_create_planner_reads_bootstrap_configuration_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PLOVER_LLM_ENDPOINT": "https://example.test/v1/chat/completions",
                "PLOVER_LLM_BOOTSTRAP_ENDPOINT": "https://example.test/session",
                "PLOVER_LLM_BOOTSTRAP_METHOD": "post",
                "PLOVER_LLM_BOOTSTRAP_HEADERS": '{"x-bootstrap":"true"}',
                "PLOVER_LLM_BOOTSTRAP_BODY": '{"grant_type":"client_credentials"}',
                "PLOVER_LLM_BOOTSTRAP_HEADER_NAME": "x-session-token",
                "PLOVER_LLM_BOOTSTRAP_HEADER_PREFIX": "Token ",
                "PLOVER_LLM_BOOTSTRAP_TOKEN_PATH": "session.token",
                "PLOVER_LLM_BOOTSTRAP_EXPIRES_IN_PATH": "session.expires_in",
                "PLOVER_LLM_BOOTSTRAP_REFRESH_SKEW_SECONDS": "15",
            },
            clear=False,
        ):
            planner = create_planner()

        self.assertIsInstance(planner, ModelPlanner)
        self.assertIsInstance(planner._model.bootstrapper, HeaderBootstrapper)
        bootstrapper = planner._model.bootstrapper
        self.assertEqual(bootstrapper.endpoint, "https://example.test/session")
        self.assertEqual(bootstrapper.method, "POST")
        self.assertEqual(bootstrapper.headers, {"x-bootstrap": "true"})
        self.assertEqual(bootstrapper.body, '{"grant_type":"client_credentials"}')
        self.assertEqual(bootstrapper.header_name, "x-session-token")
        self.assertEqual(bootstrapper.header_prefix, "Token ")
        self.assertEqual(bootstrapper.token_json_path, "session.token")
        self.assertEqual(bootstrapper.expires_in_json_path, "session.expires_in")
        self.assertEqual(bootstrapper.refresh_skew_seconds, 15)
        self.assertIsNotNone(planner._model.cookie_jar)

    def test_create_planner_reads_bootstrap_flow_configuration_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PLOVER_LLM_ENDPOINT": "https://example.test/v1/chat/completions",
                "PLOVER_LLM_BOOTSTRAP_FLOW": (
                    '[{"endpoint":"https://example.test/session","capture":{"ticket":"stage.ticket"}},'
                    '{"endpoint":"https://example.test/exchange","method":"post","headers":{"x-ticket":"${ticket}"},'
                    '"body":"{\\"ticket\\":\\"${ticket}\\"}"}]'
                ),
                "PLOVER_LLM_BOOTSTRAP_HEADER_NAME": "x-session-token",
                "PLOVER_LLM_BOOTSTRAP_HEADER_PREFIX": "Token ",
                "PLOVER_LLM_BOOTSTRAP_TOKEN_PATH": "session.token",
                "PLOVER_LLM_BOOTSTRAP_EXPIRES_IN_PATH": "session.expires_in",
            },
            clear=False,
        ):
            planner = create_planner()

        self.assertIsInstance(planner, ModelPlanner)
        self.assertIsInstance(planner._model.bootstrapper, HeaderBootstrapper)
        bootstrapper = planner._model.bootstrapper
        self.assertEqual(len(bootstrapper.steps), 2)
        self.assertEqual(bootstrapper.steps[0].capture_json_paths, {"ticket": "stage.ticket"})
        self.assertEqual(bootstrapper.steps[1].method, "POST")
        self.assertEqual(bootstrapper.steps[1].headers, {"x-ticket": "${ticket}"})
        self.assertEqual(bootstrapper.steps[1].body, '{"ticket":"${ticket}"}')

    def test_create_planner_rejects_invalid_bootstrap_flow(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PLOVER_LLM_ENDPOINT": "https://example.test/v1/chat/completions",
                "PLOVER_LLM_BOOTSTRAP_FLOW": '{"endpoint":"https://example.test/session"}',
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                create_planner()

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

    def test_create_planner_rejects_non_object_bootstrap_headers(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PLOVER_LLM_ENDPOINT": "https://example.test/v1/chat/completions",
                "PLOVER_LLM_BOOTSTRAP_ENDPOINT": "https://example.test/session",
                "PLOVER_LLM_BOOTSTRAP_HEADERS": '["x-bootstrap"]',
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                create_planner()
