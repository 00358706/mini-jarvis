"""
Optional local model drafting helper for the automation lab.

This helper only calls OpenAI-compatible local chat-completions endpoints when
explicitly enabled by the automation lab CLI. It does not import or call gateway
runtime modules, registry lifecycle code, tool implementations, sandbox code,
or approval paths.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


SYSTEM_PROMPT = """You draft review-only Mini-Jarvis automation lab notes.
Return one JSON object only. Do not call tools. Do not approve, authorize,
install, register, execute, or claim anything ran. Model output is proposal,
not authority."""

FORBIDDEN_OUTPUT_KEYS = {
    "approval_state",
    "authorization",
    "authorized",
    "execute",
    "executed",
    "registry_status",
    "tool_calls",
    "tools",
}


@dataclass(frozen=True)
class LocalModelDraftResult:
    request: dict[str, Any]
    response: dict[str, Any]
    validation: dict[str, Any]
    draft_markdown: str


def build_request_payload(
    *,
    message: str,
    classification: dict[str, Any],
    capability_matches: dict[str, Any],
    model_name: str,
) -> dict[str, Any]:
    user_payload = {
        "message": message,
        "classification": {
            "proposal_kind": classification.get("proposal_kind"),
            "domain": classification.get("domain"),
        },
        "capability_matches": {
            "primary_outcome": capability_matches.get("primary_outcome"),
            "capability_ids": capability_matches.get("capability_ids", []),
        },
        "required_boundary": {
            "proposal_only": True,
            "model_output_is_proposal_not_authority": True,
            "tools_executed": False,
            "sandbox_worker_invoked": False,
            "registry_modified": False,
            "generated_tool_execution_allowed": False,
        },
        "requested_json_shape": {
            "draft_title": "string",
            "summary": "string",
            "review_notes": ["string"],
            "risks": ["string"],
            "suggested_next_review_steps": ["string"],
        },
    }
    return {
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, sort_keys=True)},
        ],
        "temperature": 0,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
    }


def complete_chat(
    *,
    base_url: str,
    request_payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(request_payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                return {
                    "ok": False,
                    "status_code": getattr(resp, "status", None),
                    "raw": raw,
                    "error_type": "invalid_response_json",
                    "error": str(exc),
                }
            return {
                "ok": True,
                "status_code": getattr(resp, "status", None),
                "body": parsed,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "ok": False,
            "status_code": exc.code,
            "raw": raw,
            "error_type": "http_error",
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "raw": None,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def extract_content(response_payload: dict[str, Any]) -> str | None:
    if not response_payload.get("ok"):
        return None
    body = response_payload.get("body")
    if not isinstance(body, dict):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None


def validate_model_output(content: str | None) -> dict[str, Any]:
    if content is None:
        return {
            "schema_version": "automation-lab-model-validation.v1",
            "valid": False,
            "advisory_only": True,
            "validation_state": "failed",
            "parsed_json": None,
            "errors": ["No assistant content was available to validate."],
            "forbidden_keys_found": [],
        }

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        return {
            "schema_version": "automation-lab-model-validation.v1",
            "valid": False,
            "advisory_only": True,
            "validation_state": "failed",
            "parsed_json": None,
            "errors": [f"Assistant content was not valid JSON: {exc}"],
            "forbidden_keys_found": [],
        }

    errors: list[str] = []
    if not isinstance(parsed, dict):
        errors.append("Assistant JSON must be an object.")
        parsed_obj: dict[str, Any] = {}
    else:
        parsed_obj = parsed

    found = sorted(set(_walk_keys(parsed_obj)) & FORBIDDEN_OUTPUT_KEYS)
    if found:
        errors.append("Assistant JSON included forbidden authority-like keys.")

    for field in ("draft_title", "summary", "review_notes"):
        if field not in parsed_obj:
            errors.append(f"Missing expected field: {field}")

    valid = not errors
    return {
        "schema_version": "automation-lab-model-validation.v1",
        "valid": valid,
        "advisory_only": True,
        "validation_state": "passed" if valid else "failed",
        "parsed_json": parsed_obj if isinstance(parsed_obj, dict) else None,
        "errors": errors,
        "forbidden_keys_found": found,
    }


def _walk_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                keys.append(key)
            keys.extend(_walk_keys(child))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_walk_keys(item))
    return keys


def draft_markdown(validation: dict[str, Any], response_payload: dict[str, Any]) -> str:
    parsed = validation.get("parsed_json")
    if validation.get("valid") and isinstance(parsed, dict):
        notes = parsed.get("review_notes")
        risks = parsed.get("risks")
        steps = parsed.get("suggested_next_review_steps")
        return "\n".join(
            [
                "# Local Model Draft",
                "",
                "Source: optional local model adapter",
                "",
                f"Title: {parsed.get('draft_title', 'Untitled draft')}",
                "",
                "Summary:",
                str(parsed.get("summary", "")),
                "",
                "Review notes:",
                _markdown_list(notes),
                "",
                "Risks:",
                _markdown_list(risks),
                "",
                "Suggested next review steps:",
                _markdown_list(steps),
                "",
                "Authority boundary:",
                "- Advisory only: true",
                "- Model output is proposal, not authority: true",
                "- Tools executed: false",
                "- Sandbox worker invoked: false",
                "- Registry modified: false",
            ]
        ).rstrip() + "\n"

    errors = validation.get("errors") or [response_payload.get("error") or "Unknown failure"]
    return "\n".join(
        [
            "# Local Model Draft",
            "",
            "No valid model draft is available.",
            "",
            "Validation state: failed",
            "",
            "Errors:",
            _markdown_list(errors),
            "",
            "Fallback:",
            "The deterministic automation lab artifacts remain the review source.",
            "",
            "Authority boundary:",
            "- Advisory only: true",
            "- Model output is proposal, not authority: true",
            "- Tools executed: false",
            "- Sandbox worker invoked: false",
            "- Registry modified: false",
        ]
    ).rstrip() + "\n"


def _markdown_list(value: Any) -> str:
    if isinstance(value, list) and value:
        return "\n".join(f"- {item}" for item in value)
    if isinstance(value, str) and value:
        return f"- {value}"
    return "- None recorded."


def draft_with_local_model(
    *,
    message: str,
    classification: dict[str, Any],
    capability_matches: dict[str, Any],
    base_url: str,
    model_name: str,
    timeout_seconds: float = 5.0,
) -> LocalModelDraftResult:
    request_payload = build_request_payload(
        message=message,
        classification=classification,
        capability_matches=capability_matches,
        model_name=model_name,
    )
    response_payload = complete_chat(
        base_url=base_url,
        request_payload=request_payload,
        timeout_seconds=timeout_seconds,
    )
    content = extract_content(response_payload)
    validation = validate_model_output(content)
    markdown = draft_markdown(validation, response_payload)
    return LocalModelDraftResult(
        request=request_payload,
        response=response_payload,
        validation=validation,
        draft_markdown=markdown,
    )
