"""
Open WebUI action wrapper (proposal-only).

This script sends a user message to the gateway's POST /plans/from-message
endpoint, then (if pending approval) fetches the active workspace summary.

It does NOT approve plans and does NOT execute tools.
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


def _http_json(method: str, url: str, api_key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"raw": body}
        parsed["_http_status"] = exc.code
        return parsed


def _is_debug() -> bool:
    v = os.getenv("DEBUG") or ""
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _cap_text(text: str, *, max_chars: int) -> str:
    t = text.strip()
    if len(t) <= max_chars:
        return t
    return t[:max_chars] + "\n…"


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


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write(
            "Usage: python integrations/openwebui/mini_jarvis_plan_propose.py \"message\"\n"
            "\n"
            "Environment:\n"
            "  MINI_JARVIS_BASE_URL  (default: http://127.0.0.1:8000)\n"
            "  MINI_JARVIS_API_KEY   (required; same as gateway GATEWAY_API_KEY)\n"
            "  MINI_JARVIS_AGENT     (default: project_maintainer_agent)\n"
            "  DEBUG=1               (print raw JSON)\n"
        )
        return 2

    message = argv[1].strip()
    if not message:
        sys.stderr.write("message is required\n")
        return 2

    base_url = _env("MINI_JARVIS_BASE_URL", "http://127.0.0.1:8000")
    api_key = _env("MINI_JARVIS_API_KEY")
    agent = _env("MINI_JARVIS_AGENT", "project_maintainer_agent")

    if not base_url:
        sys.stderr.write("MINI_JARVIS_BASE_URL is required\n")
        return 2
    if not api_key:
        sys.stderr.write("MINI_JARVIS_API_KEY is required\n")
        return 2
    if not agent:
        sys.stderr.write("MINI_JARVIS_AGENT is required\n")
        return 2

    base_url = base_url.rstrip("/")

    propose = _http_json(
        "POST",
        f"{base_url}/plans/from-message",
        api_key,
        payload={"message": message, "agent": agent},
    )

    status = propose.get("status")
    plan_id = propose.get("plan_id")
    policy = propose.get("policy") if isinstance(propose.get("policy"), dict) else None
    policy_allowed = None
    policy_reasons: list[str] = []
    if isinstance(policy, dict):
        if isinstance(policy.get("allowed"), bool):
            policy_allowed = policy.get("allowed")
        if isinstance(policy.get("reasons"), list):
            policy_reasons = [str(r) for r in policy.get("reasons")][:20]

    workspace = propose.get("workspace") if isinstance(propose.get("workspace"), dict) else {}
    summary_url = workspace.get("summary_url") if isinstance(workspace.get("summary_url"), str) else None

    agent_from_compact: str | None = None
    tool: str | None = None
    tool_args: dict[str, Any] | None = None
    compact_url: str | None = None
    if status == "pending_approval" and isinstance(plan_id, str):
        compact_url = f"{base_url}/workspaces/active/{plan_id}/compact"
        compact = _http_json("GET", compact_url, api_key)
        if isinstance(compact, dict):
            agent_from_compact = compact.get("agent") if isinstance(compact.get("agent"), str) else None
        tool, tool_args = _first_step_from_compact(compact if isinstance(compact, dict) else None)

    lines: list[str] = []
    lines.append("mini-jarvis plan proposal")
    lines.append(f"- plan_id: {plan_id}")
    lines.append(f"- status: {status}")
    lines.append(f"- agent: {agent_from_compact or agent}")
    if tool:
        lines.append(f"- proposed_tool: {tool}")
    if tool_args is not None:
        args_json = json.dumps(tool_args, ensure_ascii=True)
        if not _is_debug():
            args_json = _cap_text(args_json, max_chars=800)
        lines.append(f"- proposed_args: {args_json}")
    if policy_allowed is not None:
        lines.append(f"- policy.allowed: {str(policy_allowed).lower()}")
    if policy_reasons:
        lines.append("- policy.reasons:")
        for r in policy_reasons:
            lines.append(f"  - {r}")
    if compact_url:
        lines.append(f"- workspace_compact_url: {compact_url}")
    elif summary_url:
        lines.append(f"- workspace_summary_url: {summary_url}")

    if status == "pending_approval":
        lines.append("")
        lines.append("This plan is pending approval. No tools have been executed.")
        if isinstance(plan_id, str) and plan_id.strip():
            lines.append("")
            lines.append("Next steps (explicit):")
            lines.append(f"- Review:  python integrations/openwebui/mini_jarvis_plan_review.py show {plan_id}")
            lines.append(
                f"- Approve: python integrations/openwebui/mini_jarvis_plan_review.py approve {plan_id} --confirm"
            )
    elif status == "policy_rejected":
        lines.append("")
        lines.append("This plan was rejected by policy. No tools have been executed.")

    if _is_debug():
        lines.append("")
        lines.append("DEBUG raw response:")
        lines.append(json.dumps(propose, ensure_ascii=True))

    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

