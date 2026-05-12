"""
Deterministic advisory capability match scoring for Automation Lab.

Merges evidence from deterministic_template, registry_readonly, and optional
static_fixture layers. Does not import registry, sandbox, or tools execution.
"""

from __future__ import annotations

from typing import Any

ALLOWED_CAPABILITY_OUTCOMES = (
    "reuse_existing",
    "extend_existing",
    "compose_existing",
    "propose_new",
    "reject_duplicate",
)

# Lane scores are 0–100 integers for stable comparisons and human review.
_OUTCOME_BASE: dict[str, int] = {
    "reuse_existing": 62,
    "extend_existing": 58,
    "compose_existing": 60,
    "reject_duplicate": 64,
    "propose_new": 48,
}


def missing_action_for_outcome(outcome: str, proposal_kind: str) -> str:
    if outcome in ("reuse_existing", "reject_duplicate"):
        return "stop"
    if outcome == "extend_existing":
        return "propose_tool_update"
    if outcome == "compose_existing":
        return "propose_composition_review"
    if proposal_kind == "routine_proposal":
        return "propose_routine_update"
    if proposal_kind == "agent_proposal":
        return "propose_agent"
    return "propose_tool"


def outcome_note(outcome: str, primary_outcome: str, proposal_kind: str) -> str:
    if outcome == primary_outcome:
        return f"Selected by deterministic scoring merge ({proposal_kind})."
    if outcome == "reuse_existing":
        return "Considered first; not selected when the request asks for a missing or changed capability."
    if outcome == "extend_existing":
        return "Considered before proposing anything net-new."
    if outcome == "compose_existing":
        return "Considered before proposing a standalone tool."
    if outcome == "reject_duplicate":
        return "Considered as a stop condition for overlapping capabilities."
    return "Considered by allowed capability outcome list."


def build_outcomes_considered(
    primary_outcome: str,
    proposal_kind: str,
    *,
    selected_note: str | None = None,
) -> list[dict[str, Any]]:
    considered = []
    for outcome in ALLOWED_CAPABILITY_OUTCOMES:
        selected = outcome == primary_outcome
        note = selected_note if selected and selected_note else outcome_note(
            outcome,
            primary_outcome,
            proposal_kind,
        )
        considered.append(
            {
                "outcome": outcome,
                "selected": selected,
                "notes": note,
            }
        )
    return considered


def _lane_score_deterministic(outcome: str, proposal_kind: str) -> tuple[int, dict[str, Any]]:
    base = _OUTCOME_BASE.get(outcome, 45)
    bonus = 8 if proposal_kind == "tool_proposal" else 0
    if proposal_kind == "routine_proposal":
        bonus = 6
    if proposal_kind == "agent_proposal":
        bonus = 4
    total = min(100, base + bonus)
    return total, {
        "outcome": outcome,
        "base_outcome_weight": base,
        "proposal_kind_bonus": bonus,
    }


def _lane_score_registry(
    outcome: str | None,
    *,
    best_confidence: float,
    best_match_kind: str | None,
    best_tool_name: str | None,
    installed: bool,
) -> tuple[int, dict[str, Any]]:
    if not outcome:
        return 0, {"outcome": None, "reason": "no_registry_recommendation"}
    base = _OUTCOME_BASE.get(outcome, 45)
    conf_pts = int(min(40, round(best_confidence * 85)))
    installed_bonus = 22 if installed and best_match_kind == "installed_capability_match" else 0
    if installed and best_match_kind == "reuse_extension_candidate":
        installed_bonus = 12
    if installed and best_match_kind == "duplicate_risk_candidate":
        installed_bonus = 18
    total = min(100, base + conf_pts + installed_bonus)
    return total, {
        "outcome": outcome,
        "base_outcome_weight": base,
        "confidence_points": conf_pts,
        "best_confidence": round(best_confidence, 4),
        "best_tool_name": best_tool_name,
        "best_match_kind": best_match_kind,
        "installed_execution_truth": installed,
        "installed_signal_bonus": installed_bonus,
    }


def _lane_score_fixture(
    outcome: str | None,
    matched_terms: list[str],
) -> tuple[int, dict[str, Any]]:
    if not outcome:
        return 0, {"outcome": None, "reason": "no_fixture_match"}
    base = _OUTCOME_BASE.get(outcome, 45)
    term_pts = min(28, len(matched_terms) * 7)
    total = min(100, base + term_pts)
    return total, {
        "outcome": outcome,
        "base_outcome_weight": base,
        "matched_term_count": len(matched_terms),
        "matched_term_points": term_pts,
    }


def _registry_best_installed_signal(registry_matches: list[dict[str, Any]]) -> tuple[float, str | None, str | None]:
    best_c = 0.0
    best_name: str | None = None
    best_kind: str | None = None
    for row in registry_matches:
        if str(row.get("status")) != "installed":
            continue
        mk = str(row.get("match_kind") or "")
        if mk not in ("installed_capability_match", "reuse_extension_candidate", "duplicate_risk_candidate"):
            continue
        c = float(row.get("confidence") or 0.0)
        if c > best_c:
            best_c = c
            best_name = str(row.get("tool_name") or "") or None
            best_kind = mk or None
    return best_c, best_name, best_kind


def _strong_installed_registry(
    registry_outcome: str | None,
    best_confidence: float,
    best_match_kind: str | None,
) -> bool:
    if not registry_outcome or registry_outcome == "propose_new":
        return False
    if best_confidence < 0.42:
        return False
    if best_match_kind not in ("installed_capability_match", "duplicate_risk_candidate"):
        return False
    return True


def finalize_capability_scoring(
    matches: dict[str, Any],
    classification: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    """
    Populate scoring, conflicts, and final primary_outcome / source fields.
    Expects deterministic_layer, registry_layer (optional), fixture_layer (optional),
    registry_matches, and evidence_sources from earlier pipeline steps.
    """
    _ = message  # reserved for future scoring signals
    out = dict(matches)
    proposal_kind = str(classification.get("proposal_kind", "review_only"))

    det_layer = out.get("deterministic_layer")
    if not isinstance(det_layer, dict):
        det_out = str(out.get("primary_outcome") or "reuse_existing")
        det_notes = str(out.get("lookup_notes") or "")
    else:
        det_out = str(det_layer.get("recommended_outcome") or out.get("primary_outcome"))
        det_notes = str(det_layer.get("lookup_notes") or "")

    reg_layer = out.get("registry_layer") if isinstance(out.get("registry_layer"), dict) else {}
    reg_out = reg_layer.get("recommended_outcome")
    reg_out = str(reg_out) if isinstance(reg_out, str) else None

    reg_matches = out.get("registry_matches") if isinstance(out.get("registry_matches"), list) else []
    best_c, best_tool, best_mk = _registry_best_installed_signal(reg_matches)
    reg_installed_for_lane = bool(best_tool and best_c >= 0.05)

    fx_layer = out.get("fixture_layer") if isinstance(out.get("fixture_layer"), dict) else {}
    fx_out = fx_layer.get("recommended_outcome")
    fx_out = str(fx_out) if isinstance(fx_out, str) else None
    fx_terms = fx_layer.get("matched_terms") if isinstance(fx_layer.get("matched_terms"), list) else []
    fx_terms_s = [str(t) for t in fx_terms]

    det_score, det_br = _lane_score_deterministic(det_out, proposal_kind)
    reg_score, reg_br = _lane_score_registry(
        reg_out,
        best_confidence=best_c,
        best_match_kind=best_mk,
        best_tool_name=best_tool,
        installed=reg_installed_for_lane,
    )
    fx_score, fx_br = _lane_score_fixture(fx_out, fx_terms_s)

    score_breakdown: dict[str, Any] = {
        "deterministic_template": {"lane_score": det_score, **det_br},
        "registry_readonly": {"lane_score": reg_score, **reg_br},
        "static_fixture": {"lane_score": fx_score, **fx_br},
    }

    conflicts: list[dict[str, Any]] = []
    precedence_applied = "deterministic_only"
    recommended_outcome = det_out
    recommendation_reason = (
        f"Deterministic template outcome `{det_out}`; no stronger registry or fixture layer."
    )
    primary_source = "deterministic_template"

    strong_reg = _strong_installed_registry(reg_out, best_c, best_mk)

    if fx_out and reg_out and fx_out != reg_out:
        if (
            reg_out == "reject_duplicate"
            and fx_out in ("reuse_existing", "compose_existing", "extend_existing")
        ):
            conflicts.append(
                {
                    "conflict_id": "fixture_over_registry_duplicate_risk_heuristic",
                    "summary": (
                        f"Registry duplicate-risk heuristic suggested `{reg_out}`; "
                        f"matched static fixture `{fx_layer.get('fixture_id')}` recommends `{fx_out}`."
                    ),
                    "registry_recommended_outcome": reg_out,
                    "fixture_recommended_outcome": fx_out,
                    "fixture_id": fx_layer.get("fixture_id"),
                    "resolution": (
                        "Primary outcome follows static fixture for curated demo/review; "
                        "registry_matches still show duplicate-risk rows for human review."
                    ),
                    "advisory_only": True,
                }
            )
            recommended_outcome = fx_out
            recommendation_reason = (
                "Precedence: explicit static fixture reuse/compose path overrides registry "
                "`reject_duplicate` heuristic (advisory duplicate-risk only)."
            )
            precedence_applied = "fixture_over_registry_duplicate_risk_heuristic"
            primary_source = "static_fixture"
        elif strong_reg and fx_out == "propose_new" and reg_out != "propose_new":
            conflicts.append(
                {
                    "conflict_id": "registry_strong_installed_vs_fixture_propose_new",
                    "summary": (
                        f"Registry read-only signal favors `{reg_out}` for installed tool "
                        f"`{best_tool}` (confidence={round(best_c, 4)}, match_kind={best_mk}); "
                        f"static fixture `{fx_layer.get('fixture_id')}` selected `{fx_out}`."
                    ),
                    "registry_recommended_outcome": reg_out,
                    "fixture_recommended_outcome": fx_out,
                    "fixture_id": fx_layer.get("fixture_id"),
                    "resolution": (
                        "Primary outcome follows registry_metadata (strong installed signal); "
                        "fixture recommendation preserved in fixture_alternate_recommendation."
                    ),
                    "advisory_only": True,
                }
            )
            recommended_outcome = reg_out
            recommendation_reason = (
                "Precedence: registry strong installed match outranks static fixture `propose_new` "
                f"(tool={best_tool}, confidence={round(best_c, 4)})."
            )
            precedence_applied = "registry_strong_installed_over_fixture_propose_new"
            primary_source = "registry_metadata"
        elif reg_score >= fx_score + 8 and reg_out:
            recommended_outcome = reg_out
            recommendation_reason = (
                f"Registry lane score ({reg_score}) exceeds fixture lane ({fx_score}) by margin; "
                "layers disagree — registry preferred."
            )
            precedence_applied = "registry_score_over_fixture"
            primary_source = "registry_metadata"
            conflicts.append(
                {
                    "conflict_id": "registry_vs_fixture_score",
                    "summary": f"Registry outcome `{reg_out}` vs fixture `{fx_out}`; scores reg={reg_score} fx={fx_score}.",
                    "registry_recommended_outcome": reg_out,
                    "fixture_recommended_outcome": fx_out,
                    "fixture_id": fx_layer.get("fixture_id"),
                    "resolution": "Primary outcome follows higher-scoring registry lane.",
                    "advisory_only": True,
                }
            )
        elif fx_out:
            recommended_outcome = fx_out
            recommendation_reason = (
                f"Static fixture matched with outcome `{fx_out}`; registry lane did not override "
                f"(reg_score={reg_score}, fx_score={fx_score}, strong_installed={strong_reg})."
            )
            precedence_applied = "fixture_when_registry_weaker_or_equal"
            primary_source = "static_fixture"
            if reg_out and reg_out != fx_out:
                conflicts.append(
                    {
                        "conflict_id": "fixture_over_registry_no_strong_override",
                        "summary": (
                            f"Fixture chose `{fx_out}` while registry suggested `{reg_out}`; "
                            "no strong installed override rule fired."
                        ),
                        "registry_recommended_outcome": reg_out,
                        "fixture_recommended_outcome": fx_out,
                        "fixture_id": fx_layer.get("fixture_id"),
                        "resolution": "Primary outcome follows fixture; registry evidence remains in registry_matches.",
                        "advisory_only": True,
                    }
                )
    elif fx_out and reg_out and fx_out == reg_out:
        recommended_outcome = reg_out
        recommendation_reason = (
            f"Registry and static fixture agree on `{reg_out}` (reg_score={reg_score}, fx_score={fx_score})."
        )
        precedence_applied = "registry_and_fixture_agree"
        primary_source = "registry_metadata"
    elif reg_out:
        recommended_outcome = reg_out
        recommendation_reason = (
            f"Registry read-only recommendation `{reg_out}` "
            f"(best installed signal: tool={best_tool}, confidence={round(best_c, 4)})."
        )
        precedence_applied = "registry_only"
        primary_source = "registry_metadata"
        if reg_out != det_out:
            conflicts.append(
                {
                    "conflict_id": "registry_vs_deterministic_template",
                    "summary": f"Deterministic `{det_out}` vs registry `{reg_out}`.",
                    "deterministic_outcome": det_out,
                    "registry_recommended_outcome": reg_out,
                    "resolution": "Primary outcome follows registry_metadata.",
                    "advisory_only": True,
                }
            )
    elif fx_out:
        recommended_outcome = fx_out
        recommendation_reason = f"Static fixture only (`{fx_out}`); registry had no recommendation."
        precedence_applied = "fixture_only"
        primary_source = "static_fixture"
        if fx_out != det_out:
            conflicts.append(
                {
                    "conflict_id": "fixture_vs_deterministic_template",
                    "summary": f"Deterministic `{det_out}` vs fixture `{fx_out}`.",
                    "deterministic_outcome": det_out,
                    "fixture_recommended_outcome": fx_out,
                    "fixture_id": fx_layer.get("fixture_id"),
                    "resolution": "Primary outcome follows fixture.",
                    "advisory_only": True,
                }
            )
    else:
        recommended_outcome = det_out
        recommendation_reason = "No registry or fixture recommendation; deterministic template applies."

    winning_score = det_score
    if primary_source == "registry_metadata":
        winning_score = reg_score
    elif primary_source == "static_fixture":
        winning_score = fx_score

    es = list(out.get("evidence_sources") or [])
    if "capability_scoring" not in es:
        es.append("capability_scoring")

    out["schema_version"] = "automation-lab-capability-matches.v3"
    out["primary_outcome"] = recommended_outcome
    out["primary_outcome_source"] = primary_source
    out["recommended_outcome"] = recommended_outcome
    out["recommendation_reason"] = recommendation_reason
    out["precedence_applied"] = precedence_applied
    out["score"] = int(winning_score)
    out["score_breakdown"] = score_breakdown
    out["conflicts"] = conflicts
    out["evidence_sources"] = es
    out["source"] = "+".join(es)
    fx_meta = out.get("fixture_lookup") if isinstance(out.get("fixture_lookup"), dict) else {}
    fid = fx_meta.get("matched_fixture_id")
    if fid and f"+fixture:{fid}" not in out["source"]:
        out["source"] = f"{out['source']}+fixture:{fid}"

    if fx_out and precedence_applied.startswith("registry_strong") and fx_out != recommended_outcome:
        out["fixture_alternate_recommendation"] = {
            "primary_outcome": fx_out,
            "fixture_id": fx_layer.get("fixture_id"),
            "lookup_notes": fx_layer.get("lookup_notes"),
            "advisory_only": True,
        }
    else:
        out.pop("fixture_alternate_recommendation", None)

    sel_note = recommendation_reason
    if conflicts:
        sel_note += f" ({len(conflicts)} advisory conflict(s) recorded)."
    out["outcomes_considered"] = build_outcomes_considered(
        recommended_outcome,
        proposal_kind,
        selected_note=sel_note[:500],
    )
    out["missing_capability_behavior"] = {
        "action": missing_action_for_outcome(recommended_outcome, proposal_kind),
        "generated_tool_execution_allowed": False,
    }

    out["lookup_notes"] = (f"{det_notes} | scoring: {recommendation_reason}").strip()

    return out
