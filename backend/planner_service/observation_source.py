from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import os
from pathlib import Path
from typing import Protocol
from urllib.request import Request, urlopen

from PIL import Image

from executor_service.driver import SCREEN_HEIGHT, SCREEN_WIDTH


@dataclass(frozen=True)
class LiveObservation:
    screenshot_png: bytes
    width: int
    height: int


class ObservationSource(Protocol):
    def observe(self, run_id: str) -> LiveObservation: ...


class ObservationSourceError(RuntimeError):
    """Raised when an external observation source cannot provide a frame."""


def _normalize_image(payload: bytes) -> LiveObservation:
    try:
        with Image.open(BytesIO(payload)) as image:
            image.load()
            width, height = image.size
            output = BytesIO()
            image.save(output, format="PNG")
    except Exception as error:  # pragma: no cover - exercised via public adapters
        raise ObservationSourceError("observation source returned an unreadable image") from error
    return LiveObservation(
        screenshot_png=output.getvalue(),
        width=width or SCREEN_WIDTH,
        height=height or SCREEN_HEIGHT,
    )


@dataclass(frozen=True)
class FileObservationSource:
    path_template: str

    def observe(self, run_id: str) -> LiveObservation:
        path = Path(self.path_template.format(run_id=run_id))
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise ObservationSourceError(f"failed to read observation frame from {path}") from error
        return _normalize_image(payload)


@dataclass(frozen=True)
class HttpObservationSource:
    url_template: str
    headers: dict[str, str]
    timeout_seconds: float = 5.0

    def observe(self, run_id: str) -> LiveObservation:
        url = self.url_template.format(run_id=run_id)
        headers = {key: value.format(run_id=run_id) for key, value in self.headers.items()}
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read()
        except OSError as error:
            raise ObservationSourceError(f"failed to fetch observation frame from {url}") from error
        return _normalize_image(payload)


def _json_headers(value: str) -> dict[str, str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("PLOVER_OBSERVATION_HEADERS must be valid JSON") from error
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(header_value, str)
        for key, header_value in parsed.items()
    ):
        raise ValueError("PLOVER_OBSERVATION_HEADERS must be a JSON object of string pairs")
    return parsed


def create_observation_source_from_env() -> ObservationSource | None:
    path_template = (os.getenv("PLOVER_OBSERVATION_PATH") or "").strip()
    url_template = (os.getenv("PLOVER_OBSERVATION_URL") or "").strip()
    if path_template and url_template:
        raise ValueError("configure only one of PLOVER_OBSERVATION_PATH or PLOVER_OBSERVATION_URL")
    if path_template:
        return FileObservationSource(path_template=path_template)
    if not url_template:
        return None

    headers_value = (os.getenv("PLOVER_OBSERVATION_HEADERS") or "").strip()
    headers = _json_headers(headers_value) if headers_value else {}
    timeout_value = (os.getenv("PLOVER_OBSERVATION_TIMEOUT_SECONDS") or "5").strip()
    try:
        timeout_seconds = float(timeout_value)
    except ValueError as error:
        raise ValueError("PLOVER_OBSERVATION_TIMEOUT_SECONDS must be a positive number") from error
    if timeout_seconds <= 0:
        raise ValueError("PLOVER_OBSERVATION_TIMEOUT_SECONDS must be a positive number")
    return HttpObservationSource(
        url_template=url_template,
        headers=headers,
        timeout_seconds=timeout_seconds,
    )
