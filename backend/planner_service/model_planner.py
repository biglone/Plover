from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
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


@dataclass
class HeaderBootstrapper:
    endpoint: str
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
    _cached_header_value: str | None = field(default=None, init=False, repr=False)
    _expires_at: float | None = field(default=None, init=False, repr=False)

    def _bootstrap_request(self) -> request.Request:
        data = self.body.encode("utf-8") if self.body is not None else None
        return request.Request(
            self.endpoint,
            data=data,
            headers=self.headers,
            method=self.method,
        )

    def resolve_header(self) -> tuple[str, str]:
        now = self.clock()
        if self._cached_header_value and (self._expires_at is None or now < self._expires_at):
            return self.header_name, self._cached_header_value

        with self.opener(self._bootstrap_request(), timeout=self.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
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

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        headers.update(self.extra_headers)
        if self.bootstrapper is not None:
            header_name, header_value = self.bootstrapper.resolve_header()
            headers[header_name] = header_value
            return headers
        if self.api_key:
            headers[self.api_key_header] = f"{self.api_key_prefix}{self.api_key}"
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
    extra_headers: dict[str, str] = {}
    raw_extra_headers = os.getenv("PLOVER_LLM_EXTRA_HEADERS")
    if raw_extra_headers:
        parsed_headers = json.loads(raw_extra_headers)
        if not isinstance(parsed_headers, dict):
            raise RuntimeError("PLOVER_LLM_EXTRA_HEADERS must be a JSON object")
        extra_headers = {str(key): str(value) for key, value in parsed_headers.items()}
    bootstrapper: HeaderBootstrapper | None = None
    bootstrap_endpoint = os.getenv("PLOVER_LLM_BOOTSTRAP_ENDPOINT")
    if bootstrap_endpoint:
        bootstrap_headers: dict[str, str] = {}
        raw_bootstrap_headers = os.getenv("PLOVER_LLM_BOOTSTRAP_HEADERS")
        if raw_bootstrap_headers:
            parsed_bootstrap_headers = json.loads(raw_bootstrap_headers)
            if not isinstance(parsed_bootstrap_headers, dict):
                raise RuntimeError("PLOVER_LLM_BOOTSTRAP_HEADERS must be a JSON object")
            bootstrap_headers = {str(key): str(value) for key, value in parsed_bootstrap_headers.items()}
        bootstrap_method = os.getenv("PLOVER_LLM_BOOTSTRAP_METHOD")
        bootstrap_body = os.getenv("PLOVER_LLM_BOOTSTRAP_BODY")
        if not bootstrap_method:
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
    )
    return ModelPlanner(model)
