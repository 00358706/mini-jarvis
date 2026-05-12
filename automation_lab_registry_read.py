"""
Read-only inspection of gateway tool registry for Automation Lab artifacts.

This module calls registry query APIs only (e.g. ``registry.all_tools()``).
It must not call propose, approve, install, reject, tools.execute, or sandbox.

Automation Lab imports this module indirectly so ``automation_lab.py`` stays free
of direct ``registry`` imports (see test guardrails).
"""

from __future__ import annotations

import re
from typing import Any

import registry
from models import ToolDefinition


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.lower())}


def infer_tool_domain(tool: ToolDefinition) -> str | None:
    """Advisory domain label derived from tool name and permissions."""
    n = tool.name.lower()
    perms = " ".join(tool.permissions).lower()
    if "radarr" in n or "radarr" in perms:
        return "media_stack"
    if "sonarr" in n or "sonarr" in perms:
        return "media_stack"
    if "sabnzbd" in n or "sabnzbd" in perms:
        return "media_stack"
    if n in ("inspect_file", "list_project_files", "search_repo", "propose_patch"):
        return "project_maintenance"
    if "file:" in perms:
        return "project_maintenance"
    return None


def summarize_input_schema(schema: dict[str, Any]) -> str:
    if not schema:
        return "empty_schema"
    keys = list(schema.keys())
    if len(keys) > 16:
        return f"fields({len(keys)}): {', '.join(keys[:16])}, …"
    return "fields: " + ", ".join(keys)


def infer_side_effects_from_permissions(tool: ToolDefinition) -> list[str]:
    """Advisory side-effect hints from permission strings; not enforcement."""
    out: list[str] = []
    perms = " ".join(tool.permissions).lower()
    if "file:read" in perms or "file:list" in perms or "file:search" in perms:
        out.append("filesystem_read")
    if "file:proposal" in perms:
        out.append("filesystem_read")
        out.append("proposal_artifact")
    if "file:write" in perms or "write" in perms:
        out.append("filesystem_write")
    if any(x in perms for x in (":read", "read")) and "file:" in perms:
        if "filesystem_read" not in out:
            out.append("filesystem_read")
    if any(
        x in perms
        for x in (
            "radarr:write",
            "sonarr:write",
            "sabnzbd:write",
        )
    ):
        out.append("network_write")
        out.append("external_mutation")
    if any(x in perms for x in ("radarr:read", "sonarr:read", "sabnzbd:read")):
        out.append("network_read")
    if not out:
        out.append("none")
    return sorted(set(out))


def infer_risk_level(tool: ToolDefinition) -> str:
    """Coarse advisory risk bucket for review; policy/sandbox remain enforcement."""
    effects = infer_side_effects_from_permissions(tool)
    perms = " ".join(tool.permissions).lower()
    if "external_mutation" in effects or "network_write" in effects:
        return "level_3"
    if "network_read" in effects or "radarr" in perms or "sonarr" in perms or "sabnzbd" in perms:
        return "level_2"
    if tool.name == "propose_patch":
        return "level_1"
    return "level_0"


def serialize_tool_evidence(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "tool_name": tool.name,
        "version": tool.version,
        "status": tool.status,
        "domain_inferred": infer_tool_domain(tool),
        "description": tool.description,
        "endpoint": tool.endpoint,
        "input_schema_summary": summarize_input_schema(tool.input_schema),
        "permissions": list(tool.permissions),
        "registry_key": f"{tool.name}:{tool.version}",
        "side_effects_inferred": infer_side_effects_from_permissions(tool),
        "risk_level_inferred": infer_risk_level(tool),
    }


def score_tool(message: str, classification_domain: str, tool: ToolDefinition) -> tuple[float, list[str]]:
    """Deterministic relevance score in [0, 1] with human-readable reasons."""
    reasons: list[str] = []
    msg_kw = _keywords(message)
    hay = f"{tool.name} {tool.description} {' '.join(tool.permissions)}".lower()
    score = 0.0
    for kw in msg_kw:
        if kw in hay:
            score += 0.11
            reasons.append(f"keyword:{kw}")
    if tool.name.lower() in message.lower():
        score += 0.38
        reasons.append("tool_name_in_message")
    tdom = infer_tool_domain(tool)
    if classification_domain == "media_stack" and tdom == "media_stack":
        score += 0.28
        reasons.append("domain_alignment:media_stack")
    if classification_domain == "project_maintenance" and tdom == "project_maintenance":
        score += 0.26
        reasons.append("domain_alignment:project_maintenance")
    if classification_domain == "navidrome":
        if "navidrome" in hay:
            score += 0.45
            reasons.append("navidrome_catalog_token")
    return min(round(score, 4), 1.0), reasons


def _compose_pair_in_top(
    ranked_names: list[str],
    a: str,
    b: str,
) -> bool:
    top = set(ranked_names[:6])
    return a in top and b in top


def perform_registry_capability_lookup(
    message: str,
    classification: dict[str, Any],
) -> dict[str, Any]:
    """
    Read-only registry pass. Returns advisory match rows and optional primary outcome.
    """
    domain = str(classification.get("domain", "general"))
    tools = registry.all_tools()
    scored: list[tuple[float, ToolDefinition, list[str]]] = []
    for t in tools:
        s, reasons = score_tool(message, domain, t)
        if s >= 0.05:
            scored.append((s, t, reasons))
    scored.sort(key=lambda x: (-x[0], x[1].name))

    ranked_names = [t.name for _, t, _ in scored[:12]]

    registry_matches: list[dict[str, Any]] = []
    for _rank, (s, tool, reasons) in enumerate(scored[:12]):
        kind = "no_registry_match"
        if tool.status == "installed":
            if s >= 0.42:
                kind = "installed_capability_match"
            elif s >= 0.06:
                kind = "reuse_extension_candidate"
        elif tool.status in ("proposed", "approved"):
            if s >= 0.22:
                kind = "non_installed_registry_match"
            elif s >= 0.06:
                kind = "reuse_extension_candidate"

        row = {
            "match_kind": kind,
            "confidence": s,
            "match_reason": "deterministic_score: " + "; ".join(reasons) if reasons else "low_signal",
            **serialize_tool_evidence(tool),
        }
        registry_matches.append(row)

    duplicate_risk_top = False
    if len(scored) >= 2:
        s0, t0, _ = scored[0]
        s1, t1, _ = scored[1]
        if (
            t0.status == "installed"
            and t1.status == "installed"
            and s0 >= 0.35
            and s1 >= 0.32
            and abs(s0 - s1) <= 0.14
        ):
            duplicate_risk_top = True
            overlap = {t0.name, t1.name}
            for row in registry_matches:
                if row["tool_name"] in overlap:
                    row["match_kind"] = "duplicate_risk_candidate"

    if not registry_matches and tools:
        for t in sorted(tools, key=lambda x: (0 if x.status == "installed" else 1, x.name))[:20]:
            registry_matches.append(
                {
                    "match_kind": "no_registry_match",
                    "confidence": 0.0,
                    "match_reason": "registry_survey_row_no_score_threshold_met",
                    **serialize_tool_evidence(t),
                }
            )

    suggested_primary: str | None = None
    suggested_notes: str = (
        f"Registry read-only pass over {len(tools)} tool definition(s); "
        "scores are advisory for human review."
    )
    suggested_candidates: list[dict[str, Any]] = []

    if scored:
        best_s, best_tool, best_reasons = scored[0]
        ml = message.lower()
        compose_hint = (
            ("review" in ml or "summarize" in ml or "summary" in ml)
            and _compose_pair_in_top(ranked_names, "search_repo", "inspect_file")
        )
        sr_score = next((s for s, t, _ in scored if t.name == "search_repo"), 0.0)
        ic_score = next((s for s, t, _ in scored if t.name == "inspect_file"), 0.0)

        if best_s < 0.18:
            suggested_primary = None
            suggested_notes += " No tool met the minimum advisory score threshold; use deterministic or fixture layer."
        elif duplicate_risk_top:
            suggested_primary = "reject_duplicate"
            suggested_notes += (
                " Multiple installed tools show similar advisory scores; treat as duplicate-risk review."
            )
        elif best_tool.status in ("proposed", "approved") and best_s >= 0.28:
            suggested_primary = "reject_duplicate"
            suggested_notes += (
                f" Registry entry `{best_tool.name}` is `{best_tool.status}` (not installed); "
                "avoid proposing a parallel tool without human review."
            )
        elif compose_hint and sr_score >= 0.18 and ic_score >= 0.18:
            suggested_primary = "compose_existing"
            suggested_notes += (
                " Advisory composition: `search_repo` plus `inspect_file` rank highly for this review-style message."
            )
        elif best_tool.status == "installed" and best_s >= 0.42:
            suggested_primary = "reuse_existing"
            suggested_notes += f" Installed tool `{best_tool.name}` is the strongest advisory registry match."
        elif best_tool.status == "installed" and best_s >= 0.22:
            suggested_primary = "extend_existing"
            suggested_notes += (
                f" Installed tool `{best_tool.name}` is a partial match; extension may suffice."
            )
        else:
            suggested_primary = "propose_new"
            suggested_notes += " No installed tool reached a strong reuse threshold; net-new proposal may be justified."

        for s, tool, rsn in scored[:6]:
            if s < 0.12:
                continue
            suggested_candidates.append(
                {
                    "tool_name": tool.name,
                    "registry_status": tool.status,
                    "domain_inferred": infer_tool_domain(tool),
                    "confidence": s,
                    "match_notes": "registry_readonly: " + "; ".join(rsn[:8]),
                }
            )

    return {
        "registry_lookup": {
            "enabled": True,
            "advisory_only": True,
            "registry_read": True,
            "registry_modified": False,
            "tools_inspected_count": len(tools),
            "reader_module": "automation_lab_registry_read",
        },
        "registry_matches": registry_matches,
        "suggested_primary_outcome": suggested_primary,
        "suggested_candidate_tools": suggested_candidates,
        "suggested_lookup_notes": suggested_notes,
    }


def registry_tool_count_readonly() -> int:
    """Test helper: count of definitions in registry store (read-only query)."""
    return len(registry.all_tools())
