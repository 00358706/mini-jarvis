"""
workspace.py — Readable task workspace files under data/workspaces/.

Creates and updates markdown/JSON artifacts only. No tools, registry, sandbox, or models.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from plans import Plan, plan_to_dict
from policy import PolicyDecision

_WORKSPACES_ROOT = Path(__file__).resolve().parent / "data" / "workspaces"
_ACTIVE = _WORKSPACES_ROOT / "active"
_COMPLETED = _WORKSPACES_ROOT / "completed"
_REJECTED = _WORKSPACES_ROOT / "rejected"

_REQUEST = "REQUEST.md"
_ROUTE = "ROUTE.json"
_AGENT = "AGENT.md"
_CONTEXT = "CONTEXT.md"
_PLAN = "PLAN.json"
_POLICY_DECISION = "POLICY_DECISION.json"
_APPROVAL = "APPROVAL.md"
_EXECUTION_LOG = "EXECUTION_LOG.jsonl"
_RESULT = "RESULT.md"

_MoveDest = Literal["completed", "rejected"]
_STATE = Literal["active", "completed", "rejected"]


def _state_dir(state: _STATE) -> Path:
    if state == "active":
        return _ACTIVE
    if state == "completed":
        return _COMPLETED
    return _REJECTED


def _gen_task_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"task_{ts}_{short}"


def workspace_path(task_id: str, state: _STATE = "active") -> Path:
    """Return the path to ``<task_id>`` under the given workspace state."""
    return _state_dir(state) / task_id


def _active_root(task_id: str) -> Path:
    root = workspace_path(task_id, "active")
    if not root.is_dir():
        raise FileNotFoundError(f"No active workspace for task_id={task_id!r}: {root}")
    return root


def create_workspace(
    task_id: str | None = None,
    request_text: str = "",
    metadata: dict[str, Any] | None = None,
) -> Path:
    """
    Create ``data/workspaces/active/<task_id>/`` with REQUEST.md, ROUTE.json,
    and minimal placeholders for the other standard files.
    """
    tid = task_id or _gen_task_id()
    root = workspace_path(tid, "active")
    if root.exists():
        raise FileExistsError(f"Workspace already exists: {root}")

    root.mkdir(parents=True)

    (root / _REQUEST).write_text(request_text, encoding="utf-8")
    route_payload = dict(metadata) if metadata else {}
    (root / _ROUTE).write_text(
        json.dumps(route_payload, indent=2, default=str),
        encoding="utf-8",
    )

    (root / _AGENT).write_text("", encoding="utf-8")
    (root / _CONTEXT).write_text("", encoding="utf-8")
    (root / _PLAN).write_text("{}", encoding="utf-8")
    (root / _POLICY_DECISION).write_text("{}", encoding="utf-8")
    (root / _APPROVAL).write_text("", encoding="utf-8")
    (root / _EXECUTION_LOG).write_text("", encoding="utf-8")
    (root / _RESULT).write_text("", encoding="utf-8")

    return root


def write_request(task_id: str, text: str) -> Path:
    """Overwrite REQUEST.md for an active workspace."""
    root = _active_root(task_id)
    path = root / _REQUEST
    path.write_text(text, encoding="utf-8")
    return path


def write_plan(task_id: str, plan: Plan | dict[str, Any]) -> Path:
    """Write PLAN.json from a Plan model or dict."""
    root = _active_root(task_id)
    path = root / _PLAN
    if isinstance(plan, Plan):
        payload = plan_to_dict(plan)
    else:
        payload = plan
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def write_policy_decision(task_id: str, decision: PolicyDecision | dict[str, Any]) -> Path:
    """Write POLICY_DECISION.json from a PolicyDecision or dict."""
    root = _active_root(task_id)
    path = root / _POLICY_DECISION
    if isinstance(decision, PolicyDecision):
        payload = asdict(decision)
    else:
        payload = decision
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def append_execution_log(task_id: str, entry: dict[str, Any]) -> Path:
    """Append one JSON object as a line to EXECUTION_LOG.jsonl."""
    root = _active_root(task_id)
    path = root / _EXECUTION_LOG
    line_obj = dict(entry)
    if "timestamp" not in line_obj:
        line_obj["timestamp"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line_obj, default=str) + "\n")
    return path


def write_result(task_id: str, markdown: str) -> Path:
    """Overwrite RESULT.md."""
    root = _active_root(task_id)
    path = root / _RESULT
    path.write_text(markdown, encoding="utf-8")
    return path


def write_approval(
    task_id: str,
    markdown: str,
    state: _STATE = "active",
) -> Path:
    """Overwrite APPROVAL.md for a workspace in the given state."""
    root = workspace_path(task_id, state)
    if not root.is_dir():
        raise FileNotFoundError(f"No {state} workspace for task_id={task_id!r}: {root}")
    path = root / _APPROVAL
    path.write_text(markdown, encoding="utf-8")
    return path


def write_agent(
    task_id: str,
    markdown: str,
    state: _STATE = "active",
) -> Path:
    """Overwrite AGENT.md for a workspace in the given state."""
    root = workspace_path(task_id, state)
    if not root.is_dir():
        raise FileNotFoundError(f"No {state} workspace for task_id={task_id!r}: {root}")
    path = root / _AGENT
    path.write_text(markdown, encoding="utf-8")
    return path


def write_context(
    task_id: str,
    markdown: str,
    state: _STATE = "active",
) -> Path:
    """Overwrite CONTEXT.md for a workspace in the given state."""
    root = workspace_path(task_id, state)
    if not root.is_dir():
        raise FileNotFoundError(f"No {state} workspace for task_id={task_id!r}: {root}")
    path = root / _CONTEXT
    path.write_text(markdown, encoding="utf-8")
    return path


def move_workspace(task_id: str, destination: _MoveDest) -> Path:
    """
    Move ``active/<task_id>`` to ``completed`` or ``rejected``.
    """
    if destination not in ("completed", "rejected"):
        raise ValueError("destination must be 'completed' or 'rejected'")

    src = workspace_path(task_id, "active")
    if not src.is_dir():
        raise FileNotFoundError(f"No active workspace {task_id!r} at {src}")

    dst_parent = _COMPLETED if destination == "completed" else _REJECTED
    dst_parent.mkdir(parents=True, exist_ok=True)
    dst = dst_parent / task_id
    if dst.exists():
        raise FileExistsError(f"Target already exists: {dst}")

    shutil.move(str(src), str(dst))
    return dst
