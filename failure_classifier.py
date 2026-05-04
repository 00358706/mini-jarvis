"""
failure_classifier.py — Deterministic post-route failure taxonomy.

Maps observable pipeline outcomes to exactly one of:

  MISSING_CAPABILITY  — no tool / capability to satisfy the request
  REASONING_LIMIT      — local model could not produce a usable answer
  KNOWLEDGE_GAP        — request needs external knowledge / cloud path
  EXECUTION_ERROR      — tool or sandbox execution failed

Rule-based only (no LLM). Used after dispatch attempts so logs and API
responses carry a stable failure reason.
"""

from __future__ import annotations

import re
from typing import Any, Literal

FailureReason = Literal[
    "MISSING_CAPABILITY",
    "REASONING_LIMIT",
    "KNOWLEDGE_GAP",
    "EXECUTION_ERROR",
]

_NOISY_EMPTY_REPLY = re.compile(r"^\s*(ok\.?|sure\.?|n/a|none)?\s*$", re.I)


def classify_failure(
    *,
    routed_to: str,
    tool_name: str | None = None,
    tool_success: bool | None = None,
    tool_error: str | None = None,
    llm_reply: str | None = None,
    llm_error: str | None = None,
    cloud_blocked: bool = False,
    no_matching_tool_intent: bool = False,
    validation_error: str | None = None,
) -> FailureReason | None:
    """
    Return a FailureReason when the request did not fully succeed, else None.

    Callers pass only the fields relevant to the branch that ran.
    """
    if validation_error:
        return "MISSING_CAPABILITY"

    if routed_to == "LOCAL_TOOLS":
        if no_matching_tool_intent:
            return "MISSING_CAPABILITY"
        if tool_name in (None, "", "none"):
            return "MISSING_CAPABILITY"
        if tool_success is False or tool_error:
            return "EXECUTION_ERROR"
        return None

    if routed_to == "LOCAL_LLM":
        if llm_error:
            if _is_timeout_or_capacity(llm_error):
                return "REASONING_LIMIT"
            return "EXECUTION_ERROR"
        if llm_reply is not None and _is_weak_or_empty_reply(llm_reply):
            return "REASONING_LIMIT"

    if routed_to == "CLOUD_LLM":
        if cloud_blocked:
            return "KNOWLEDGE_GAP"
        if llm_error:
            return "EXECUTION_ERROR"
        if llm_reply is not None and not llm_reply.strip():
            return "KNOWLEDGE_GAP"

    if routed_to == "DROP":
        return "MISSING_CAPABILITY"

    return None


def annotate_result_dict(
    result: dict[str, Any], fail: FailureReason | None
) -> dict[str, Any]:
    """Attach fail_reason to a dispatch result dict when applicable."""
    out = dict(result)
    if fail:
        out["fail_reason"] = fail
    else:
        out.setdefault("fail_reason", None)
    return out


def _is_weak_or_empty_reply(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    return bool(_NOISY_EMPTY_REPLY.match(t))


def _is_timeout_or_capacity(msg: str) -> bool:
    m = msg.lower()
    return any(
        s in m
        for s in (
            "timeout",
            "timed out",
            "context length",
            "token",
            "too long",
            "ollama",
            "cuda out of memory",
            "out of memory",
        )
    )
