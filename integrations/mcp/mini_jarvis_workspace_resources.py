"""
mini_jarvis_workspace_resources.py

Read-only MCP-style workspace resources for mini-jarvis.

Design goals (invariants):
- Read-only resources only (no tools, no mutation, no approve/reject/execute).
- Reuse existing workspace validators/helpers where possible.
- Runnable as a separate optional script (gateway startup must not require MCP deps).
- stdio transport only (no network server behavior in this branch).

This file also provides a small CLI "read resource" mode used by smoke tests,
so tests do not require a full MCP host/client setup.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlparse, unquote

# Ensure repo root is importable when running this script directly.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from workspace import list_workspaces, read_workspace_file, read_workspace_summary

_VALID_STATES = {"active", "completed", "rejected"}
_MAX_TEXT_BYTES = 200_000


def _cap_text(text: str | None, *, max_bytes: int = _MAX_TEXT_BYTES) -> str | None:
    if text is None:
        return None
    if not isinstance(text, str):
        return str(text)
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= max_bytes:
        return text
    clipped = raw[:max_bytes].decode("utf-8", errors="replace")
    return clipped + "\n…\n(TRUNCATED)\n"


def _extract_execution_status_from_result_text(text: str) -> str | None:
    """
    Extract execution status from RESULT.md text.

    Accepts:
      - "- status: `executed_success`"
      - "- status: executed_success"
    """
    if not text:
        return None
    m = re.search(r"(?im)^\s*-\s*status\s*:\s*`?([A-Za-z0-9_]+)`?\s*$", text)
    if not m:
        return None
    return m.group(1).strip()


def _compact_summary(state: str, task_id: str) -> dict[str, Any]:
    if state not in _VALID_STATES:
        raise ValueError("Invalid state.")

    ws = read_workspace_summary(task_id=task_id, state=state)  # validates task_id

    plan_json = ws.get("plan_json") if isinstance(ws.get("plan_json"), dict) else {}
    policy_decision = (
        ws.get("policy_decision_json") if isinstance(ws.get("policy_decision_json"), dict) else {}
    )

    agent = plan_json.get("agent") if isinstance(plan_json.get("agent"), str) else "unknown_agent"
    risk = plan_json.get("risk") if isinstance(plan_json.get("risk"), str) else "level_0"
    plan_status = plan_json.get("status") if isinstance(plan_json.get("status"), str) else "proposed"

    approval_text = ws.get("approval_text")
    approval_status = None
    if isinstance(approval_text, str) and approval_text.strip():
        m = re.search(r"(?im)\bStatus\s*:\s*([A-Za-z_]+)\b", approval_text)
        if m:
            approval_status = m.group(1).strip()
    if not approval_status:
        approval_status = "pending_approval" if state == "active" else None

    policy_allowed = policy_decision.get("allowed")
    if not isinstance(policy_allowed, bool):
        policy_allowed = False
    reasons_raw = policy_decision.get("reasons")
    policy_reasons: list[str] = []
    if isinstance(reasons_raw, list):
        policy_reasons = [str(r) for r in reasons_raw][:50]

    steps: list[dict[str, Any]] = []
    plan_steps = plan_json.get("steps")
    if isinstance(plan_steps, list):
        for s in plan_steps:
            if not isinstance(s, dict):
                continue
            tool = s.get("tool")
            if not isinstance(tool, str):
                continue
            steps.append(
                {
                    "step_id": str(s.get("step_id") or ""),
                    "tool": tool,
                    "args": s.get("args") if isinstance(s.get("args"), dict) else {},
                    "description": str(s.get("description") or ""),
                }
            )

    result_text = ws.get("result_text")
    result_present = isinstance(result_text, str) and bool(result_text.strip())

    try:
        log_count = int(ws.get("execution_log_count") or 0)
    except Exception:
        log_count = 0

    execution_status = None
    if state == "completed" and isinstance(result_text, str) and result_text.strip():
        execution_status = _extract_execution_status_from_result_text(result_text)

    recommended_next_action = "review_then_approve_or_reject" if state == "active" else "review_results"
    review_summary = (
        f"agent={agent} policy.allowed={str(policy_allowed).lower()} approval={approval_status or 'n/a'} "
        + (f"execution={execution_status}" if execution_status else "execution=not_started")
    )

    files_present: list[str] = []
    files_block = ws.get("files")
    if isinstance(files_block, dict):
        present = files_block.get("present")
        if isinstance(present, list):
            files_present = [str(p) for p in present]

    return {
        "task_id": ws.get("task_id"),
        "state": ws.get("state"),
        "agent": agent,
        "risk": risk,
        "status": plan_status,
        "approval_status": approval_status,
        "policy": {"allowed": policy_allowed, "reasons": policy_reasons},
        "steps": steps,
        "execution": {
            "log_count": log_count,
            "has_result": result_present,
            "status": execution_status,
        },
        "artifacts": {
            "patch_proposal_present": bool(ws.get("patch_proposal_present")),
            "result_present": result_present,
            "files_present": files_present,
        },
        "review": {"summary": review_summary, "recommended_next_action": recommended_next_action},
    }


def read_resource(uri: str) -> dict[str, Any]:
    """
    Read a mini-jarvis workspace resource by URI.

    Supported resources:
      - mini-jarvis://workspaces/{state}
      - mini-jarvis://workspaces/{state}/{task_id}/compact
      - mini-jarvis://workspaces/{state}/{task_id}/files/{filename}
    """
    if not isinstance(uri, str) or not uri.strip():
        raise ValueError("uri is required")

    parsed = urlparse(uri)
    if parsed.scheme != "mini-jarvis":
        raise ValueError("Invalid URI scheme.")
    if parsed.netloc != "workspaces":
        raise ValueError("Invalid URI host; expected mini-jarvis://workspaces/...")

    # Keep traversal contained: decode but never interpret as filesystem paths.
    path = unquote(parsed.path or "")
    if not path.startswith("/"):
        raise ValueError("Invalid URI path.")

    parts = [p for p in path.split("/") if p]
    if not parts:
        raise ValueError("Invalid URI path.")

    state = parts[0]
    if state not in _VALID_STATES:
        raise ValueError("Invalid state.")

    # 1) state list
    if len(parts) == 1:
        items = list_workspaces(state)  # type: ignore[arg-type]
        return {"uri": uri, "kind": "workspaces_list", "state": state, "count": len(items), "workspaces": items}

    # Remaining forms require task_id
    if len(parts) < 3:
        raise ValueError("Invalid workspace resource path.")

    task_id = parts[1]
    tail = parts[2]

    if tail == "compact":
        if len(parts) != 3:
            raise ValueError("Invalid compact resource path.")
        return {"uri": uri, "kind": "workspace_compact", "data": _compact_summary(state, task_id)}

    if tail == "files":
        if len(parts) != 4:
            raise ValueError("Invalid files resource path.")
        filename = parts[3]
        file_obj = read_workspace_file(task_id=task_id, state=state, filename=filename)  # type: ignore[arg-type]
        if isinstance(file_obj, dict) and "content" in file_obj:
            file_obj["content"] = _cap_text(file_obj.get("content"))
        return {"uri": uri, "kind": "workspace_file", "data": file_obj}

    raise ValueError("Unknown workspace resource.")


def _serve_stdio_mcp() -> int:
    """
    Optional stdio MCP server mode.
    This does not run unless MCP dependencies are installed.
    """
    try:
        # Imported only when server mode is requested.
        from mcp.server.fastmcp import FastMCP  # type: ignore
    except Exception:
        sys.stderr.write(
            "MCP Python SDK is not installed.\n"
            "Install (example): pip install mcp\n"
        )
        return 2

    mcp = FastMCP("mini-jarvis (workspace resources)")

    @mcp.resource("mini-jarvis://workspaces/{state}")  # type: ignore[misc]
    def _res_state_list(state: str) -> str:
        payload = read_resource(f"mini-jarvis://workspaces/{state}")
        return json.dumps(payload, ensure_ascii=True)

    @mcp.resource("mini-jarvis://workspaces/{state}/{task_id}/compact")  # type: ignore[misc]
    def _res_compact(state: str, task_id: str) -> str:
        payload = read_resource(f"mini-jarvis://workspaces/{state}/{task_id}/compact")
        return json.dumps(payload, ensure_ascii=True)

    @mcp.resource("mini-jarvis://workspaces/{state}/{task_id}/files/{filename}")  # type: ignore[misc]
    def _res_file(state: str, task_id: str, filename: str) -> str:
        payload = read_resource(f"mini-jarvis://workspaces/{state}/{task_id}/files/{filename}")
        return json.dumps(payload, ensure_ascii=True)

    mcp.run()
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--read", dest="read_uri", help="Read one resource URI and print JSON.")
    ap.add_argument("--serve-stdio", action="store_true", help="Run stdio MCP server (requires MCP SDK).")
    args = ap.parse_args(argv)

    if args.serve_stdio:
        return _serve_stdio_mcp()

    if args.read_uri:
        try:
            payload = read_resource(args.read_uri)
        except ValueError as exc:
            sys.stderr.write(f"error: {exc}\n")
            return 2
        except FileNotFoundError as exc:
            sys.stderr.write(f"not_found: {exc}\n")
            return 3
        sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

