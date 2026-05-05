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

from plans import Plan, plan_to_dict, validate_storage_id
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
_PATCH_PROPOSAL = "PATCH_PROPOSAL.md"

_WORKSPACE_STATES: set[str] = {"active", "completed", "rejected"}
_STANDARD_WORKSPACE_FILES: tuple[str, ...] = (
    _REQUEST,
    _ROUTE,
    _AGENT,
    _CONTEXT,
    _PLAN,
    _POLICY_DECISION,
    _APPROVAL,
    _EXECUTION_LOG,
    _RESULT,
    _PATCH_PROPOSAL,
)

_WORKSPACE_FILE_SET: set[str] = set(_STANDARD_WORKSPACE_FILES)


def _validate_state(state: str) -> Literal["active", "completed", "rejected"]:
    if state not in _WORKSPACE_STATES:
        raise ValueError(f"Invalid workspace state: {state!r}")
    return state  # type: ignore[return-value]


def _validate_filename(filename: str) -> str:
    if not isinstance(filename, str) or not filename:
        raise ValueError("Filename is required.")
    if "/" in filename or "\\" in filename:
        raise ValueError("Filename must not contain path separators.")
    if ".." in filename:
        raise ValueError("Filename must not contain traversal ('..').")
    # Absolute paths are rejected; this should cover Windows drive letters too.
    if Path(filename).is_absolute():
        raise ValueError("Filename must be a plain file name, not an absolute path.")
    if filename not in _WORKSPACE_FILE_SET:
        raise ValueError(f"Unknown workspace filename: {filename!r}")
    return filename


def _validate_task_id(task_id: str) -> str:
    return validate_storage_id(task_id, field_name="task_id")


def list_workspaces(
    state: Literal["active", "completed", "rejected"],
) -> list[dict]:
    """
    List workspaces in a state as review summaries (read-only).
    """
    state = _validate_state(state)
    state_dir = _state_dir(state)  # may not exist
    if not state_dir.is_dir():
        return []

    summaries: list[dict] = []
    for entry in sorted(state_dir.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        summaries.append(read_workspace_summary(entry.name, state))
    return summaries


def read_workspace_summary(
    task_id: str,
    state: Literal["active", "completed", "rejected"],
) -> dict:
    """
    Return a compact review summary for a single workspace.
    """
    state = _validate_state(state)
    root = workspace_path(task_id, state)
    if not root.is_dir():
        raise FileNotFoundError(f"No {state} workspace for task_id={task_id!r}.")

    rel_ws_path = str(root.relative_to(_WORKSPACES_ROOT)).replace("\\", "/")

    present: list[str] = []
    missing: list[str] = []
    for fn in _STANDARD_WORKSPACE_FILES:
        if (root / fn).is_file():
            present.append(fn)
        else:
            missing.append(fn)

    plan_json: dict[str, Any] | None = None
    policy_decision_json: dict[str, Any] | None = None
    if (root / _PLAN).is_file():
        try:
            plan_json = json.loads((root / _PLAN).read_text(encoding="utf-8"))
        except Exception:
            plan_json = None
    if (root / _POLICY_DECISION).is_file():
        try:
            policy_decision_json = json.loads(
                (root / _POLICY_DECISION).read_text(encoding="utf-8")
            )
        except Exception:
            policy_decision_json = None

    approval_text: str | None = None
    if (root / _APPROVAL).is_file():
        approval_text = (root / _APPROVAL).read_text(encoding="utf-8", errors="replace")

    result_text: str | None = None
    if (root / _RESULT).is_file():
        result_text = (root / _RESULT).read_text(encoding="utf-8", errors="replace")

    patch_proposal_present = (root / _PATCH_PROPOSAL).is_file()

    execution_log_count = 0
    if (root / _EXECUTION_LOG).is_file():
        try:
            with (root / _EXECUTION_LOG).open("r", encoding="utf-8", errors="replace") as f:
                execution_log_count = sum(1 for _ in f)
        except Exception:
            execution_log_count = 0

    return {
        "task_id": task_id,
        "state": state,
        "path": rel_ws_path,
        "files": {"present": present, "missing": missing},
        "plan_json": plan_json,
        "policy_decision_json": policy_decision_json,
        "approval_text": approval_text,
        "result_text": result_text,
        "patch_proposal_present": patch_proposal_present,
        "execution_log_count": execution_log_count,
    }


def read_workspace_file(
    task_id: str,
    state: Literal["active", "completed", "rejected"],
    filename: str,
) -> dict:
    """
    Return a single workspace file's content (read-only), with safe filename validation.
    """
    state = _validate_state(state)
    root = workspace_path(task_id, state)
    if not root.is_dir():
        raise FileNotFoundError(f"No {state} workspace for task_id={task_id!r}.")

    filename = _validate_filename(filename)
    file_path = (root / filename).resolve()
    ws_root_resolved = root.resolve()
    try:
        file_path.relative_to(ws_root_resolved)
    except ValueError:
        raise ValueError("Resolved file escaped workspace root.")

    exists = file_path.is_file()
    content_type: str
    if filename.endswith(".md"):
        content_type = "markdown"
    elif filename.endswith(".json"):
        content_type = "json"
    elif filename.endswith(".jsonl"):
        content_type = "jsonl"
    else:
        content_type = "text"

    content: str | None = None
    if exists:
        content = file_path.read_text(encoding="utf-8", errors="replace")

    return {
        "task_id": task_id,
        "state": state,
        "filename": filename,
        "exists": exists,
        "content_type": content_type,
        "content": content,
    }

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
    return _state_dir(state) / _validate_task_id(task_id)


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


def write_patch_proposal(
    task_id: str,
    *,
    target_path: str,
    summary: str,
    patch: str,
    applied: bool,
) -> Path:
    """Write PATCH_PROPOSAL.md in an active workspace."""
    root = _active_root(task_id)
    path = root / _PATCH_PROPOSAL
    content = (
        "# Patch Proposal\n\n"
        f"Target: {target_path}\n"
        "Summary:\n"
        f"{summary}\n\n"
        f"Applied: {str(applied).lower()}\n"
        "Patch:\n"
        "```diff\n"
        f"{patch}\n"
        "```\n"
    )
    path.write_text(content, encoding="utf-8")
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


def write_route(
    task_id: str,
    route: dict[str, Any],
    state: _STATE = "active",
) -> Path:
    """Overwrite ROUTE.json for a workspace in the given state."""
    root = workspace_path(task_id, state)
    if not root.is_dir():
        raise FileNotFoundError(f"No {state} workspace for task_id={task_id!r}: {root}")
    path = root / _ROUTE
    path.write_text(json.dumps(route, indent=2, default=str), encoding="utf-8")
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
        # Idempotent for the same task id: replace only this destination folder.
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()

    shutil.move(str(src), str(dst))
    return dst
