"""
policy.py — Evaluate proposed plans (no execution, no models, no registry writes).

The gateway remains the authority; this module only returns allow/deny + reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from plans import Plan, PlanStep

# ──────────────────────────────────────────────────────────────────────────────
# Risk & heuristics (ordered by increasing sensitivity where applicable)
# ──────────────────────────────────────────────────────────────────────────────

RISK_LEVELS: Final[tuple[str, ...]] = (
    "level_0",
    "level_1",
    "level_2",
    "level_3",
    "level_4",
    "level_5",
)

RISK_FORBIDDEN: Final[str] = "level_5"
RISK_REQUIRES_APPROVAL_FROM: Final[str] = "level_3"

_CLOUD_TOOL_SUBSTRINGS: Final[tuple[str, ...]] = (
    "openrouter",
    "cloud_llm",
    "cloud-llm",
    "anthropic",
    "bedrock",
    "vertex",
    "azure_openai",
    "together.ai",
    "groq",
    "cohere",
)

_CLOUD_ARG_SUBSTRINGS: Final[tuple[str, ...]] = (
    "openrouter",
    "api.openai.com",
    "anthropic.com",
    "generativelanguage.googleapis.com",
    "bedrock",
    "azure.com",
    "groq.com",
    "cohere.ai",
    "together.xyz",
    "CLOUD_LLM",
    "cloud routing",
    "model_slug",
)

_DESTRUCTIVE_TOOL_SUBSTRINGS: Final[tuple[str, ...]] = (
    "delete",
    "remove",
    "destroy",
    "purge",
    "drop_",
    "_drop",
    "truncate",
    "wipe",
    "shred",
    "rm_",
    "_rm",
    "obliterate",
    "uninstall",
    "erase",
)

_DESCRIPTION_CLOUD_MARKERS: Final[tuple[str, ...]] = (
    "openrouter",
    "anthropic",
    "cloud_llm",
    "gpt-4",
    "gpt-3",
    "together.ai",
)

# ──────────────────────────────────────────────────────────────────────────────
# Decision object
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class PolicyDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Internal checks
# ──────────────────────────────────────────────────────────────────────────────


def _risk_index(risk: str) -> int | None:
    try:
        return RISK_LEVELS.index(risk)
    except ValueError:
        return None


def _risk_requires_approval_flag(risk: str) -> bool:
    idx = _risk_index(risk)
    if idx is None:
        return False
    min_idx = _risk_index(RISK_REQUIRES_APPROVAL_FROM)
    assert min_idx is not None
    return idx >= min_idx


def _values_scan_cloud(obj: Any) -> bool:
    if isinstance(obj, str):
        s = obj.lower()
        return any(m.lower() in s for m in _CLOUD_ARG_SUBSTRINGS)
    if isinstance(obj, dict):
        return any(_values_scan_cloud(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_values_scan_cloud(x) for x in obj)
    return False


def _step_suggests_cloud(step: PlanStep) -> bool:
    t = step.tool.lower()
    if any(m in t for m in _CLOUD_TOOL_SUBSTRINGS):
        return True
    if _values_scan_cloud(step.args):
        return True
    desc = step.description.lower()
    if desc and any(m in desc for m in _DESCRIPTION_CLOUD_MARKERS):
        return True
    return False


def _tool_name_suggests_delete(tool: str) -> bool:
    t = tool.lower()
    return any(m in t for m in _DESTRUCTIVE_TOOL_SUBSTRINGS)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def evaluate_plan(
    plan: Plan,
    installed_tools: set[str] | None = None,
    active_session: dict[str, Any] | None = None,
) -> PolicyDecision:
    """
    Decide whether ``plan`` is acceptable before any execution attempt.

    ``active_session`` is reserved for session-scoped policy extensions; it must
    not trigger side effects here.
    """
    reasons: list[str] = []
    _ = active_session  # reserved for session-scoped policy; no side effects.

    if _risk_index(plan.risk) is None:
        joined = ", ".join(RISK_LEVELS)
        return PolicyDecision(
            allowed=False,
            reasons=[
                f"Unknown risk level {plan.risk!r}; expected one of {joined}.",
            ],
        )

    if plan.risk == RISK_FORBIDDEN:
        return PolicyDecision(
            allowed=False,
            reasons=[
                "Risk level level_5 is forbidden; downgrade risk or refuse the operation.",
            ],
        )

    if _risk_requires_approval_flag(plan.risk) and not plan.requires_approval:
        return PolicyDecision(
            allowed=False,
            reasons=[
                f"Risk {plan.risk} requires requires_approval=true before proceeding.",
            ],
        )

    if len(plan.steps) > plan.limits.max_tool_calls:
        reasons.append(
            f"Step count {len(plan.steps)} exceeds limits.max_tool_calls "
            f"({plan.limits.max_tool_calls}).",
        )

    if not plan.limits.allow_cloud:
        offenders = [
            step.step_id
            for step in plan.steps
            if _step_suggests_cloud(step)
        ]
        if offenders:
            joined = ", ".join(offenders)
            reasons.append(
                f"limits.allow_cloud is false but steps suggest cloud use: {joined}",
            )

    if not plan.limits.allow_delete:
        offenders = [
            step.step_id
            for step in plan.steps
            if _tool_name_suggests_delete(step.tool)
        ]
        if offenders:
            joined = ", ".join(offenders)
            reasons.append(
                "limits.allow_delete is false but destructive tool names present: "
                f"{joined}",
            )

    if installed_tools is not None:
        unknown = [
            step
            for step in plan.steps
            if step.tool not in installed_tools
        ]
        if unknown:
            detail = ", ".join(f"{s.step_id}:{s.tool}" for s in unknown)
            reasons.append(
                f"Steps reference tools not in installed_tools: {detail}",
            )

    return PolicyDecision(allowed=(len(reasons) == 0), reasons=reasons)
