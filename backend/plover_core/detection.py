from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Action:
    kind: str
    target: str | None = None
    value: str | None = None

    def canonical(self) -> str:
        parts = [self.kind.strip().lower()]
        if self.target:
            parts.append(self.target.strip().lower())
        if self.value:
            parts.append(self.value.strip().lower())
        return ":".join(parts)


@dataclass(frozen=True)
class StuckDetection:
    failure_type: str
    repeated_action: str
    screenshot_distances: tuple[int, ...]


def grayscale_dhash(pixels: Sequence[Sequence[int]]) -> int:
    """Compute a 64-bit difference hash from an 8x9 grayscale pixel grid."""
    if len(pixels) != 8 or any(len(row) != 9 for row in pixels):
        raise ValueError("dHash requires an 8x9 grayscale grid")
    value = 0
    for row in pixels:
        for left, right in zip(row, row[1:]):
            value = (value << 1) | int(left > right)
    return value


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


class NonProgressDetector:
    """Conservatively detects repeated actions with visually static screens."""

    def __init__(
        self,
        *,
        action_window: int = 3,
        screenshot_window: int = 3,
        stable_distance: int = 4,
        meaningful_change_distance: int = 40,
    ) -> None:
        self._actions: deque[str] = deque(maxlen=action_window)
        self._screenshots: deque[int] = deque(maxlen=screenshot_window)
        self._stable_distance = stable_distance
        self._meaningful_change_distance = meaningful_change_distance

    def observe(self, action: Action, screenshot_hash: int | None = None) -> StuckDetection | None:
        canonical = action.canonical()
        self._actions.append(canonical)
        if screenshot_hash is not None:
            self._screenshots.append(screenshot_hash)

        if len(self._actions) < self._actions.maxlen or len(set(self._actions)) != 1:
            return None
        if len(self._screenshots) < self._screenshots.maxlen:
            return None

        distances = tuple(
            hamming_distance(left, right)
            for left, right in zip(self._screenshots, list(self._screenshots)[1:])
        )
        if any(distance > self._meaningful_change_distance for distance in distances):
            return None
        if any(distance > self._stable_distance for distance in distances):
            return None

        detection = StuckDetection(
            failure_type=f"REPEAT_{canonical.replace(':', '_').upper()}",
            repeated_action=canonical,
            screenshot_distances=distances,
        )
        self._actions.clear()
        self._screenshots.clear()
        return detection

