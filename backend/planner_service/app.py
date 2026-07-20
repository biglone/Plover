from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from plover_core.models import Annotation, PlanVersion, Proposal
from plover_core.plan import PlanInvariantError, approve_proposal, complete_next_step
from planner_service.planner import DeterministicPlanner
from planner_service.store import PlannerRepository, RunRecord, utc_now


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


class StatusRequest(BaseModel):
    status: str = Field(pattern="^(running|paused|failed)$")
    reason: str | None = Field(default=None, max_length=1000)


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


def create_app(
    repository: PlannerRepository | None = None,
    planner: DeterministicPlanner | None = None,
) -> FastAPI:
    repository = repository or PlannerRepository()
    planner = planner or DeterministicPlanner()
    app = FastAPI(title="Plover Planner Service", version="0.1.0")

    def get_run(run_id: str) -> RunRecord:
        run = repository.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "planner"}

    @app.post("/api/runs", status_code=201)
    def create_run(request: CreateRunRequest) -> dict[str, Any]:
        initial = planner.create_initial(request.task)
        run = RunRecord(
            id=f"run-{uuid4().hex[:10]}",
            task=request.task,
            active_version_id=initial.id,
            versions={initial.id: initial},
            status="draft",
        )
        run.add_event("plan_created", version_id=initial.id, cause=initial.cause.value)
        repository.create(run)
        return run.as_dict()

    @app.get("/api/runs/{run_id}")
    def get_run_state(run_id: str) -> dict[str, Any]:
        return get_run(run_id).as_dict()

    @app.post("/api/runs/{run_id}/replan", status_code=201)
    def propose_replan(run_id: str, request: ReplanRequest) -> dict[str, Any]:
        run = get_run(run_id)
        if not any((request.guidance, request.annotation, request.failure_type)):
            raise HTTPException(
                status_code=422,
                detail="one of guidance, annotation, or failure_type is required",
            )
        annotation = _annotation(request.annotation)
        if annotation:
            run.add_screenshot(annotation.screenshot)
        proposal = planner.propose_repair(
            run.active_version(),
            guidance=request.guidance,
            annotation=annotation,
            failure_type=request.failure_type,
            rationale=request.rationale,
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
        run.status = "running"
        run.add_event("proposal_approved", proposal_id=proposal_id, version_id=approved.id)
        repository.save(run)
        return run.as_dict()

    @app.post("/api/runs/{run_id}/steps/complete")
    def complete_step(run_id: str) -> dict[str, Any]:
        run = get_run(run_id)
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

    @app.post("/api/runs/{run_id}/status")
    def update_status(run_id: str, request: StatusRequest) -> dict[str, Any]:
        run = get_run(run_id)
        run.status = request.status
        run.add_event("status_changed", status=request.status, reason=request.reason)
        repository.save(run)
        return run.as_dict()

    return app


app = create_app()

