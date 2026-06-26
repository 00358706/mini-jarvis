#!/usr/bin/env python3
"""Hermes-facing Mini-Jarvis media-flow wrapper.

Hermes uses this helper to call Mini-Jarvis gateway endpoints only. It does not
call media services directly, does not treat chat text as authorization, and
keeps proposal, approval, and execution as separate operator actions.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_AGENT = "media_agent"
TIMEOUT_SECONDS = 30


def _usage() -> str:
    return """Usage:
  python integrations/hermes/mini_jarvis_media_flow.py propose "<media request>" [--plan-id <id>]
  python integrations/hermes/mini_jarvis_media_flow.py pending
  python integrations/hermes/mini_jarvis_media_flow.py show <plan_id>
  python integrations/hermes/mini_jarvis_media_flow.py approve <plan_id> --confirm
  python integrations/hermes/mini_jarvis_media_flow.py execute <plan_id> --confirm

Environment:
  MINI_JARVIS_BASE_URL  Mini-Jarvis gateway base URL (default: http://127.0.0.1:8000)
  MINI_JARVIS_API_KEY   Required gateway API key
  MINI_JARVIS_AGENT     Agent for proposals (default: media_agent)
  DEBUG=1               Print raw JSON responses

Safety:
  - Hermes calls Mini-Jarvis endpoints only.
  - Natural-language chat is not authorization.
  - Approval and execution are separate.
  - approve and execute require --confirm.
  - Do not combine approve and execute.
"""


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _debug_enabled() -> bool:
    return (_env("DEBUG", "") or "").lower() in {"1", "true", "yes", "on"}


def _require_runtime() -> tuple[str, str, str] | None:
    base_url = _env("MINI_JARVIS_BASE_URL", DEFAULT_BASE_URL)
    api_key = _env("MINI_JARVIS_API_KEY")
    agent = _env("MINI_JARVIS_AGENT", DEFAULT_AGENT)
    if not base_url:
        sys.stderr.write("MINI_JARVIS_BASE_URL is required\n")
        return None
    if not api_key:
        sys.stderr.write("MINI_JARVIS_API_KEY is required\n")
        return None
    if not agent:
        sys.stderr.write("MINI_JARVIS_AGENT is required\n")
        return None
    return base_url.rstrip("/"), api_key, agent


def _http_json(
    method: str,
    url: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url=url,
        method=method,
        data=data,
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
            return int(response.status), (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"raw": body}
        return int(exc.code), parsed


def _json_preview(value: Any, *, max_chars: int = 900) -> str:
    text = json.dumps(value, ensure_ascii=True, sort_keys=True)
    if _debug_enabled() or len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _first_step(document: dict[str, Any] | None) -> tuple[str | None, Any | None]:
    if not isinstance(document, dict):
        return None, None
    steps = document.get("steps")
    if not isinstance(steps, list) or not steps or not isinstance(steps[0], dict):
        return None, None
    tool = steps[0].get("tool")
    args = steps[0].get("args")
    return (tool if isinstance(tool, str) else None), args


def _get_compact(base_url: str, api_key: str, plan_id: str) -> tuple[str | None, dict[str, Any] | None]:
    for state in ("active", "completed", "rejected"):
        code, body = _http_json(
            "GET",
            f"{base_url}/workspaces/{state}/{plan_id}/compact",
            api_key,
        )
        if code == 200 and isinstance(body, dict):
            return state, body
    return None, None


def _get_workspace(base_url: str, api_key: str, plan_id: str) -> tuple[str | None, dict[str, Any] | None]:
    for state in ("active", "completed", "rejected"):
        code, body = _http_json("GET", f"{base_url}/workspaces/{state}/{plan_id}", api_key)
        if code == 200 and isinstance(body, dict):
            return state, body
    return None, None


def _print_raw(label: str, value: Any) -> None:
    if _debug_enabled():
        sys.stdout.write(f"\nDEBUG {label}:\n")
        sys.stdout.write(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n")


def _print_compact(plan_id: str, state: str, compact: dict[str, Any]) -> None:
    tool, args = _first_step(compact)
    raw_policy = compact.get("policy")
    policy: dict[str, Any] = raw_policy if isinstance(raw_policy, dict) else {}
    raw_execution = compact.get("execution")
    execution: dict[str, Any] = raw_execution if isinstance(raw_execution, dict) else {}
    raw_artifacts = compact.get("artifacts")
    artifacts: dict[str, Any] = raw_artifacts if isinstance(raw_artifacts, dict) else {}

    sys.stdout.write("mini-jarvis media plan\n")
    sys.stdout.write(f"- plan_id: {plan_id}\n")
    sys.stdout.write(f"- state: {state}\n")
    approval_status = compact.get("approval_status")
    if isinstance(approval_status, str):
        sys.stdout.write(f"- approval_status: {approval_status}\n")
    if tool:
        sys.stdout.write(f"- proposed_tool: {tool}\n")
    if args is not None:
        sys.stdout.write(f"- proposed_args: {_json_preview(args)}\n")
    if isinstance(policy.get("allowed"), bool):
        sys.stdout.write(f"- policy.allowed: {str(policy.get('allowed')).lower()}\n")
    reasons = policy.get("reasons")
    if isinstance(reasons, list) and reasons:
        sys.stdout.write("- policy.reasons:\n")
        for reason in reasons[:20]:
            sys.stdout.write(f"  - {reason}\n")
    if isinstance(execution.get("status"), str):
        sys.stdout.write(f"- execution.status: {execution.get('status')}\n")
    log_count = execution.get("log_count")
    if isinstance(log_count, (int, float)):
        sys.stdout.write(f"- execution.log_count: {int(log_count)}\n")
    if "patch_proposal_present" in artifacts:
        sys.stdout.write(f"- patch_proposal_present: {str(bool(artifacts.get('patch_proposal_present'))).lower()}\n")


def _cmd_propose(base_url: str, api_key: str, agent: str, argv: list[str]) -> int:
    if not argv or not argv[0].strip():
        sys.stderr.write("media request is required for propose\n")
        return 2
    message = argv[0].strip()
    payload: dict[str, Any] = {"message": message, "agent": agent}
    if "--plan-id" in argv:
        idx = argv.index("--plan-id")
        if idx + 1 >= len(argv) or not argv[idx + 1].strip():
            sys.stderr.write("--plan-id requires a value\n")
            return 2
        payload["plan_id"] = argv[idx + 1].strip()

    code, body = _http_json("POST", f"{base_url}/plans/from-message", api_key, payload)
    status = body.get("status")
    plan_id = body.get("plan_id")
    sys.stdout.write("mini-jarvis media proposal\n")
    sys.stdout.write(f"- http_status: {code}\n")
    sys.stdout.write(f"- status: {status}\n")
    sys.stdout.write(f"- plan_id: {plan_id}\n")
    sys.stdout.write(f"- agent: {body.get('agent') or agent}\n")
    policy = body.get("policy") if isinstance(body.get("policy"), dict) else {}
    if isinstance(policy.get("allowed"), bool):
        sys.stdout.write(f"- policy.allowed: {str(policy.get('allowed')).lower()}\n")
    _print_raw("proposal response", body)

    if code != 200:
        return 1
    if status == "pending_approval" and isinstance(plan_id, str):
        state, compact = _get_compact(base_url, api_key, plan_id)
        if state and compact:
            sys.stdout.write("\n")
            _print_compact(plan_id, state, compact)
        sys.stdout.write("\nNo approval or execution was performed.\n")
        sys.stdout.write("Natural-language chat is not authorization.\n")
        sys.stdout.write("Next explicit steps:\n")
        sys.stdout.write(
            f"- Review:  python integrations/hermes/mini_jarvis_media_flow.py show {plan_id}\n"
        )
        sys.stdout.write(
            f"- Approve: python integrations/hermes/mini_jarvis_media_flow.py approve {plan_id} --confirm\n"
        )
    return 0


def _cmd_pending(base_url: str, api_key: str) -> int:
    code, body = _http_json("GET", f"{base_url}/plans/pending", api_key)
    sys.stdout.write("mini-jarvis pending media plans\n")
    sys.stdout.write(f"- http_status: {code}\n")
    if code != 200:
        _print_raw("pending response", body)
        return 1
    plans = body.get("plans") if isinstance(body.get("plans"), list) else []
    sys.stdout.write(f"- count: {len(plans)}\n")
    for plan_id in plans[:50]:
        if not isinstance(plan_id, str):
            continue
        sys.stdout.write(f"\nplan_id: {plan_id}\n")
        state, compact = _get_compact(base_url, api_key, plan_id)
        if state and compact:
            _print_compact(plan_id, state, compact)
        sys.stdout.write("Next explicit steps:\n")
        sys.stdout.write(f"- Review:  python integrations/hermes/mini_jarvis_media_flow.py show {plan_id}\n")
        sys.stdout.write(f"- Approve: python integrations/hermes/mini_jarvis_media_flow.py approve {plan_id} --confirm\n")
        sys.stdout.write(f"- Execute: python integrations/hermes/mini_jarvis_media_flow.py execute {plan_id} --confirm\n")
    return 0


def _cmd_show(base_url: str, api_key: str, plan_id: str) -> int:
    if not plan_id:
        sys.stderr.write("plan_id is required for show\n")
        return 2
    state, compact = _get_compact(base_url, api_key, plan_id)
    if not state or compact is None:
        sys.stderr.write("Plan workspace not found.\n")
        return 1
    _print_compact(plan_id, state, compact)
    if state == "completed":
        _, workspace = _get_workspace(base_url, api_key, plan_id)
        result_text = workspace.get("result_text") if isinstance(workspace, dict) else None
        if isinstance(result_text, str) and result_text.strip():
            preview = result_text.strip()
            if not _debug_enabled() and len(preview) > 1200:
                preview = preview[:1200] + "\n..."
            sys.stdout.write("\nRESULT.md preview:\n")
            sys.stdout.write(preview + "\n")
    return 0


def _confirm_or_refuse(confirm: bool, action: str) -> int:
    if confirm:
        return 0
    if action == "approve":
        sys.stdout.write("Refusing to approve without --confirm.\n")
    elif action == "execute":
        sys.stdout.write("Refusing to execute without --confirm.\n")
    else:
        sys.stdout.write(f"Refusing to {action} without --confirm.\n")
    sys.stdout.write("Natural-language chat is not authorization.\n")
    sys.stdout.write("Approval and execution are separate operator actions.\n")
    return 2


def _cmd_approve(base_url: str, api_key: str, plan_id: str, confirm: bool) -> int:
    if not plan_id:
        sys.stderr.write("plan_id is required for approve\n")
        return 2
    refused = _confirm_or_refuse(confirm, "approve")
    if refused:
        return refused
    state, compact = _get_compact(base_url, api_key, plan_id)
    if state != "active" or compact is None:
        sys.stderr.write("Active pending workspace not found; refusing to approve.\n")
        return 1
    _print_compact(plan_id, state, compact)
    code, body = _http_json("POST", f"{base_url}/plans/{plan_id}/approve", api_key)
    sys.stdout.write(f"\napprove http_status: {code}\n")
    _print_raw("approve response", body)
    if code != 200:
        return 1
    sys.stdout.write("Approved. No execution was started.\n")
    sys.stdout.write("Next explicit step:\n")
    sys.stdout.write(f"- Execute: python integrations/hermes/mini_jarvis_media_flow.py execute {plan_id} --confirm\n")
    return 0


def _cmd_execute(base_url: str, api_key: str, plan_id: str, confirm: bool) -> int:
    if not plan_id:
        sys.stderr.write("plan_id is required for execute\n")
        return 2
    refused = _confirm_or_refuse(confirm, "execute")
    if refused:
        return refused
    code, body = _http_json("POST", f"{base_url}/plans/{plan_id}/execute", api_key)
    sys.stdout.write(f"execute http_status: {code}\n")
    _print_raw("execute response", body)
    if code != 200:
        return 1
    sys.stdout.write("Execution requested through Mini-Jarvis approved-plan endpoint.\n")
    state, compact = _get_compact(base_url, api_key, plan_id)
    if state and compact:
        sys.stdout.write("\n")
        _print_compact(plan_id, state, compact)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in {"-h", "--help", "help"}:
        sys.stdout.write(_usage())
        return 0 if len(argv) >= 2 else 2

    runtime = _require_runtime()
    if runtime is None:
        return 2
    base_url, api_key, agent = runtime
    cmd = argv[1].strip().lower()
    args = argv[2:]
    confirm = "--confirm" in args
    args_without_flags = [arg for arg in args if arg != "--confirm"]

    if cmd == "propose":
        return _cmd_propose(base_url, api_key, agent, args_without_flags)
    if cmd == "pending":
        return _cmd_pending(base_url, api_key)
    if cmd == "show":
        return _cmd_show(base_url, api_key, args_without_flags[0] if args_without_flags else "")
    if cmd == "approve":
        return _cmd_approve(base_url, api_key, args_without_flags[0] if args_without_flags else "", confirm)
    if cmd == "execute":
        return _cmd_execute(base_url, api_key, args_without_flags[0] if args_without_flags else "", confirm)

    sys.stderr.write(f"Unknown command: {cmd}\n")
    sys.stderr.write(_usage())
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
