from __future__ import annotations

import json
import os
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

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers[self.api_key_header] = f"{self.api_key_prefix}{self.api_key}"
        headers.update(self.extra_headers)
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
    model = OpenAICompatibleChatModel(
        endpoint=endpoint,
        model=os.getenv("PLOVER_LLM_MODEL", "computer-use"),
        api_key=os.getenv("PLOVER_LLM_API_KEY"),
        api_key_header=os.getenv("PLOVER_LLM_API_KEY_HEADER", "Authorization"),
        api_key_prefix=os.getenv("PLOVER_LLM_API_KEY_PREFIX", "Bearer "),
        extra_headers=extra_headers,
        stream=os.getenv("PLOVER_LLM_STREAM", "").lower() in {"1", "true", "yes", "on"},
    )
    return ModelPlanner(model)
