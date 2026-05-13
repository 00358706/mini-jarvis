"""
Deterministic NL → structured Plan for ``POST /plans/from-message``.

Proposal-only: no tools, sandbox, registry mutations, approvals, or execution.
Uses an explicit allowlist of agents and message→tool mappings. Tool steps are
emitted only when the tool name is present in ``installed_tool_names`` (registry
``installed`` truth passed in from the gateway).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from plans import Plan, PlanLimits, PlanStep

MAINTAINER_AGENT: Final[str] = "project_maintainer_agent"
MEDIA_AGENT: Final[str] = "media_agent"

_SUPPORTED_AGENTS: Final[frozenset[str]] = frozenset({MAINTAINER_AGENT, MEDIA_AGENT})

_AUTOMATION_LAB_HINT: Final[str] = (
    "Use the Automation Lab proposal lane (review-only artifacts) or add an "
    "installed, schema-valid gateway tool before execution. The gateway does not "
    "invent callable tools for this capability."
)


@dataclass(frozen=True)
class BuildPlanOk:
    plan: Plan


@dataclass(frozen=True)
class BuildMissingCapability:
    """No :class:`Plan` is produced; caller must not run ``save_pending_plan``."""

    reason_code: str
    detail: str
    hint: str
    proposal_needed: bool


@dataclass(frozen=True)
class BuildUnsupportedAgent:
    agent: str
    detail: str


BuildFromMessageResult = BuildPlanOk | BuildMissingCapability | BuildUnsupportedAgent


def _truncate_summary(msg: str) -> str:
    msg = (msg or "").strip()
    if len(msg) <= 200:
        return msg or "Plan proposed from message."
    return msg[:199] + "…"


def extract_simple_filename(message: str) -> str | None:
    """
    Extract a simple repo-relative filename token like README.md from message.
    Rejects separators to avoid paths in this first version.
    """
    m = re.search(r"(?i)\b([A-Z0-9][A-Z0-9_.-]{0,127}\.[A-Z0-9]{1,8})\b", message)
    if not m:
        return None
    token = m.group(1).strip()
    if "/" in token or "\\" in token:
        return None
    return token


def _base_plan(*, plan_id: str, agent: str, summary: str, tool: str, args: dict, desc: str) -> Plan:
    return Plan(
        plan_id=plan_id,
        summary=_truncate_summary(summary),
        agent=agent,
        risk="level_0",
        requires_approval=True,
        steps=[PlanStep(step_id="step_1", tool=tool, args=args, description=desc)],
        limits=PlanLimits(
            max_tool_calls=6,
            max_runtime_seconds=90,
            allow_cloud=False,
            allow_delete=False,
        ),
        status="proposed",
    )


def _build_maintainer_plan(
    *, message: str, agent: str, plan_id: str, installed_tool_names: set[str]
) -> BuildFromMessageResult:
    """
    Preserve historical ``project_maintainer_agent`` behavior (single-step,
    deterministic). Maintainer does not emit media stack tools; media keywords
    fall back to ``list_project_files``.
    """
    msg = (message or "").strip()
    msg_l = msg.lower()

    tool = "list_project_files"
    args: dict = {"root": ".", "max_results": 200}
    desc = "List repository files (safe discovery)."

    if "radarr_search" in msg_l or "radarr" in msg_l or "sonarr" in msg_l or "sabnzbd" in msg_l:
        tool = "list_project_files"
        args = {"root": ".", "max_results": 200}
        desc = "Safe fallback: list repository files (maintainer tools only)."
    elif ("search" in msg_l) or ("find references" in msg_l) or ("find reference" in msg_l):
        tool = "search_repo"
        query = None
        mm = re.search(r"(?i)\bfor\s+['\"]?([A-Z0-9_.-]{1,200})['\"]?\b", msg)
        if mm:
            query = mm.group(1).strip()
        if not query:
            query = msg[:200]
        args = {
            "query": query,
            "root": ".",
            "max_results": 50,
            "max_file_size_bytes": 100000,
        }
        desc = "Literal search over repository text files."
    elif ("list files" in msg_l) or ("show files" in msg_l) or ("list project files" in msg_l):
        tool = "list_project_files"
        args = {"root": ".", "max_results": 200}
        desc = "List repository files."
    elif ("inspect" in msg_l) or ("read file" in msg_l) or ("read " in msg_l):
        fn = extract_simple_filename(msg)
        if fn:
            tool = "inspect_file"
            args = {"path": fn}
            desc = "Read a repository file for review."
        else:
            tool = "list_project_files"
            args = {"root": ".", "max_results": 200}
            desc = "Safe fallback: list repository files (no filename detected)."

    if tool not in installed_tool_names:
        return BuildMissingCapability(
            reason_code="tool_not_installed",
            detail=f"Tool {tool!r} is not in the installed registry; cannot build a valid plan.",
            hint=_AUTOMATION_LAB_HINT,
            proposal_needed=True,
        )
    return BuildPlanOk(plan=_base_plan(plan_id=plan_id, agent=agent, summary=msg, tool=tool, args=args, desc=desc))


def _extract_media_title_movie(msg: str) -> str | None:
    for pat in (
        r"(?i)\b(?:search|find)\s+for\s+movie\s+(.+)$",
        r"(?i)\bsearch\s+movie\s+(.+)$",
        r"(?i)\bfind\s+movie\s+(.+)$",
    ):
        m = re.search(pat, msg.strip())
        if m:
            t = m.group(1).strip().strip('\'"').strip()
            return t[:200] if t else None
    return None


def _extract_media_title_series(msg: str) -> str | None:
    for pat in (
        r"(?i)\b(?:search|find)\s+for\s+(?:series|show)\s+(.+)$",
        r"(?i)\bsearch\s+(?:series|show)\s+(.+)$",
        r"(?i)\bfind\s+(?:series|show)\s+(.+)$",
    ):
        m = re.search(pat, msg.strip())
        if m:
            t = m.group(1).strip().strip('\'"').strip()
            return t[:200] if t else None
    return None


def _media_wants_navidrome_catalog(msg: str) -> bool:
    """Navidrome / album-browsing intents have no installed callable tool in-repo."""
    msg_l = msg.lower()
    if "navidrome" in msg_l:
        return True
    return bool(re.search(r"(?i)\bnavidrome\b.*\balbum", msg)) or bool(
        re.search(r"(?i)\balbums?\b.*\bnavidrome\b", msg)
    )


def _media_wants_queue(msg_l: str) -> bool:
    return (
        "sabnzbd queue" in msg_l
        or "download queue" in msg_l
        or "sabnzbd status" in msg_l
        or ("sabnzbd" in msg_l and "queue" in msg_l)
    )


def _build_media_plan(
    *, message: str, agent: str, plan_id: str, installed_tool_names: set[str]
) -> BuildFromMessageResult:
    """
    Deterministic media mappings. Order: Navidrome/catalog (missing) → queue →
    movie (Radarr) → series (Sonarr) → unsupported pattern.
    """
    msg = (message or "").strip()
    msg_l = msg.lower()

    if _media_wants_navidrome_catalog(msg):
        return BuildMissingCapability(
            reason_code="navidrome_catalog_not_installed",
            detail="No installed gateway tool handles Navidrome / recently-added album catalog requests.",
            hint=_AUTOMATION_LAB_HINT,
            proposal_needed=True,
        )

    if _media_wants_queue(msg_l):
        if "sabnzbd_queue" not in installed_tool_names:
            return BuildMissingCapability(
                reason_code="tool_not_installed",
                detail="sabnzbd_queue is not installed in the registry.",
                hint=_AUTOMATION_LAB_HINT,
                proposal_needed=True,
            )
        return BuildPlanOk(
            plan=_base_plan(
                plan_id=plan_id,
                agent=agent,
                summary=msg,
                tool="sabnzbd_queue",
                args={},
                desc="Read SABnzbd download queue status (lookup only until approved and executed).",
            )
        )

    movie_title = _extract_media_title_movie(msg)
    if movie_title:
        if "radarr_search" not in installed_tool_names:
            return BuildMissingCapability(
                reason_code="tool_not_installed",
                detail="radarr_search is not installed in the registry.",
                hint=_AUTOMATION_LAB_HINT,
                proposal_needed=True,
            )
        return BuildPlanOk(
            plan=_base_plan(
                plan_id=plan_id,
                agent=agent,
                summary=msg,
                tool="radarr_search",
                args={"title": movie_title},
                desc="Search Radarr catalog for a movie title (lookup only until approved and executed).",
            )
        )

    series_title = _extract_media_title_series(msg)
    if series_title:
        if "sonarr_search" not in installed_tool_names:
            return BuildMissingCapability(
                reason_code="tool_not_installed",
                detail="sonarr_search is not installed in the registry.",
                hint=_AUTOMATION_LAB_HINT,
                proposal_needed=True,
            )
        return BuildPlanOk(
            plan=_base_plan(
                plan_id=plan_id,
                agent=agent,
                summary=msg,
                tool="sonarr_search",
                args={"title": series_title},
                desc="Search Sonarr catalog for a series title (lookup only until approved and executed).",
            )
        )

    return BuildMissingCapability(
        reason_code="unsupported_message_pattern",
        detail="No deterministic media_agent plan mapping for this message.",
        hint=(
            "Try explicit phrasing such as 'search for movie <title>', "
            "'search for series <title>', or SABnzbd queue/status wording; "
            "or use Automation Lab for broader capability proposals."
        ),
        proposal_needed=True,
    )


def build_plan_from_message(
    *,
    message: str,
    agent: str,
    plan_id: str,
    installed_tool_names: set[str],
) -> BuildFromMessageResult:
    """
    Build a single-step pending proposal plan, or return a structured non-plan outcome.

    ``installed_tool_names`` must be the set of registry tool names with
    ``status == installed`` (caller supplies ``main._installed_tool_names()``).
    """
    agent_clean = (agent or "").strip()
    if agent_clean not in _SUPPORTED_AGENTS:
        return BuildUnsupportedAgent(
            agent=agent_clean,
            detail=(
                f"Unsupported agent for /plans/from-message: {agent_clean!r}. "
                f"Supported agents: {', '.join(sorted(_SUPPORTED_AGENTS))}."
            ),
        )

    if agent_clean == MAINTAINER_AGENT:
        return _build_maintainer_plan(
            message=message,
            agent=agent_clean,
            plan_id=plan_id,
            installed_tool_names=installed_tool_names,
        )
    return _build_media_plan(
        message=message,
        agent=agent_clean,
        plan_id=plan_id,
        installed_tool_names=installed_tool_names,
    )
