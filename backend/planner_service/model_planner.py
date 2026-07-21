from __future__ import annotations

import json
import os
from string import Template
import time
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any, Callable, Protocol
from urllib import request
from uuid import uuid4

from plover_core.models import Annotation, PlanState, PlanVersion, Proposal, ReplanCause
from plover_core.plan import replace_pending
from plover_core.prompts import PROPOSAL_MODE_SUFFIX, failure_message, planner_system_prompt
from plover_core.xml_plan import parse_plan_response
from planner_service.store import utc_now


class ChatModel(Protocol):
    def complete(self, *, system: str, user: str, image_urls: tuple[str, ...] = ()) -> str: ...


def _resolve_json_path(data: Any, path: str) -> Any:
    if path in {"", "."}:
        return data
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise RuntimeError(f"JSON path '{path}' could not be resolved")
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                raise RuntimeError(f"JSON path '{path}' could not be resolved")
            current = current[index]
            continue
        raise RuntimeError(f"JSON path '{path}' could not be resolved")
    return current


def _json_object(raw: str | None, *, env_name: str) -> dict[str, str]:
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{env_name} must be a JSON object")
    return {str(key): str(value) for key, value in parsed.items()}


def _template_value(value: str, context: dict[str, str]) -> str:
    try:
        return Template(value).substitute(context)
    except KeyError as error:
        missing = error.args[0]
        raise RuntimeError(f"bootstrap template referenced missing value '{missing}'") from error


def _context_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if value is None:
        return ""
    return str(value)


@dataclass(frozen=True)
class BootstrapRequestStep:
    endpoint: str
    method: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    capture_json_paths: dict[str, str] = field(default_factory=dict)

    def request_method(self) -> str:
        return self.method or ("POST" if self.body is not None else "GET")


@dataclass
class HeaderBootstrapper:
    endpoint: str = ""
    header_name: str = "Authorization"
    header_prefix: str = "Bearer "
    token_json_path: str = "access_token"
    expires_in_json_path: str | None = "expires_in"
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    refresh_skew_seconds: float = 30
    timeout_seconds: float = 30
    opener: Callable[..., Any] = request.urlopen
    clock: Callable[[], float] = time.monotonic
    cookie_jar: "CookieJar | None" = None
    steps: tuple[BootstrapRequestStep, ...] = ()
    _cached_header_value: str | None = field(default=None, init=False, repr=False)
    _expires_at: float | None = field(default=None, init=False, repr=False)

    def _steps(self) -> tuple[BootstrapRequestStep, ...]:
        if self.steps:
            return self.steps
        if not self.endpoint:
            raise RuntimeError("bootstrap endpoint is required")
        return (
            BootstrapRequestStep(
                endpoint=self.endpoint,
                method=self.method,
                headers=self.headers,
                body=self.body,
            ),
        )

    def _bootstrap_request(self, step: BootstrapRequestStep, context: dict[str, str]) -> request.Request:
        endpoint = _template_value(step.endpoint, context)
        body = _template_value(step.body, context) if step.body is not None else None
        data = body.encode("utf-8") if body is not None else None
        headers = {key: _template_value(value, context) for key, value in step.headers.items()}
        if self.cookie_jar is not None:
            self.cookie_jar.inject(headers)
        return request.Request(
            endpoint,
            data=data,
            headers=headers,
            method=step.request_method(),
        )

    def resolve_header(self) -> tuple[str, str]:
        now = self.clock()
        if self._cached_header_value and (self._expires_at is None or now < self._expires_at):
            return self.header_name, self._cached_header_value

        context: dict[str, str] = {}
        body: Any = None
        steps = self._steps()
        for index, step in enumerate(steps):
            with self.opener(self._bootstrap_request(step, context), timeout=self.timeout_seconds) as response:
                if self.cookie_jar is not None:
                    self.cookie_jar.capture(response)
                payload = response.read()
            is_last = index == len(steps) - 1
            if step.capture_json_paths or is_last:
                body = json.loads(payload.decode("utf-8"))
            if step.capture_json_paths:
                if not isinstance(body, dict):
                    raise RuntimeError("bootstrap step did not return a JSON object")
                for name, path in step.capture_json_paths.items():
                    context[name] = _context_value(_resolve_json_path(body, path))

        token = _resolve_json_path(body, self.token_json_path)
        if not isinstance(token, str) or not token:
            raise RuntimeError("bootstrap response did not contain a usable token")
        self._cached_header_value = f"{self.header_prefix}{token}"

        expires_at: float | None = None
        if self.expires_in_json_path:
            expires_in = _resolve_json_path(body, self.expires_in_json_path)
            if expires_in is not None:
                try:
                    expires_seconds = float(expires_in)
                except (TypeError, ValueError) as error:
                    raise RuntimeError("bootstrap response did not contain a numeric expiry") from error
                expires_at = now + max(0.0, expires_seconds - self.refresh_skew_seconds)
        self._expires_at = expires_at
        return self.header_name, self._cached_header_value


@dataclass
class CookieJar:
    cookies: dict[str, str] = field(default_factory=dict)

    def capture(self, response: Any) -> None:
        headers = getattr(response, "headers", None)
        if headers is None or not hasattr(headers, "get_all"):
            return
        for raw_cookie in headers.get_all("Set-Cookie") or []:
            parsed = SimpleCookie()
            parsed.load(raw_cookie)
            for name, morsel in parsed.items():
                self.cookies[name] = morsel.value

    def inject(self, headers: dict[str, str]) -> None:
        if not self.cookies:
            return
        cookie_header = "; ".join(f"{name}={value}" for name, value in sorted(self.cookies.items()))
        if cookie_header:
            headers["Cookie"] = cookie_header


@dataclass
class OpenAICompatibleChatModel:
    endpoint: str
    model: str
    api_key: str | None = None
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer "
    extra_headers: dict[str, str] = field(default_factory=dict)
    stream: bool = False
    timeout_seconds: float = 90
    opener: Callable[..., Any] = request.urlopen
    bootstrapper: HeaderBootstrapper | None = None
    cookie_jar: CookieJar | None = None

    def __post_init__(self) -> None:
        if self.bootstrapper is None:
            return
        if self.cookie_jar is None and self.bootstrapper.cookie_jar is None:
            self.cookie_jar = CookieJar()
            self.bootstrapper.cookie_jar = self.cookie_jar
        elif self.cookie_jar is None:
            self.cookie_jar = self.bootstrapper.cookie_jar
        elif self.bootstrapper.cookie_jar is None:
            self.bootstrapper.cookie_jar = self.cookie_jar

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        headers.update(self.extra_headers)
        if self.bootstrapper is not None:
            header_name, header_value = self.bootstrapper.resolve_header()
            headers[header_name] = header_value
        elif self.api_key:
            headers[self.api_key_header] = f"{self.api_key_prefix}{self.api_key}"
        if self.cookie_jar is not None:
            self.cookie_jar.inject(headers)
        return headers

    @staticmethod
    def _extract_choice_content(choice: dict[str, Any]) -> str | None:
        for key in ("message", "delta"):
            payload = choice.get(key)
            if isinstance(payload, dict):
                content = payload.get("content")
                if isinstance(content, str) and content:
                    return content
        content = choice.get("content")
        if isinstance(content, str) and content:
            return content
        return None

    def _extract_response_content(self, body: dict[str, Any]) -> str:
        try:
            choice = body["choices"][0]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError("model response did not contain choices[0]") from error
        if not isinstance(choice, dict):
            raise RuntimeError("model response did not contain a structured choice")
        content = self._extract_choice_content(choice)
        if content is None:
            raise RuntimeError("model response did not contain choices[0].message.content")
        return content

    def _read_stream_response(self, response: Any) -> str:
        chunks: list[str] = []
        raw_lines: list[str] = []
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            raw_lines.append(line)
            if not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            try:
                choice = event["choices"][0]
            except (KeyError, IndexError, TypeError):
                continue
            if not isinstance(choice, dict):
                continue
            content = self._extract_choice_content(choice)
            if content:
                chunks.append(content)
        if chunks:
            return "".join(chunks)
        raw_text = "\n".join(raw_lines).strip()
        if not raw_text:
            raise RuntimeError("model response did not contain streamed content")
        try:
            body = json.loads(raw_text)
        except json.JSONDecodeError as error:
            raise RuntimeError("model response did not contain streamed content") from error
        if not isinstance(body, dict):
            raise RuntimeError("model response did not contain streamed content")
        return self._extract_response_content(body)

    def complete(self, *, system: str, user: str, image_urls: tuple[str, ...] = ()) -> str:
        user_content: str | list[dict[str, Any]] = user
        valid_images = [
            image_url
            for image_url in image_urls
            if image_url.startswith("data:image/") or image_url.startswith("http")
        ]
        if valid_images:
            user_content = [{"type": "text", "text": user}]
            user_content.extend(
                {"type": "image_url", "image_url": {"url": image_url}}
                for image_url in valid_images
            )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
        }
        if self.stream:
            payload["stream"] = True
        http_request = request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        with self.opener(http_request, timeout=self.timeout_seconds) as response:
            if self.cookie_jar is not None:
                self.cookie_jar.capture(response)
            if self.stream:
                return self._read_stream_response(response)
            body = json.loads(response.read().decode("utf-8"))
        if not isinstance(body, dict):
            raise RuntimeError("model response did not contain a JSON object")
        return self._extract_response_content(body)


def _plan_context(plan: PlanVersion) -> str:
    lines = ["<current_plan>", "<completed>"]
    for step in plan.plan.completed:
        lines.append(f'<step id="{step.id}">{step.instruction}</step>')
    lines.extend(["</completed>", "<pending>"])
    for step in plan.plan.pending:
        lines.append(f'<step id="{step.id}">{step.instruction}</step>')
    lines.extend(["</pending>", "</current_plan>"])
    return "\n".join(lines)


def _cause(*, guidance: str | None, annotation: Annotation | None, failure_type: str | None) -> ReplanCause:
    if annotation:
        return ReplanCause.ANNOTATION
    if failure_type:
        return ReplanCause.SYSTEM_DRIVEN_IR
    return ReplanCause.USER_GUIDANCE


class ModelPlanner:
    """Vision-model planner with schema validation and safe history preservation."""

    def __init__(self, model: ChatModel) -> None:
        self._model = model

    def create_initial(self, task: str) -> PlanVersion:
        response = self._model.complete(
            system=planner_system_prompt(),
            user=f"Create an initial plan for this task:\n{task}",
        )
        parsed = parse_plan_response(response)
        return PlanVersion(
            id=f"version-{uuid4().hex[:10]}",
            plan=parsed.state,
            parent_id=None,
            cause=ReplanCause.INITIAL,
            created_at=utc_now(),
            derived_constraints=("Preserve completed steps", "Verify the final visible state"),
        )

    def propose_repair(
        self,
        current: PlanVersion,
        *,
        guidance: str | None,
        annotation: Annotation | None,
        failure_type: str | None,
        screenshots: tuple[str, ...] = (),
        rationale: str | None = None,
    ) -> Proposal:
        cause = _cause(guidance=guidance, annotation=annotation, failure_type=failure_type)
        context = [_plan_context(current)]
        if guidance:
            context.append(f"<user_guidance>{guidance}</user_guidance>")
        if screenshots:
            context.append(f"<recent_screenshots count=\"{len(screenshots)}\" />")
        if annotation:
            context.append(
                f"<annotation_bbox x=\"{annotation.x}\" y=\"{annotation.y}\" "
                f"width=\"{annotation.width}\" height=\"{annotation.height}\" />"
            )
        if failure_type:
            context.append(failure_message(failure_type))
            context.append(PROPOSAL_MODE_SUFFIX)
        response = self._model.complete(
            system=planner_system_prompt(),
            user="\n".join(context),
            image_urls=screenshots,
        )
        parsed = parse_plan_response(response, current=current)
        new_plan = replace_pending(current.plan, parsed.state.pending)
        version = PlanVersion(
            id=f"version-{uuid4().hex[:10]}",
            plan=new_plan,
            parent_id=current.id,
            cause=cause,
            created_at=utc_now(),
            derived_constraints=("Preserve completed steps", "Validate the final visible state"),
        )
        summary = parsed.state.pending[0].instruction
        return Proposal(
            id=f"proposal-{uuid4().hex[:10]}",
            base_version_id=current.id,
            version=version,
            summary=summary,
            rationale=rationale or parsed.analysis,
            annotation=annotation,
        )


def create_planner() -> Any:
    endpoint = os.getenv("PLOVER_LLM_ENDPOINT")
    if not endpoint:
        from planner_service.planner import DeterministicPlanner

        return DeterministicPlanner()
    extra_headers = _json_object(os.getenv("PLOVER_LLM_EXTRA_HEADERS"), env_name="PLOVER_LLM_EXTRA_HEADERS")
    bootstrapper: HeaderBootstrapper | None = None
    cookie_jar = CookieJar()
    bootstrap_steps: tuple[BootstrapRequestStep, ...] = ()
    raw_bootstrap_flow = os.getenv("PLOVER_LLM_BOOTSTRAP_FLOW")
    if raw_bootstrap_flow:
        parsed_bootstrap_flow = json.loads(raw_bootstrap_flow)
        if not isinstance(parsed_bootstrap_flow, list) or not parsed_bootstrap_flow:
            raise RuntimeError("PLOVER_LLM_BOOTSTRAP_FLOW must be a non-empty JSON array")
        parsed_steps: list[BootstrapRequestStep] = []
        for index, raw_step in enumerate(parsed_bootstrap_flow, start=1):
            if not isinstance(raw_step, dict):
                raise RuntimeError(f"PLOVER_LLM_BOOTSTRAP_FLOW step {index} must be a JSON object")
            endpoint = raw_step.get("endpoint")
            if not isinstance(endpoint, str) or not endpoint:
                raise RuntimeError(f"PLOVER_LLM_BOOTSTRAP_FLOW step {index} requires a non-empty endpoint")
            method = raw_step.get("method")
            if method is not None and not isinstance(method, str):
                raise RuntimeError(f"PLOVER_LLM_BOOTSTRAP_FLOW step {index} method must be a string")
            body = raw_step.get("body")
            if body is not None and not isinstance(body, str):
                raise RuntimeError(f"PLOVER_LLM_BOOTSTRAP_FLOW step {index} body must be a string")
            headers = raw_step.get("headers") or {}
            if not isinstance(headers, dict):
                raise RuntimeError(f"PLOVER_LLM_BOOTSTRAP_FLOW step {index} headers must be a JSON object")
            capture = raw_step.get("capture") or {}
            if not isinstance(capture, dict):
                raise RuntimeError(f"PLOVER_LLM_BOOTSTRAP_FLOW step {index} capture must be a JSON object")
            parsed_steps.append(
                BootstrapRequestStep(
                    endpoint=endpoint,
                    method=(method or "").upper(),
                    headers={str(key): str(value) for key, value in headers.items()},
                    body=body,
                    capture_json_paths={str(key): str(value) for key, value in capture.items()},
                )
            )
        bootstrap_steps = tuple(parsed_steps)
    bootstrap_endpoint = os.getenv("PLOVER_LLM_BOOTSTRAP_ENDPOINT")
    if bootstrap_steps or bootstrap_endpoint:
        bootstrap_headers = _json_object(
            os.getenv("PLOVER_LLM_BOOTSTRAP_HEADERS"),
            env_name="PLOVER_LLM_BOOTSTRAP_HEADERS",
        )
        bootstrap_method = os.getenv("PLOVER_LLM_BOOTSTRAP_METHOD")
        bootstrap_body = os.getenv("PLOVER_LLM_BOOTSTRAP_BODY")
        if bootstrap_steps:
            bootstrap_method = bootstrap_method or "GET"
        elif not bootstrap_method:
            bootstrap_method = "POST" if bootstrap_body is not None else "GET"
        bootstrapper = HeaderBootstrapper(
            endpoint=bootstrap_endpoint,
            header_name=os.getenv("PLOVER_LLM_BOOTSTRAP_HEADER_NAME", os.getenv("PLOVER_LLM_API_KEY_HEADER", "Authorization")),
            header_prefix=os.getenv("PLOVER_LLM_BOOTSTRAP_HEADER_PREFIX", os.getenv("PLOVER_LLM_API_KEY_PREFIX", "Bearer ")),
            token_json_path=os.getenv("PLOVER_LLM_BOOTSTRAP_TOKEN_PATH", "access_token"),
            expires_in_json_path=os.getenv("PLOVER_LLM_BOOTSTRAP_EXPIRES_IN_PATH", "expires_in"),
            method=bootstrap_method.upper(),
            headers=bootstrap_headers,
            body=bootstrap_body,
            refresh_skew_seconds=float(os.getenv("PLOVER_LLM_BOOTSTRAP_REFRESH_SKEW_SECONDS", "30")),
            cookie_jar=cookie_jar,
            steps=bootstrap_steps,
        )
    model = OpenAICompatibleChatModel(
        endpoint=endpoint,
        model=os.getenv("PLOVER_LLM_MODEL", "computer-use"),
        api_key=os.getenv("PLOVER_LLM_API_KEY"),
        api_key_header=os.getenv("PLOVER_LLM_API_KEY_HEADER", "Authorization"),
        api_key_prefix=os.getenv("PLOVER_LLM_API_KEY_PREFIX", "Bearer "),
        extra_headers=extra_headers,
        stream=os.getenv("PLOVER_LLM_STREAM", "").lower() in {"1", "true", "yes", "on"},
        bootstrapper=bootstrapper,
        cookie_jar=cookie_jar,
    )
    return ModelPlanner(model)
