from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    category: str | None = None
    reason: str | None = None


SENSITIVE_TERMS = (
    "password",
    "passcode",
    "credential",
    "secret",
    "api key",
    "access token",
    "验证码",
    "密码",
)

AMBIGUOUS_PHRASES = (
    "the right one",
    "the appropriate one",
    "something suitable",
    "whatever looks best",
    "choose wisely",
)


def inspect_text(text: str) -> SafetyDecision:
    normalized = " ".join(text.lower().split())
    for term in SENSITIVE_TERMS:
        if term in normalized:
            return SafetyDecision(
                allowed=False,
                category="sensitive_data",
                reason=f"Sensitive input may be required ({term}); request user guidance before execution.",
            )
    for phrase in AMBIGUOUS_PHRASES:
        if phrase in normalized:
            return SafetyDecision(
                allowed=False,
                category="subjective_ambiguity",
                reason=f"Subjective instruction detected ({phrase}); clarify the intended target before execution.",
            )
    return SafetyDecision(allowed=True)
