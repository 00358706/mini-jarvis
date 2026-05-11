"""
Proposal-only automation lab artifact generator.

This module writes review artifacts under data/automation_lab/<request_id>/.
It does not import or call gateway runtime modules, registry lifecycle code,
tool implementations, sandbox code, or approval paths. Optional local model
drafting is explicit and advisory only.
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent
AUTOMATION_LAB_ROOT = REPO_ROOT / "data" / "automation_lab"

ALLOWED_CAPABILITY_OUTCOMES = (
    "reuse_existing",
    "extend_existing",
    "compose_existing",
    "propose_new",
    "reject_duplicate",
)

AUTHORITY_BOUNDARY = {
    "proposal_only": True,
    "gateway_remains_authority": True,
    "registry_is_execution_truth": True,
    "model_output_is_proposal_not_authority": True,
    "plans_approved": False,
    "plans_authorized": False,
    "tools_executed": False,
    "sandbox_worker_invoked": False,
    "registry_modified": False,
    "model_called": False,
    "generated_tool_execution_allowed": False,
    "automatic_registry_installation_allowed": False,
}


def authority_boundary(*, model_called: bool = False) -> dict[str, Any]:
    boundary = dict(AUTHORITY_BOUNDARY)
    boundary["model_called"] = model_called
    return boundary


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_request_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"auto_lab_{stamp}_{uuid.uuid4().hex[:8]}"


def validate_request_id(request_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
        raise ValueError("request_id must be 8-80 chars of letters, numbers, '_' or '-'.")
    return request_id


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def classify_message(message: str, *, model_called: bool = False) -> dict[str, Any]:
    lower = message.lower()
    matched_rules: list[str] = []

    tool_terms = ("tool", "integration", "connector", "api", "list", "fetch", "query")
    routine_terms = ("routine", "schedule", "scheduled", "daily", "weekly", "repeat", "recurring")
    agent_terms = ("agent", "persona", "specialist", "assistant")

    if any(term in lower for term in tool_terms) and any(
        term in lower for term in ("create", "add", "build", "make", "new", "navidrome")
    ):
        matched_rules.append("tool_terms_with_creation_intent")
        proposal_kind = "tool_proposal"
        optional_artifact = "TOOL_PROPOSAL.md"
    elif any(term in lower for term in routine_terms):
        matched_rules.append("routine_or_schedule_terms")
        proposal_kind = "routine_proposal"
        optional_artifact = "ROUTINE_PROPOSAL.md"
    elif any(term in lower for term in agent_terms):
        matched_rules.append("agent_terms")
        proposal_kind = "agent_proposal"
        optional_artifact = "AGENT_PROPOSAL.md"
    else:
        matched_rules.append("default_review_only")
        proposal_kind = "review_only"
        optional_artifact = None

    domain = "general"
    if "navidrome" in lower:
        domain = "navidrome"
        matched_rules.append("domain_navidrome")
    elif "repo" in lower or "project" in lower or "file" in lower:
        domain = "project_maintenance"
        matched_rules.append("domain_project_maintenance")
    elif "radarr" in lower or "sonarr" in lower or "sabnzbd" in lower:
        domain = "media_stack"
        matched_rules.append("domain_media_stack")

    return {
        "schema_version": "automation-lab-classification.v1",
        "proposal_kind": proposal_kind,
        "optional_artifact": optional_artifact,
        "domain": domain,
        "deterministic": True,
        "matched_rules": matched_rules,
        "authority_boundary": authority_boundary(model_called=model_called),
    }


def capability_id_for(message: str, classification: dict[str, Any]) -> str:
    domain = classification["domain"]
    if domain == "navidrome":
        return "navidrome.releases.list_new"
    if domain == "project_maintenance":
        return "repo.review.proposal"
    if domain == "media_stack":
        return "media.stack.review"
    if classification["proposal_kind"] == "routine_proposal":
        return "routine.workflow.repeatable"
    if classification["proposal_kind"] == "agent_proposal":
        return "agent.context.proposal"
    words = re.findall(r"[a-z0-9]+", message.lower())
    suffix = "_".join(words[:4]) if words else "general"
    return f"automation_lab.{suffix}"


def build_capability_matches(
    message: str,
    request_id: str,
    classification: dict[str, Any],
    *,
    model_called: bool = False,
) -> dict[str, Any]:
    proposal_kind = classification["proposal_kind"]
    domain = classification["domain"]

    if proposal_kind == "tool_proposal":
        primary_outcome = "propose_new"
        missing_action = "propose_tool"
        candidate_tools: list[dict[str, Any]] = []
        lookup_notes = (
            "Deterministic spike lookup records no matching installed tool metadata. "
            "No registry module or registry lifecycle path was imported or mutated."
        )
        if domain == "project_maintenance":
            primary_outcome = "extend_existing"
            candidate_tools = [
                {
                    "tool_name": "search_repo",
                    "match_notes": "Static known tool name for repository search; extension may be enough.",
                }
            ]
            lookup_notes = "Static spike lookup found a project-maintainer candidate by template."
    elif proposal_kind == "routine_proposal":
        primary_outcome = "compose_existing"
        missing_action = "propose_routine_update"
        candidate_tools = []
        lookup_notes = "Routine proposal can usually compose existing proposal/review flows."
    elif proposal_kind == "agent_proposal":
        primary_outcome = "reuse_existing"
        missing_action = "propose_agent"
        candidate_tools = []
        lookup_notes = "Agent proposal is context/configuration only; no new tool is implied."
    else:
        primary_outcome = "reuse_existing"
        missing_action = "stop"
        candidate_tools = []
        lookup_notes = "Review-only request; no tool proposal is implied."

    considered = []
    for outcome in ALLOWED_CAPABILITY_OUTCOMES:
        selected = outcome == primary_outcome
        considered.append(
            {
                "outcome": outcome,
                "selected": selected,
                "notes": outcome_note(outcome, primary_outcome, proposal_kind),
            }
        )

    return {
        "schema_version": "automation-lab-capability-matches.v1",
        "request_id": request_id,
        "source": "deterministic_template_no_registry_read",
        "allowed_outcomes": list(ALLOWED_CAPABILITY_OUTCOMES),
        "primary_outcome": primary_outcome,
        "outcomes_considered": considered,
        "candidate_tools": candidate_tools,
        "capability_ids": [capability_id_for(message, classification)],
        "lookup_notes": lookup_notes,
        "missing_capability_behavior": {
            "action": missing_action,
            "generated_tool_execution_allowed": False,
        },
        "authority_boundary": authority_boundary(model_called=model_called),
    }


def outcome_note(outcome: str, primary_outcome: str, proposal_kind: str) -> str:
    if outcome == primary_outcome:
        return f"Selected by deterministic {proposal_kind} template."
    if outcome == "reuse_existing":
        return "Considered first; not selected when the request asks for a missing or changed capability."
    if outcome == "extend_existing":
        return "Considered before proposing anything net-new."
    if outcome == "compose_existing":
        return "Considered before proposing a standalone tool."
    if outcome == "reject_duplicate":
        return "Considered as a stop condition for overlapping capabilities."
    return "Considered by allowed capability outcome list."


def review_summary_markdown(
    message: str,
    request_id: str,
    classification: dict[str, Any],
    capability_matches: dict[str, Any],
    artifacts: list[str],
    *,
    model_enabled: bool = False,
    model_validation: dict[str, Any] | None = None,
) -> str:
    artifact_lines = "\n".join(f"- `{name}`" for name in artifacts)
    model_state = "disabled"
    if model_enabled:
        state = "unknown"
        if model_validation:
            state = str(model_validation.get("validation_state", "unknown"))
        model_state = f"enabled ({state})"
    return f"""# Automation Lab Review Summary

Request id: `{request_id}`

Message:
```text
{message}
```

Classification: `{classification["proposal_kind"]}`

Primary capability outcome: `{capability_matches["primary_outcome"]}`

Local model draft: `{model_state}`

Artifacts:
{artifact_lines}

Authority boundary:
- Proposal-only: true
- Gateway remains authority: true
- Registry remains source of truth for installed tools: true
- Model output remains proposal, not authority: true
- Plans approved: false
- Plans authorized: false
- Tools executed: false
- Sandbox worker invoked: false
- Registry modified: false
- Model called: {str(model_enabled).lower()}
- Generated tool execution allowed: false

Reviewer notes:
- This folder is review evidence only.
- Capability outcomes are advisory and must not bypass policy, authorization, registry/schema validation, or sandbox execution.
- Any future implementation must use a separate reviewed branch and normal gateway enforcement.
"""


def tool_proposal_markdown(
    message: str,
    request_id: str,
    capability_matches: dict[str, Any],
) -> str:
    capability_ids = ", ".join(f"`{cap}`" for cap in capability_matches["capability_ids"])
    return f"""# Tool Proposal Draft

Proposal id: `{request_id}_tool`

Status: `draft`

Source request: `{request_id}`

Stated need:
```text
{message}
```

Capability ids:
{capability_ids}

Capability lookup:
- Primary outcome: `{capability_matches["primary_outcome"]}`
- Lookup source: `{capability_matches["source"]}`
- `reuse_existing`, `extend_existing`, `compose_existing`, and `reject_duplicate` were considered before this draft.

Risk and side effects:
- risk_level: `level_2`
- side_effects: `network_read`
- network_access: `local`
- destructive: false
- costly: false

Implementation plan:
- Draft a normal tool proposal following `docs/TOOL_PROPOSAL_SCHEMA.md`.
- Review duplicate/overlap risk with capability metadata.
- Implement only in a future branch after human review.
- Install manually only after tests and review.

Test plan:
- Unit tests for argument validation.
- Integration tests against mocked local service responses.
- Manual checklist before any registry install.

Review outcome:
- decision: null
- generated_tool_execution_allowed: false
- automatic_registry_installation_allowed: false
- model_driven_tool_installation_allowed: false

Authority boundary:
This draft is a review artifact only. It is not a registry entry, not approval, not authorization, and not execution permission.
"""


def routine_proposal_markdown(
    message: str,
    request_id: str,
    capability_matches: dict[str, Any],
) -> str:
    capability_ids = ", ".join(f"`{cap}`" for cap in capability_matches["capability_ids"])
    return f"""# Routine Proposal Draft

Routine id: `{request_id}_routine`

Status: `draft`

Goal:
```text
{message}
```

Required capabilities:
{capability_ids}

Missing capability behavior:
- action: `{capability_matches["missing_capability_behavior"]["action"]}`
- generated_tool_execution_allowed: false

Authority boundary:
This routine draft is a repeatable workflow definition proposal only. It cannot approve, authorize, install, or execute tools.
"""


def agent_proposal_markdown(message: str, request_id: str) -> str:
    return f"""# Agent Proposal Draft

Agent id: `{request_id}_agent`

Status: `draft`

Purpose:
```text
{message}
```

Authority boundary:
Agents are folders/configuration only. This proposal cannot run services, execute tools, approve plans, authorize plans, or bypass gateway enforcement.
"""


def generate(
    message: str,
    request_id: str | None = None,
    *,
    use_local_model: bool = False,
    model_base_url: str = "http://127.0.0.1:10000/v1",
    model_name: str = "local-model",
    strict_model: bool = False,
) -> dict[str, Any]:
    if not message or not message.strip():
        raise ValueError("Message is required.")

    rid = validate_request_id(request_id) if request_id else make_request_id()
    root = AUTOMATION_LAB_ROOT / rid
    if root.exists():
        raise FileExistsError(f"Automation lab request already exists: {root}")
    root.mkdir(parents=True)

    created_at = utc_now()
    classification = classify_message(message, model_called=use_local_model)
    capability_matches = build_capability_matches(
        message,
        rid,
        classification,
        model_called=use_local_model,
    )
    boundary = authority_boundary(model_called=use_local_model)

    request_payload = {
        "schema_version": "automation-lab-request.v1",
        "request_id": rid,
        "message": message,
        "source_client": "scripts/automation_lab_propose.ps1",
        "created_at": created_at,
        "local_model": {
            "enabled": use_local_model,
            "base_url": model_base_url if use_local_model else None,
            "model_name": model_name if use_local_model else None,
            "strict_model": strict_model,
            "tool_calling_enabled": False,
        },
        "authority_boundary": boundary,
    }

    artifacts = [
        "REQUEST.json",
        "CLASSIFICATION.json",
        "CAPABILITY_MATCHES.json",
        "REVIEW_SUMMARY.md",
    ]

    write_json(root / "REQUEST.json", request_payload)
    classification_payload = {
        **classification,
        "request_id": rid,
        "created_at": created_at,
    }
    write_json(root / "CLASSIFICATION.json", classification_payload)
    write_json(root / "CAPABILITY_MATCHES.json", capability_matches)

    optional_artifact = classification["optional_artifact"]
    if optional_artifact == "TOOL_PROPOSAL.md":
        write_text(root / optional_artifact, tool_proposal_markdown(message, rid, capability_matches))
        artifacts.append(optional_artifact)
    elif optional_artifact == "ROUTINE_PROPOSAL.md":
        write_text(root / optional_artifact, routine_proposal_markdown(message, rid, capability_matches))
        artifacts.append(optional_artifact)
    elif optional_artifact == "AGENT_PROPOSAL.md":
        write_text(root / optional_artifact, agent_proposal_markdown(message, rid))
        artifacts.append(optional_artifact)

    model_validation: dict[str, Any] | None = None
    if use_local_model:
        from local_model_adapter import draft_with_local_model

        model_result = draft_with_local_model(
            message=message,
            classification=classification,
            capability_matches=capability_matches,
            base_url=model_base_url,
            model_name=model_name,
        )
        model_request = {
            "schema_version": "automation-lab-model-request.v1",
            "request_id": rid,
            "adapter_id": "automation_lab_openai_compatible_local",
            "runtime_type": "openai_compatible_local",
            "base_url": model_base_url,
            "model_name": model_name,
            "strict_model": strict_model,
            "tool_calling_enabled": False,
            "generated_tool_execution_allowed": False,
            "request_payload": model_result.request,
            "authority_boundary": boundary,
        }
        model_response = {
            "schema_version": "automation-lab-model-response.v1",
            "request_id": rid,
            "advisory_only": True,
            "response": model_result.response,
            "authority_boundary": boundary,
        }
        model_validation = {
            **model_result.validation,
            "request_id": rid,
            "strict_model": strict_model,
            "model_output_is_proposal_not_authority": True,
            "authority_boundary": boundary,
        }

        write_json(root / "MODEL_REQUEST.json", model_request)
        write_json(root / "MODEL_RESPONSE.json", model_response)
        write_json(root / "MODEL_VALIDATION.json", model_validation)
        write_text(root / "MODEL_DRAFT.md", model_result.draft_markdown)
        artifacts.extend(
            [
                "MODEL_REQUEST.json",
                "MODEL_RESPONSE.json",
                "MODEL_VALIDATION.json",
                "MODEL_DRAFT.md",
            ]
        )

    write_text(
        root / "REVIEW_SUMMARY.md",
        review_summary_markdown(
            message,
            rid,
            classification,
            capability_matches,
            artifacts,
            model_enabled=use_local_model,
            model_validation=model_validation,
        ),
    )

    if strict_model and model_validation and not model_validation.get("valid"):
        raise RuntimeError(
            f"Strict local model mode failed validation; review artifacts were written to {root}"
        )

    return {
        "status": "created",
        "request_id": rid,
        "output_dir": str(root.relative_to(REPO_ROOT)).replace("\\", "/"),
        "output_dir_abs": str(root),
        "artifacts": artifacts,
        "proposal_kind": classification["proposal_kind"],
        "primary_capability_outcome": capability_matches["primary_outcome"],
        "local_model": {
            "enabled": use_local_model,
            "validation_state": (
                model_validation.get("validation_state") if model_validation else "not_requested"
            ),
        },
        "authority_boundary": boundary,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create proposal-only automation lab artifacts.")
    parser.add_argument("--message", required=True, help="User request to classify and draft.")
    parser.add_argument("--request-id", default=None, help="Optional safe request id for tests/review.")
    parser.add_argument("--use-local-model", action="store_true", help="Attempt optional local model drafting.")
    parser.add_argument(
        "--model-base-url",
        default="http://127.0.0.1:10000/v1",
        help="OpenAI-compatible local API base URL.",
    )
    parser.add_argument("--model-name", default="local-model", help="Local model name/id.")
    parser.add_argument(
        "--strict-model",
        action="store_true",
        help="Fail the CLI if optional model drafting fails validation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = generate(
        args.message,
        args.request_id,
        use_local_model=args.use_local_model,
        model_base_url=args.model_base_url,
        model_name=args.model_name,
        strict_model=args.strict_model,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
