from __future__ import annotations

import asyncio
from dataclasses import replace as dataclass_replace
import os
from typing import Any, Mapping
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from plover_core.models import Annotation, PlanState, PlanStep, PlanVersion, Proposal, ReplanCause, StepAction
from plover_core.plan import PlanInvariantError, approve_proposal, complete_next_step, fail_next_step, replace_pending
from plover_core.safety import inspect_text
from plover_core.xml_plan import PlanParseError
from planner_service.executor_gateway import ExecutorGateway, create_executor_gateway_from_env
from planner_service.model_planner import create_planner
from planner_service.store import (
    PlannerRepository,
    PostgresPlannerRepository,
    RunRecord,
    SqlitePlannerRepository,
    create_repository,
    utc_now,
)
from planner_service.vnc_gateway import VncTarget, VncTargetError, proxy_vnc


class CreateRunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=2000)


class AnnotationRequest(BaseModel):
    screenshot: str = Field(min_length=1)
    x: int = Field(ge=0, le=1024)
    y: int = Field(ge=0, le=768)
    width: int = Field(gt=0, le=1024)
    height: int = Field(gt=0, le=768)


class ReplanRequest(BaseModel):
    guidance: str | None = Field(default=None, max_length=2000)
    annotation: AnnotationRequest | None = None
    failure_type: str | None = Field(default=None, max_length=120)
    rationale: str | None = Field(default=None, max_length=2000)


class FailureRequest(BaseModel):
    failure_type: str = Field(min_length=1, max_length=120)
    rationale: str | None = Field(default=None, max_length=2000)


class ManualStepRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)
    ui_summary: str | None = Field(default=None, max_length=500)
    actions: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class ManualEditRequest(BaseModel):
    instructions: list[str] = Field(default_factory=list, max_length=20)
    steps: list[ManualStepRequest] = Field(default_factory=list, max_length=20)
    rationale: str | None = Field(default=None, max_length=2000)


class ResumeRunRequest(BaseModel):
    guidance: str | None = Field(default=None, max_length=2000)
    handled_outside: bool = False


class StatusRequest(BaseModel):
    status: str = Field(pattern="^(running|paused|failed)$")
    reason: str | None = Field(default=None, max_length=1000)


def _configured_api_token() -> str | None:
    token = os.getenv("PLOVER_API_TOKEN", "").strip()
    return token or None


def _bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _request_token(headers: Mapping[str, str]) -> str | None:
    token = _bearer_token(headers.get("authorization"))
    if token:
        return token
    header_token = headers.get("x-plover-token")
    if header_token:
        header_token = header_token.strip()
    return header_token or None


def _websocket_token(websocket: WebSocket) -> str | None:
    query_token = websocket.query_params.get("token")
    if query_token:
        query_token = query_token.strip()
        if query_token:
            return query_token
    return _request_token(websocket.headers)


def _annotation(request: AnnotationRequest | None) -> Annotation | None:
    if request is None:
        return None
    return Annotation(
        screenshot=request.screenshot,
        x=request.x,
        y=request.y,
        width=request.width,
        height=request.height,
    )


def _manual_pending(
    *,
    instructions: list[str],
    steps: list[ManualStepRequest],
) -> tuple[PlanStep, ...]:
    if instructions and steps:
        raise HTTPException(status_code=422, detail="provide either instructions or structured steps, not both")
    if steps:
        pending: list[PlanStep] = []
        for step in steps:
            instruction = step.instruction.strip()
            safety = inspect_text(instruction)
            if not safety.allowed:
                raise HTTPException(status_code=409, detail=safety.reason)
            try:
                actions = tuple(StepAction.from_dict(action) for action in step.actions)
            except (KeyError, ValueError) as error:
                raise HTTPException(status_code=422, detail=f"invalid structured step action: {error}") from error
            pending.append(
                PlanStep(
                    f"step-{uuid4().hex[:8]}",
                    instruction,
                    ui_summary=step.ui_summary,
                    actions=actions,
                )
            )
        return tuple(pending)

    normalized = tuple(instruction.strip() for instruction in instructions if instruction.strip())
    if not normalized:
        raise HTTPException(status_code=422, detail="at least one non-empty pending step is required")
    pending: list[PlanStep] = []
    for instruction in normalized:
        safety = inspect_text(instruction)
        if not safety.allowed:
            raise HTTPException(status_code=409, detail=safety.reason)
        pending.append(PlanStep(f"step-{uuid4().hex[:8]}", instruction))
    return tuple(pending)


def _record_executor_events(run: RunRecord, step_id: str, events: tuple[Any, ...]) -> None:
    for event in events:
        run.add_event(
            f"executor_{event.kind}",
            step_id=step_id,
            executor_kind=event.kind,
            ui_summary=event.ui_summary,
            detail=event.detail,
            created_at=event.created_at,
        )


def _sync_run_status(run: RunRecord) -> None:
    if run.active_safety_stop():
        run.status = "paused"
        return
    if any(proposal.status == "pending" for proposal in run.proposals.values()):
        run.status = "paused"
        return
    if any(step.status == "failed" for step in run.active_version().plan.pending):
        run.status = "paused"
        return
    run.status = "completed" if not run.active_version().plan.pending else "running"


def _manual_status_blocker(run: RunRecord) -> str | None:
    if run.active_safety_stop():
        return "run is blocked by a safety stop"
    if any(proposal.status == "pending" for proposal in run.proposals.values()):
        return "run has pending proposals that must be resolved first"
    if any(step.status == "failed" for step in run.active_version().plan.pending):
        return "run has a failed step that must be repaired first"
    if not run.active_version().plan.pending:
        return "run has no pending steps left to execute"
    return None


def _manual_completion_blocker(run: RunRecord) -> str | None:
    if run.status == "failed":
        return "run is failed and the current step cannot be completed yet"
    if run.active_safety_stop():
        return "run is blocked by a safety stop"
    if any(proposal.status == "pending" for proposal in run.proposals.values()):
        return "run has pending proposals that must be resolved first"
    if any(step.status == "failed" for step in run.active_version().plan.pending):
        return "run has a failed step that must be repaired first"
    if not run.active_version().plan.pending:
        return "run has no pending steps left to complete"
    return None


def _planner_screenshots(run: RunRecord, annotation: Annotation | None = None) -> tuple[str, ...]:
    images = [image for image in run.screenshots if image]
    live_view = run.live_view_data_url()
    if live_view:
        images.append(live_view)
    if annotation and annotation.screenshot:
        images.append(annotation.screenshot)
    deduped: list[str] = []
    for image in images:
        if image not in deduped:
            deduped.append(image)
    return tuple(deduped[-3:])


def create_app(
    repository: PlannerRepository | SqlitePlannerRepository | PostgresPlannerRepository | None = None,
    planner: Any | None = None,
    executor: ExecutorGateway | None = None,
) -> FastAPI:
    repository = repository or create_repository()
    planner = planner or create_planner()
    if executor is None:
        executor = create_executor_gateway_from_env()
    app = FastAPI(title="Plover Planner Service", version="0.1.0")
    api_token = _configured_api_token()
    public_paths = {"/health", "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}

    def get_run(run_id: str) -> RunRecord:
        run = repository.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.middleware("http")
    async def require_api_token(request: Request, call_next):
        if api_token is None or request.url.path in public_paths or not request.url.path.startswith("/api/"):
            return await call_next(request)
        if _request_token(request.headers) != api_token:
            return JSONResponse(
                status_code=401,
                content={"detail": "authentication required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "planner"}

    @app.post("/api/runs", status_code=201)
    def create_run(request: CreateRunRequest) -> dict[str, Any]:
        try:
            initial = planner.create_initial(request.task)
        except PlanParseError as error:
            raise HTTPException(status_code=422, detail=f"planner output rejected: {error}") from error
        safety = inspect_text(request.task)
        run = RunRecord(
            id=f"run-{uuid4().hex[:10]}",
            task=request.task,
            active_version_id=initial.id,
            versions={initial.id: initial},
            status="draft",
        )
        observation = executor.observe(run.id)
        run.set_live_view(observation.screenshot_png, width=observation.width, height=observation.height)
        run.add_event("plan_created", version_id=initial.id, cause=initial.cause.value)
        if not safety.allowed:
            run.status = "paused"
            run.add_event(
                "safety_stop",
                category=safety.category,
                reason=safety.reason,
            )
        repository.create(run)
        return run.as_dict()

    @app.get("/api/runs/{run_id}")
    def get_run_state(run_id: str) -> dict[str, Any]:
        return get_run(run_id).as_dict()

    @app.post("/api/runs/{run_id}/observe")
    def observe_run(run_id: str) -> dict[str, Any]:
        run = get_run(run_id)
        observation = executor.observe(run.id)
        run.set_live_view(observation.screenshot_png, width=observation.width, height=observation.height)
        run.add_event("live_view_refreshed")
        repository.save(run)
        return run.as_dict()

    @app.websocket("/api/runs/{run_id}/live")
    async def live_view(websocket: WebSocket, run_id: str) -> None:
        if api_token is not None and _websocket_token(websocket) != api_token:
            await websocket.close(code=1008, reason="authentication required")
            return
        run = repository.get(run_id)
        if run is None:
            await websocket.close(code=1008, reason="run not found")
            return
        await websocket.accept()
        try:
            while True:
                run = repository.get(run_id)
                if run is None:
                    await websocket.close(code=1008, reason="run not found")
                    return
                observation = await asyncio.to_thread(executor.observe, run.id)
                run.set_live_view(
                    observation.screenshot_png,
                    width=observation.width,
                    height=observation.height,
                )
                repository.save(run)
                await websocket.send_json(
                    {
                        "type": "frame",
                        "run_id": run.id,
                        "image_url": run.live_view_data_url(),
                        "width": run.live_view_width,
                        "height": run.live_view_height,
                        "status": run.status,
                        "latest_event": run.events[-1] if run.events else None,
                        "created_at": utc_now(),
                    }
                )
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            return

    @app.websocket("/api/runs/{run_id}/vnc")
    async def vnc_view(websocket: WebSocket, run_id: str) -> None:
        if api_token is not None and _websocket_token(websocket) != api_token:
            await websocket.close(code=1008, reason="authentication required")
            return
        if repository.get(run_id) is None:
            await websocket.close(code=1008, reason="run not found")
            return
        target_value = os.getenv("PLOVER_VNC_TARGET")
        if not target_value:
            await websocket.accept()
            await websocket.close(code=1013, reason="PLOVER_VNC_TARGET is not configured")
            return
        try:
            target = VncTarget.parse(target_value)
            await proxy_vnc(websocket, target)
        except (VncTargetError, ConnectionError, OSError) as error:
            if websocket.client_state.name != "DISCONNECTED":
                await websocket.close(code=1013, reason=str(error))

    @app.post("/api/runs/{run_id}/replan", status_code=201)
    def propose_replan(run_id: str, request: ReplanRequest) -> dict[str, Any]:
        run = get_run(run_id)
        safety = inspect_text(request.guidance or "")
        if not safety.allowed:
            run.status = "paused"
            run.add_event(
                "safety_stop",
                category=safety.category,
                reason=safety.reason,
            )
            repository.save(run)
            raise HTTPException(status_code=409, detail=safety.reason)
        if not any((request.guidance, request.annotation, request.failure_type)):
            raise HTTPException(
                status_code=422,
                detail="one of guidance, annotation, or failure_type is required",
            )
        annotation = _annotation(request.annotation)
        if annotation:
            run.add_screenshot(annotation.screenshot)
        screenshots = _planner_screenshots(run, annotation)
        try:
            proposal = planner.propose_repair(
                run.active_version(),
                guidance=request.guidance,
                annotation=annotation,
                failure_type=request.failure_type,
                screenshots=screenshots,
                rationale=request.rationale,
            )
        except PlanParseError as error:
            run.status = "paused"
            run.add_event("planner_output_rejected", reason=str(error))
            repository.save(run)
            raise HTTPException(status_code=422, detail=f"planner output rejected: {error}") from error
        run.proposals[proposal.id] = proposal
        run.status = "paused"
        run.add_event(
            "proposal_created",
            proposal_id=proposal.id,
            cause=proposal.version.cause.value,
        )
        repository.save(run)
        return proposal.as_dict()

    @app.post("/api/runs/{run_id}/manual-edit", status_code=201)
    def propose_manual_edit(run_id: str, request: ManualEditRequest) -> dict[str, Any]:
        run = get_run(run_id)
        current = run.active_version()
        try:
            pending = _manual_pending(
                instructions=request.instructions,
                steps=request.steps,
            )
            updated_plan = replace_pending(current.plan, pending)
        except PlanInvariantError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except HTTPException as error:
            if error.status_code == 409:
                run.status = "paused"
                run.add_event("safety_stop", reason=error.detail)
                repository.save(run)
            raise

        proposal = Proposal(
            id=f"proposal-{uuid4().hex[:10]}",
            base_version_id=current.id,
            version=PlanVersion(
                id=f"version-{uuid4().hex[:10]}",
                plan=PlanState(completed=updated_plan.completed, pending=updated_plan.pending),
                parent_id=current.id,
                cause=ReplanCause.MANUAL_EDIT,
                created_at=utc_now(),
                derived_constraints=(
                    "Apply the manually edited pending suffix",
                    "Preserve completed steps",
                ),
            ),
            summary=pending[0].instruction,
            rationale=request.rationale
            or "The pending suffix was edited directly while preserving completed history.",
        )
        run.proposals[proposal.id] = proposal
        run.status = "paused"
        run.add_event(
            "proposal_created",
            proposal_id=proposal.id,
            cause=proposal.version.cause.value,
        )
        repository.save(run)
        return proposal.as_dict()

    @app.post("/api/runs/{run_id}/resume", status_code=201)
    def resume_safety_paused_run(run_id: str, request: ResumeRunRequest) -> dict[str, Any]:
        run = get_run(run_id)
        safety_stop = run.active_safety_stop()
        if safety_stop is None:
            raise HTTPException(status_code=409, detail="run is not waiting on a safety stop")

        guidance = (request.guidance or "").strip()
        if not request.handled_outside and not guidance:
            raise HTTPException(
                status_code=422,
                detail="guidance is required unless the interaction was handled outside the agent",
            )
        if guidance:
            safety = inspect_text(guidance)
            if not safety.allowed:
                run.add_event(
                    "safety_resume_rejected",
                    category=safety.category,
                    reason=safety.reason,
                )
                repository.save(run)
                raise HTTPException(status_code=409, detail=safety.reason)

        if request.handled_outside:
            resume_guidance = (
                "Continue from the current screen after the blocked interaction was "
                "completed outside the agent."
            )
            if guidance:
                resume_guidance = f"{resume_guidance} User note: {guidance}"
            rationale = (
                "The user completed the sensitive or ambiguous interaction outside "
                "the agent, so only the pending suffix needs to be rebuilt."
            )
        else:
            resume_guidance = guidance
            rationale = (
                "The user clarified the safety-paused interaction, so only the "
                "pending suffix needs to be rebuilt."
            )

        try:
            proposal = planner.propose_repair(
                run.active_version(),
                guidance=resume_guidance,
                annotation=None,
                failure_type=None,
                screenshots=_planner_screenshots(run),
                rationale=rationale,
            )
        except PlanParseError as error:
            run.add_event("planner_output_rejected", reason=str(error))
            repository.save(run)
            raise HTTPException(status_code=422, detail=f"planner output rejected: {error}") from error

        run.proposals[proposal.id] = proposal
        run.status = "paused"
        run.add_event(
            "safety_resume_proposed",
            proposal_id=proposal.id,
            safety_event_id=safety_stop["id"],
            category=safety_stop.get("category"),
            handled_outside=request.handled_outside,
        )
        repository.save(run)
        return proposal.as_dict()

    @app.post("/api/runs/{run_id}/failures", status_code=201)
    def propose_system_recovery(run_id: str, request: FailureRequest) -> dict[str, Any]:
        run = get_run(run_id)
        proposal = planner.propose_repair(
            run.active_version(),
            guidance=None,
            annotation=None,
            failure_type=request.failure_type,
            screenshots=_planner_screenshots(run),
            rationale=request.rationale,
        )
        run.proposals[proposal.id] = proposal
        run.status = "paused"
        run.add_event(
            "system_recovery_proposed",
            proposal_id=proposal.id,
            failure_type=request.failure_type,
        )
        repository.save(run)
        return proposal.as_dict()

    @app.post("/api/runs/{run_id}/proposals/{proposal_id}/approve")
    def approve_replan(run_id: str, proposal_id: str) -> dict[str, Any]:
        run = get_run(run_id)
        proposal = run.proposals.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        try:
            approved = approve_proposal(run.active_version(), proposal)
        except PlanInvariantError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        run.versions[approved.id] = approved
        run.active_version_id = approved.id
        run.proposals[proposal_id] = Proposal(
            id=proposal.id,
            base_version_id=proposal.base_version_id,
            version=proposal.version,
            summary=proposal.summary,
            rationale=proposal.rationale,
            status="approved",
            annotation=proposal.annotation,
        )
        for other in run.proposals.values():
            if other.id != proposal_id and other.status == "pending" and other.base_version_id == proposal.base_version_id:
                run.proposals[other.id] = dataclass_replace(other, status="superseded")
                run.add_event(
                    "proposal_superseded",
                    proposal_id=other.id,
                    superseded_by=proposal_id,
                )
        run.add_event("proposal_approved", proposal_id=proposal_id, version_id=approved.id)
        _sync_run_status(run)
        repository.save(run)
        return run.as_dict()

    @app.post("/api/runs/{run_id}/proposals/{proposal_id}/reject")
    def reject_replan(run_id: str, proposal_id: str) -> dict[str, Any]:
        run = get_run(run_id)
        proposal = run.proposals.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        if proposal.status != "pending":
            raise HTTPException(status_code=409, detail="proposal is not pending")
        run.proposals[proposal_id] = dataclass_replace(proposal, status="rejected")
        run.add_event("proposal_rejected", proposal_id=proposal_id)
        _sync_run_status(run)
        repository.save(run)
        return run.as_dict()

    @app.post("/api/runs/{run_id}/steps/complete")
    def complete_step(run_id: str) -> dict[str, Any]:
        run = get_run(run_id)
        blocker = _manual_completion_blocker(run)
        if blocker is not None:
            raise HTTPException(status_code=409, detail=blocker)
        current = run.active_version()
        updated_plan = complete_next_step(current.plan)
        updated = PlanVersion(
            id=f"version-{uuid4().hex[:10]}",
            plan=updated_plan,
            parent_id=current.id,
            cause=current.cause,
            created_at=utc_now(),
            derived_constraints=current.derived_constraints,
        )
        run.versions[updated.id] = updated
        run.active_version_id = updated.id
        run.status = "completed" if not updated.plan.pending else "running"
        run.add_event(
            "step_completed",
            step_id=current.plan.pending[0].id if current.plan.pending else None,
            version_id=updated.id,
        )
        repository.save(run)
        return run.as_dict()

    @app.post("/api/runs/{run_id}/execute-next")
    def execute_next(run_id: str) -> dict[str, Any]:
        run = get_run(run_id)
        if run.status in {"paused", "failed"}:
            reason = (
                "Run is paused and requires user guidance before execution."
                if run.status == "paused"
                else "Run is failed and requires a manual reset before execution."
            )
            run.add_event(
                "execution_blocked",
                reason=reason,
            )
            repository.save(run)
            return run.as_dict()
        current = run.active_version()
        if not current.plan.pending:
            run.status = "completed"
            repository.save(run)
            return run.as_dict()

        step = current.plan.pending[0]
        safety = inspect_text(step.instruction)
        if not safety.allowed:
            run.status = "paused"
            run.add_event(
                "safety_stop",
                step_id=step.id,
                category=safety.category,
                reason=safety.reason,
            )
            repository.save(run)
            return run.as_dict()
        run.status = "running"
        run.add_event("step_execution_started", step_id=step.id, instruction=step.instruction)
        result = executor.execute_step(run.id, step)
        if result.events:
            _record_executor_events(run, step.id, result.events)
        if result.screenshot_png:
            run.set_live_view(result.screenshot_png, width=result.width, height=result.height)
            run.add_screenshot(run.live_view_data_url() or "")

        if not result.ok:
            failed_plan = fail_next_step(
                current.plan,
                reason=result.failure_type or "executor failure",
            )
            failed_version = PlanVersion(
                id=f"version-{uuid4().hex[:10]}",
                plan=failed_plan,
                parent_id=current.id,
                cause=current.cause,
                created_at=utc_now(),
                derived_constraints=current.derived_constraints,
            )
            run.versions[failed_version.id] = failed_version
            run.active_version_id = failed_version.id
            proposal = planner.propose_repair(
                failed_version,
                guidance=None,
                annotation=None,
                failure_type=result.failure_type,
                screenshots=_planner_screenshots(run),
                rationale=(
                    f"Execution failed with {result.failure_type}. "
                    "A system-driven recovery proposal was generated automatically."
                ),
            )
            run.proposals[proposal.id] = proposal
            run.status = "paused"
            run.add_event(
                "step_execution_failed",
                step_id=step.id,
                version_id=failed_version.id,
                failure_type=result.failure_type,
                proposal_id=proposal.id,
            )
            repository.save(run)
            return run.as_dict()

        updated_plan = complete_next_step(current.plan, ui_summary=result.summary)
        updated = PlanVersion(
            id=f"version-{uuid4().hex[:10]}",
            plan=updated_plan,
            parent_id=current.id,
            cause=current.cause,
            created_at=utc_now(),
            derived_constraints=current.derived_constraints,
        )
        run.versions[updated.id] = updated
        run.active_version_id = updated.id
        run.status = "completed" if not updated.plan.pending else "running"
        run.add_event(
            "step_executed",
            step_id=step.id,
            version_id=updated.id,
            ui_summary=result.summary,
        )
        repository.save(run)
        return run.as_dict()

    @app.post("/api/runs/{run_id}/status")
    def update_status(run_id: str, request: StatusRequest) -> dict[str, Any]:
        run = get_run(run_id)
        reason = (request.reason or "").strip() or None
        if request.status == "failed" and reason is None:
            raise HTTPException(status_code=422, detail="reason is required when marking a run as failed")
        if request.status == "running":
            blocker = _manual_status_blocker(run)
            if blocker is not None:
                raise HTTPException(status_code=409, detail=blocker)
        run.status = request.status
        run.add_event("status_changed", status=request.status, reason=reason)
        repository.save(run)
        return run.as_dict()

    return app


app = create_app()
