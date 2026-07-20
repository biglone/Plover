from __future__ import annotations

from dataclasses import dataclass
import re


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

UNSAFE_SENSITIVE_ACTIONS = (
    "enter",
    "type",
    "input",
    "paste",
    "fill",
    "provide",
    "use",
    "submit",
    "share",
)

SAFE_SENSITIVE_REFERENCES = (
    "stop if",
    "ask the user",
    "request user guidance",
    "outside the agent",
    "handled outside",
    "already entered",
    "already supplied",
    "entered by the user",
    "supplied by the user",
    "do not enter",
    "don't enter",
    "never enter",
)


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text) is not None


def _contains_sensitive_secret(normalized: str, term: str) -> bool:
    escaped = re.escape(term)
    if _matches(rf"{escaped}\s*[:=]\s*\S+", normalized):
        return True
    if _matches(rf"(?:{'|'.join(UNSAFE_SENSITIVE_ACTIONS)}).{{0,40}}{escaped}", normalized):
        return True
    return False


def _is_safe_sensitive_reference(normalized: str, term: str) -> bool:
    escaped = re.escape(term)
    if any(marker in normalized for marker in SAFE_SENSITIVE_REFERENCES):
        if _matches(rf"(?:{'|'.join(re.escape(marker) for marker in SAFE_SENSITIVE_REFERENCES)}).{{0,60}}{escaped}", normalized):
            return True
        if _matches(rf"{escaped}.{{0,60}}(?:{'|'.join(re.escape(marker) for marker in SAFE_SENSITIVE_REFERENCES)})", normalized):
            return True
    if _matches(rf"if.{{0,20}}{escaped}.{{0,20}}(?:required|needed|prompted|requested)", normalized):
        return True
    if _matches(rf"ask.{{0,20}}(?:user|me|operator).{{0,30}}{escaped}", normalized):
        return True
    return False


def inspect_text(text: str) -> SafetyDecision:
    normalized = " ".join(text.lower().split())
    for term in SENSITIVE_TERMS:
        if term in normalized:
            if _contains_sensitive_secret(normalized, term):
                return SafetyDecision(
                    allowed=False,
                    category="sensitive_data",
                    reason=f"Sensitive input may be required ({term}); request user guidance before execution.",
                )
            if _is_safe_sensitive_reference(normalized, term):
                continue
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
