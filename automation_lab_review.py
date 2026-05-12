"""
Read-only automation lab review summary helper.

This module reads INDEX.json from an existing automation lab run and prints a
compact human-readable summary. It does not import gateway runtime modules,
registry lifecycle code, tool implementations, sandbox code, local model code,
or approval paths.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent
AUTOMATION_LAB_ROOT = REPO_ROOT / "data" / "automation_lab"

RECOMMENDED_ORDER = (
    "INDEX.json",
    "REQUEST.json",
    "CLASSIFICATION.json",
    "CAPABILITY_MATCHES.json",
    "ROUTINE_PROPOSAL.md",
    "TOOL_PROPOSAL.md",
    "AGENT_PROPOSAL.md",
    "MODEL_VALIDATION.json",
    "MODEL_DRAFT.md",
    "MODEL_REQUEST.json",
    "MODEL_RESPONSE.json",
    "REVIEW_SUMMARY.md",
)


def validate_request_id(request_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
        raise ValueError("request_id must be 8-80 chars of letters, numbers, '_' or '-'.")
    return request_id


def resolve_run_dir(*, request_id: str | None, path: str | None) -> Path:
    if bool(request_id) == bool(path):
        raise ValueError("Provide exactly one of --request-id or --path.")

    if request_id:
        rid = validate_request_id(request_id)
        return (AUTOMATION_LAB_ROOT / rid).resolve()

    assert path is not None
    candidate = Path(path.strip())
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    candidate = candidate.resolve()
    if candidate.name == "INDEX.json":
        return candidate.parent
    return candidate


def load_index(run_dir: Path) -> tuple[dict[str, Any], Path]:
    index_path = run_dir / "INDEX.json"
    if not index_path.exists():
        raise FileNotFoundError(f"INDEX.json not found at: {index_path}")
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"INDEX.json is malformed JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("INDEX.json must contain a JSON object.")
    validate_index_payload(payload)
    return payload, index_path


def validate_index_payload(payload: dict[str, Any]) -> None:
    required = (
        "schema_version",
        "request_id",
        "proposal_kind",
        "primary_capability_outcome",
        "local_model",
        "fixture_lookup",
        "authority_boundary",
        "artifacts",
    )
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(f"INDEX.json is missing required fields: {', '.join(missing)}")

    if not isinstance(payload["local_model"], dict):
        raise ValueError("INDEX.json local_model must be an object.")
    if not isinstance(payload["fixture_lookup"], dict):
        raise ValueError("INDEX.json fixture_lookup must be an object.")
    reg = payload.get("registry_capability_lookup")
    if reg is not None and not isinstance(reg, dict):
        raise ValueError("INDEX.json registry_capability_lookup must be an object when present.")
    if not isinstance(payload["authority_boundary"], dict):
        raise ValueError("INDEX.json authority_boundary must be an object.")
    if not isinstance(payload["artifacts"], list):
        raise ValueError("INDEX.json artifacts must be a list.")

    for entry in payload["artifacts"]:
        if not isinstance(entry, dict):
            raise ValueError("Each INDEX.json artifact entry must be an object.")
        for field in ("filename", "kind", "format", "required", "authority"):
            if field not in entry:
                raise ValueError(f"Artifact entry is missing required field: {field}")


def bool_text(value: Any) -> str:
    return "true" if value is True else "false" if value is False else str(value)


def recommended_review_order(artifact_names: set[str]) -> list[str]:
    ordered = [name for name in RECOMMENDED_ORDER if name in artifact_names]
    ordered.extend(sorted(artifact_names - set(ordered)))
    return ordered


def render_summary(index: dict[str, Any], index_path: Path) -> str:
    local_model = index["local_model"]
    fixture_lookup = index["fixture_lookup"]
    reg = index.get("registry_capability_lookup") or {}
    boundary = index["authority_boundary"]
    artifacts = index["artifacts"]
    artifact_names = {str(entry["filename"]) for entry in artifacts}
    all_artifacts_non_authority = all(entry.get("authority") is False for entry in artifacts)

    es = reg.get("evidence_sources")
    if isinstance(es, list):
        es_txt = ",".join(str(x) for x in es)
    elif es is None:
        es_txt = ""
    else:
        es_txt = str(es)
    reg_line = (
        "registry_capability_index: "
        f"enabled={bool_text(reg.get('enabled'))}, "
        f"registry_read={bool_text(reg.get('registry_read'))}, "
        f"tools_inspected_count={reg.get('tools_inspected_count')}, "
        f"primary_outcome_source={reg.get('primary_outcome_source')}, "
        f"evidence_sources={es_txt}"
    )

    lines = [
        "Automation Lab Review Summary",
        f"Review source: {index_path}",
        "",
        f"request_id: {index['request_id']}",
        f"proposal_kind: {index['proposal_kind']}",
        f"primary_capability_outcome: {index['primary_capability_outcome']}",
        "local_model: "
        f"enabled={bool_text(local_model.get('enabled'))}, "
        f"validation_state={local_model.get('validation_state')}",
        "fixture_lookup: "
        f"enabled={bool_text(fixture_lookup.get('enabled'))}, "
        f"source={fixture_lookup.get('source')}",
        reg_line,
        "",
        f"Artifacts ({len(artifacts)}):",
    ]

    for entry in artifacts:
        lines.append(
            "- "
            f"{entry['filename']} "
            f"[kind={entry['kind']}, format={entry['format']}, "
            f"required={bool_text(entry['required'])}, authority={bool_text(entry['authority'])}]"
        )

    lines.extend(["", "Recommended review order:"])
    for index_num, filename in enumerate(recommended_review_order(artifact_names), start=1):
        lines.append(f"{index_num}. {filename}")

    lines.extend(
        [
            "",
            "Authority boundary status:",
            f"- proposal_only: {bool_text(boundary.get('proposal_only'))}",
            f"- tools_executed: {bool_text(boundary.get('tools_executed'))}",
            f"- sandbox_worker_invoked: {bool_text(boundary.get('sandbox_worker_invoked'))}",
            f"- registry_modified: {bool_text(boundary.get('registry_modified'))}",
            "- generated_tool_execution_allowed: "
            f"{bool_text(boundary.get('generated_tool_execution_allowed'))}",
            f"- all_artifacts_authority_false: {bool_text(all_artifacts_non_authority)}",
            "",
            "Review note: INDEX.json and listed artifacts are evidence only, not authority.",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize an automation lab review artifact index.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--request-id", default=None, help="Automation lab request id.")
    group.add_argument("--path", default=None, help="Run directory or INDEX.json path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run_dir = resolve_run_dir(request_id=args.request_id, path=args.path)
        index, index_path = load_index(run_dir)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(render_summary(index, index_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
