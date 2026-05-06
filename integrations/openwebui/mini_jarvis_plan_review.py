"""
Open WebUI review/approval/execution wrapper (explicit, command-based).

This script is intentionally separate from proposal creation:
- It NEVER calls /plans/from-message
- It NEVER generates plans
- It NEVER calls tools directly
- It NEVER calls sandbox directly

Commands (each requires explicit invocation):
  show <plan_id>
  approve <plan_id> [--confirm]
  reject <plan_id>  [--confirm]
  execute <plan_id> [--confirm]
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default


def _http_json(
    method: str,
    url: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        method=method,
        data=data,
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"raw": body}
        return exc.code, parsed


def _is_debug() -> bool:
    v = os.getenv("DEBUG") or ""
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _cap_text(text: str, *, max_chars: int) -> str:
    t = text.strip()
    if len(t) <= max_chars:
        return t
    return t[:max_chars] + "\n…"


def _first_step(plan_json: dict[str, Any] | None) -> tuple[str | None, dict[str, Any] | None]:
    if not isinstance(plan_json, dict):
        return None, None
    steps = plan_json.get("steps")
    if not isinstance(steps, list) or not steps:
        return None, None
    step0 = steps[0]
    if not isinstance(step0, dict):
        return None, None
    tool = step0.get("tool")
    args = step0.get("args")
    return (tool if isinstance(tool, str) else None, args if isinstance(args, dict) else None)


def _first_step_from_compact(compact: dict[str, Any] | None) -> tuple[str | None, dict[str, Any] | None]:
    if not isinstance(compact, dict):
        return None, None
    steps = compact.get("steps")
    if not isinstance(steps, list) or not steps:
        return None, None
    step0 = steps[0]
    if not isinstance(step0, dict):
        return None, None
    tool = step0.get("tool")
    args = step0.get("args")
    return (tool if isinstance(tool, str) else None, args if isinstance(args, dict) else None)


def _get_workspace_summary(base_url: str, api_key: str, plan_id: str) -> tuple[str | None, dict[str, Any] | None]:
    for state in ("active", "completed", "rejected"):
        code, body = _http_json("GET", f"{base_url}/workspaces/{state}/{plan_id}", api_key)
        if code == 200 and isinstance(body, dict):
            return state, body
    return None, None


def _get_workspace_compact_summary(
    base_url: str, api_key: str, plan_id: str
) -> tuple[str | None, dict[str, Any] | None]:
    for state in ("active", "completed", "rejected"):
        code, body = _http_json(
            "GET", f"{base_url}/workspaces/{state}/{plan_id}/compact", api_key
        )
        if code == 200 and isinstance(body, dict):
            return state, body
    return None, None


def _print_workspace_summary(plan_id: str, state: str, ws: dict[str, Any]) -> None:
    plan_json = ws.get("plan_json") if isinstance(ws.get("plan_json"), dict) else None
    tool, args = _first_step(plan_json)

    policy = ws.get("policy_decision_json") if isinstance(ws.get("policy_decision_json"), dict) else None
    policy_allowed = policy.get("allowed") if isinstance(policy, dict) else None
    reasons = policy.get("reasons") if isinstance(policy, dict) else None
    reasons_list = [str(r) for r in reasons] if isinstance(reasons, list) else []

    approval_text = ws.get("approval_text")
    result_text = ws.get("result_text")

    lines: list[str] = []
    lines.append("mini-jarvis plan review")
    lines.append(f"- plan_id: {plan_id}")
    lines.append(f"- state: {state}")
    if tool:
        lines.append(f"- tool: {tool}")
    if args is not None:
        lines.append(f"- args: {json.dumps(args, ensure_ascii=True)}")
    if isinstance(policy_allowed, bool):
        lines.append(f"- policy.allowed: {str(policy_allowed).lower()}")
    if reasons_list:
        lines.append("- policy.reasons:")
        for r in reasons_list[:30]:
            lines.append(f"  - {r}")
    if isinstance(approval_text, str) and approval_text.strip():
        lines.append("- approval_text_present: true")
    else:
        lines.append("- approval_text_present: false")
    lines.append(f"- execution_log_count: {int(ws.get('execution_log_count') or 0)}")
    lines.append(f"- patch_proposal_present: {str(bool(ws.get('patch_proposal_present'))).lower()}")
    if state == "completed" and isinstance(result_text, str) and result_text.strip():
        lines.append("")
        lines.append("RESULT.md:")
        preview = result_text.strip()
        if len(preview) > 800:
            preview = preview[:800] + "\n…"
        lines.append(preview)

    sys.stdout.write("\n".join(lines) + "\n")


def _print_compact_workspace_summary(
    plan_id: str, state: str, compact: dict[str, Any]
) -> None:
    tool, args = _first_step_from_compact(compact)

    policy = compact.get("policy") if isinstance(compact.get("policy"), dict) else {}
    policy_allowed = policy.get("allowed") if isinstance(policy.get("allowed"), bool) else None
    reasons = policy.get("reasons") if isinstance(policy.get("reasons"), list) else []
    reasons_list = [str(r) for r in reasons]

    approval_status = compact.get("approval_status")
    exec_block = compact.get("execution") if isinstance(compact.get("execution"), dict) else {}
    log_count = exec_block.get("log_count") if isinstance(exec_block.get("log_count"), (int, float)) else 0
    exec_status = exec_block.get("status") if isinstance(exec_block.get("status"), str) else None
    artifacts_block = compact.get("artifacts") if isinstance(compact.get("artifacts"), dict) else {}
    patch_present = artifacts_block.get("patch_proposal_present")

    lines: list[str] = []
    lines.append("mini-jarvis plan review")
    lines.append(f"- plan_id: {plan_id}")
    lines.append(f"- state: {state}")
    if tool:
        lines.append(f"- tool: {tool}")
    if args is not None:
        args_json = json.dumps(args, ensure_ascii=True)
        if not _is_debug():
            args_json = _cap_text(args_json, max_chars=800)
        lines.append(f"- args: {args_json}")
    if isinstance(policy_allowed, bool):
        lines.append(f"- policy.allowed: {str(policy_allowed).lower()}")
    if reasons_list:
        lines.append("- policy.reasons:")
        for r in reasons_list[:30]:
            lines.append(f"  - {r}")
    if isinstance(approval_status, str):
        lines.append(f"- approval_status: {approval_status}")
    if exec_status:
        lines.append(f"- execution.status: {exec_status}")
    lines.append(f"- execution.log_count: {int(log_count)}")
    lines.append(f"- patch_proposal_present: {str(bool(patch_present)).lower()}")

    sys.stdout.write("\n".join(lines) + "\n")


def _require_confirm(confirm: bool, action: str) -> int:
    if confirm:
        return 0
    sys.stdout.write(f"Refusing to {action} without --confirm.\n")
    sys.stdout.write("This wrapper does not auto-approve or auto-execute.\n")
    return 2


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        sys.stderr.write(
            "Usage:\n"
            "  python integrations/openwebui/mini_jarvis_plan_review.py show <plan_id>\n"
            "  python integrations/openwebui/mini_jarvis_plan_review.py approve <plan_id> --confirm\n"
            "  python integrations/openwebui/mini_jarvis_plan_review.py reject <plan_id> --confirm\n"
            "  python integrations/openwebui/mini_jarvis_plan_review.py execute <plan_id> --confirm\n"
            "\n"
            "Notes:\n"
            "  - approve does NOT execute tools\n"
            "  - execute does NOT approve plans\n"
            "  - set DEBUG=1 for raw JSON\n"
        )
        return 2

    cmd = argv[1].strip().lower()
    plan_id = argv[2].strip()
    confirm = "--confirm" in argv[3:]

    base_url = _env("MINI_JARVIS_BASE_URL", "http://127.0.0.1:8000")
    api_key = _env("MINI_JARVIS_API_KEY")
    if not base_url:
        sys.stderr.write("MINI_JARVIS_BASE_URL is required\n")
        return 2
    if not api_key:
        sys.stderr.write("MINI_JARVIS_API_KEY is required\n")
        return 2
    base_url = base_url.rstrip("/")

    if cmd == "show":
        c_state, compact = _get_workspace_compact_summary(base_url, api_key, plan_id)
        if not c_state or not compact:
            sys.stderr.write("Workspace not found for plan_id.\n")
            return 1
        _print_compact_workspace_summary(plan_id, c_state, compact)
        if c_state == "completed":
            state, ws = _get_workspace_summary(base_url, api_key, plan_id)
            if state == "completed" and isinstance(ws, dict):
                result_text = ws.get("result_text")
                if isinstance(result_text, str) and result_text.strip():
                    sys.stdout.write("\nRESULT.md (preview):\n")
                    sys.stdout.write(_cap_text(result_text, max_chars=1200) + "\n")
        return 0

    if cmd == "approve":
        rc = _require_confirm(confirm, "approve")
        if rc != 0:
            return rc
        # Show context first (active only)
        code, ws = _http_json("GET", f"{base_url}/workspaces/active/{plan_id}", api_key)
        if code != 200 or not isinstance(ws, dict):
            sys.stderr.write("Active workspace not found; cannot approve.\n")
            return 1
        code, compact = _http_json(
            "GET", f"{base_url}/workspaces/active/{plan_id}/compact", api_key
        )
        tool, args = _first_step_from_compact(compact if isinstance(compact, dict) else None)
        if tool:
            sys.stdout.write(f"Approving plan {plan_id} (tool={tool}, args={json.dumps(args or {}, ensure_ascii=True)})\n")
        code, body = _http_json("POST", f"{base_url}/plans/{plan_id}/approve", api_key)
        sys.stdout.write(f"approve http_status: {code}\n")
        if code == 200:
            sys.stdout.write("Approved. No tools executed.\n")
            sys.stdout.write("\nNext step (explicit):\n")
            sys.stdout.write(f"- Execute: python integrations/openwebui/mini_jarvis_plan_review.py execute {plan_id} --confirm\n")
            if _is_debug():
                sys.stdout.write("\nDEBUG raw response:\n")
                sys.stdout.write(json.dumps(body, ensure_ascii=True) + "\n")
            return 0
        if _is_debug():
            sys.stdout.write("\nDEBUG raw response:\n")
            sys.stdout.write(json.dumps(body, ensure_ascii=True) + "\n")
        return 1

    if cmd == "reject":
        rc = _require_confirm(confirm, "reject")
        if rc != 0:
            return rc
        code, body = _http_json(
            "POST",
            f"{base_url}/plans/{plan_id}/reject",
            api_key,
            payload={"reason": "rejected via openwebui wrapper"},
        )
        sys.stdout.write(f"reject http_status: {code}\n")
        if code == 200:
            sys.stdout.write("Rejected. No tools executed.\n")
        if _is_debug():
            sys.stdout.write(json.dumps(body, ensure_ascii=True) + "\n")
        return 0 if code == 200 else 1

    if cmd == "execute":
        rc = _require_confirm(confirm, "execute")
        if rc != 0:
            return rc
        code, body = _http_json("POST", f"{base_url}/plans/{plan_id}/execute", api_key)
        sys.stdout.write(f"execute http_status: {code}\n")
        if _is_debug():
            sys.stdout.write(json.dumps(body, ensure_ascii=True) + "\n")
        if code != 200:
            return 1
        # If execution succeeded, show completed compact summary + capped result preview.
        c_state, compact = _get_workspace_compact_summary(base_url, api_key, plan_id)
        if c_state and compact:
            sys.stdout.write("\n")
            _print_compact_workspace_summary(plan_id, c_state, compact)
        state, ws = _get_workspace_summary(base_url, api_key, plan_id)
        if state == "completed" and isinstance(ws, dict):
            result_text = ws.get("result_text")
            if isinstance(result_text, str) and result_text.strip():
                sys.stdout.write("\nRESULT.md (preview):\n")
                sys.stdout.write(_cap_text(result_text, max_chars=1200) + "\n")
        return 0

    sys.stderr.write(f"Unknown command: {cmd}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

