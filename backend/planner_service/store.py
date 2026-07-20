from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from plover_core.models import Annotation, PlanVersion, Proposal


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
    status: str = "draft"

    def active_version(self) -> PlanVersion:
        return self.versions[self.active_version_id]

    def add_screenshot(self, screenshot: str) -> None:
        if screenshot:
            self.screenshots.append(screenshot)
            del self.screenshots[:-3]

    def add_event(self, event_type: str, **payload: Any) -> None:
        self.events.append(
            {
                "id": f"event-{len(self.events) + 1}",
                "type": event_type,
                "created_at": utc_now(),
                **payload,
            }
        )

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

