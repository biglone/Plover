from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import sqlite3
from threading import RLock
from typing import Any

from plover_core.models import Annotation, ExecutionStatus, PlanState, PlanStep, PlanVersion, Proposal, ReplanCause


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunRecord:
    id: str
    task: str
    active_version_id: str
    versions: dict[str, PlanVersion]
    proposals: dict[str, Proposal] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    latest_screenshot_png: bytes = b""
    live_view_width: int = 1024
    live_view_height: int = 768
    status: str = "draft"

    def active_version(self) -> PlanVersion:
        return self.versions[self.active_version_id]

    def add_screenshot(self, screenshot: str) -> None:
        if screenshot:
            self.screenshots.append(screenshot)
            del self.screenshots[:-3]

    def set_live_view(self, screenshot_png: bytes, *, width: int = 1024, height: int = 768) -> None:
        self.latest_screenshot_png = screenshot_png
        self.live_view_width = width
        self.live_view_height = height

    def live_view_data_url(self) -> str | None:
        if not self.latest_screenshot_png:
            return None
        encoded = b64encode(self.latest_screenshot_png).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def add_event(self, event_type: str, *, created_at: str | None = None, **payload: Any) -> None:
        self.events.append(
            {
                "id": f"event-{len(self.events) + 1}",
                "type": event_type,
                "created_at": created_at or utc_now(),
                **payload,
            }
        )

    def active_safety_stop(self) -> dict[str, Any] | None:
        resolution_events = {
            "proposal_created",
            "safety_resume_proposed",
            "proposal_approved",
            "step_completed",
            "step_executed",
            "system_recovery_proposed",
        }
        for event in reversed(self.events):
            if event["type"] in resolution_events:
                return None
            if event["type"] == "safety_stop":
                return event
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "status": self.status,
            "active_version_id": self.active_version_id,
            "active_version": self.active_version().as_dict(),
            "versions": [version.as_dict() for version in self.versions.values()],
            "proposals": [proposal.as_dict() for proposal in self.proposals.values()],
            "events": list(self.events),
            "screenshot_count": len(self.screenshots),
            "active_safety_stop": self.active_safety_stop(),
            "live_view": {
                "image_url": self.live_view_data_url(),
                "width": self.live_view_width,
                "height": self.live_view_height,
            },
        }


class PlannerRepository:
    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = RLock()

    def create(self, run: RunRecord) -> RunRecord:
        with self._lock:
            self._runs[run.id] = run
        return run

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def save(self, run: RunRecord) -> RunRecord:
        with self._lock:
            if run.id not in self._runs:
                raise KeyError(run.id)
            self._runs[run.id] = run
        return run


def _step_from_dict(data: dict[str, Any]) -> PlanStep:
    return PlanStep(
        id=data["id"],
        instruction=data["instruction"],
        status=ExecutionStatus(data["status"]),
        ui_summary=data.get("ui_summary"),
        failure_reason=data.get("failure_reason"),
    )


def _version_from_dict(data: dict[str, Any]) -> PlanVersion:
    plan_data = data["plan"]
    plan = PlanState(
        completed=tuple(_step_from_dict(step) for step in plan_data["completed"]),
        pending=tuple(_step_from_dict(step) for step in plan_data["pending"]),
    )
    return PlanVersion(
        id=data["id"],
        plan=plan,
        parent_id=data.get("parent_id"),
        cause=ReplanCause(data["cause"]),
        created_at=data["created_at"],
        derived_constraints=tuple(data.get("derived_constraints", ())),
    )


def _annotation_from_dict(data: dict[str, Any] | None) -> Annotation | None:
    if not data:
        return None
    bbox = data["bbox"]
    return Annotation(
        screenshot=data["screenshot"],
        x=bbox["x"],
        y=bbox["y"],
        width=bbox["width"],
        height=bbox["height"],
    )


def _proposal_from_dict(data: dict[str, Any]) -> Proposal:
    return Proposal(
        id=data["id"],
        base_version_id=data["base_version_id"],
        version=_version_from_dict(data["version"]),
        summary=data["summary"],
        rationale=data["rationale"],
        status=data.get("status", "pending"),
        annotation=_annotation_from_dict(data.get("annotation")),
    )


class SqlitePlannerRepository:
    """Durable repository for plan artifacts and execution provenance."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = RLock()
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                active_version_id TEXT NOT NULL,
                status TEXT NOT NULL,
                versions_json TEXT NOT NULL,
                proposals_json TEXT NOT NULL,
                events_json TEXT NOT NULL,
                screenshots_json TEXT NOT NULL,
                latest_screenshot_png BLOB NOT NULL,
                live_view_width INTEGER NOT NULL,
                live_view_height INTEGER NOT NULL
            )
            """
        )
        self._connection.commit()

    def _encode(self, run: RunRecord) -> tuple[Any, ...]:
        return (
            run.id,
            run.task,
            run.active_version_id,
            run.status,
            json.dumps({key: value.as_dict() for key, value in run.versions.items()}),
            json.dumps({key: value.as_dict() for key, value in run.proposals.items()}),
            json.dumps(run.events),
            json.dumps(run.screenshots),
            run.latest_screenshot_png,
            run.live_view_width,
            run.live_view_height,
        )

    def _decode(self, row: sqlite3.Row) -> RunRecord:
        versions_data = json.loads(row["versions_json"])
        proposals_data = json.loads(row["proposals_json"])
        return RunRecord(
            id=row["id"],
            task=row["task"],
            active_version_id=row["active_version_id"],
            versions={key: _version_from_dict(value) for key, value in versions_data.items()},
            proposals={key: _proposal_from_dict(value) for key, value in proposals_data.items()},
            events=json.loads(row["events_json"]),
            screenshots=json.loads(row["screenshots_json"]),
            latest_screenshot_png=bytes(row["latest_screenshot_png"]),
            live_view_width=row["live_view_width"],
            live_view_height=row["live_view_height"],
            status=row["status"],
        )

    def create(self, run: RunRecord) -> RunRecord:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO runs (
                    id, task, active_version_id, status, versions_json,
                    proposals_json, events_json, screenshots_json,
                    latest_screenshot_png, live_view_width, live_view_height
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._encode(run),
            )
            self._connection.commit()
        return run

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return self._decode(row) if row else None

    def save(self, run: RunRecord) -> RunRecord:
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE runs SET
                    task = ?, active_version_id = ?, status = ?,
                    versions_json = ?, proposals_json = ?, events_json = ?,
                    screenshots_json = ?, latest_screenshot_png = ?,
                    live_view_width = ?, live_view_height = ?
                WHERE id = ?
                """,
                self._encode(run)[1:] + (run.id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(run.id)
            self._connection.commit()
        return run

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def create_repository() -> PlannerRepository | SqlitePlannerRepository:
    path = os.getenv("PLOVER_DATABASE_PATH")
    return SqlitePlannerRepository(path) if path else PlannerRepository()
