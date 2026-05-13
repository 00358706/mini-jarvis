from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from workspace import list_workspaces, read_workspace_file, read_workspace_summary

router = APIRouter()

_WORKSPACE_STATE_VALUES = {"active", "completed", "rejected"}
_WORKSPACE_FILENAME_TRAILER_LIMIT = 255


@router.get("/workspaces")
async def workspaces_list(state: str = Query(default="active")):
    """
    Workspace review API — list readable workspace summaries (read-only).
    """
    if state not in _WORKSPACE_STATE_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state.")
    summaries = list_workspaces(state)  # type: ignore[arg-type]
    return {"count": len(summaries), "workspaces": summaries}


@router.get("/workspaces/{state}/{task_id}")
async def workspace_summary_endpoint(state: str, task_id: str):
    if state not in _WORKSPACE_STATE_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state.")
    try:
        return read_workspace_summary(task_id=task_id, state=state)  # type: ignore[arg-type]
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None


@router.get("/workspaces/{state}/{task_id}/files/{filename}")
async def workspace_file_endpoint(state: str, task_id: str, filename: str):
    if state not in _WORKSPACE_STATE_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state.")
    if not filename or len(filename) > _WORKSPACE_FILENAME_TRAILER_LIMIT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename.") from None
    try:
        return read_workspace_file(task_id=task_id, state=state, filename=filename)  # type: ignore[arg-type]
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None


def _extract_execution_status_from_result_text(text: str) -> str | None:
    """
    Extract execution status from RESULT.md text.

    Accepts:
      - "- status: `executed_success`"
      - "- status: executed_success"
    """
    if not text or not isinstance(text, str):
        return None
    m = re.search(
        r"(?im)^\s*-\s*status\s*:\s*`?([A-Za-z0-9_]+)`?\s*$",
        text,
    )
    if not m:
        return None
    return m.group(1).strip()


@router.get("/workspaces/{state}/{task_id}/compact")
async def workspace_compact_summary_endpoint(state: str, task_id: str):
    """
    Workspace review API — compact, approval-card style summary (read-only).

    This endpoint is intentionally read-only: it does not execute tools, approve plans,
    or mutate any workspace files.
    """
    if state not in _WORKSPACE_STATE_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state.")

    try:
        ws = read_workspace_summary(task_id=task_id, state=state)  # type: ignore[arg-type]
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    plan_json = ws.get("plan_json") if isinstance(ws.get("plan_json"), dict) else {}
    policy_decision = ws.get("policy_decision_json") if isinstance(ws.get("policy_decision_json"), dict) else {}

    agent = plan_json.get("agent") if isinstance(plan_json.get("agent"), str) else "unknown_agent"
    risk = plan_json.get("risk") if isinstance(plan_json.get("risk"), str) else "level_0"
    plan_status = plan_json.get("status") if isinstance(plan_json.get("status"), str) else "proposed"

    # Extract approval status from the readable APPROVAL.md mirror.
    approval_text = ws.get("approval_text")
    approval_status = None
    if isinstance(approval_text, str) and approval_text.strip():
        m = re.search(r"(?im)\\bStatus\\s*:\\s*([A-Za-z_]+)\\b", approval_text)
        if m:
            approval_status = m.group(1).strip()
    if not approval_status:
        # For active workspaces, this is the common UX default.
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
            step_id = s.get("step_id")
            tool = s.get("tool")
            args = s.get("args")
            description = s.get("description")
            if not isinstance(tool, str):
                continue
            steps.append(
                {
                    "step_id": str(step_id) if isinstance(step_id, str) else "",
                    "tool": tool,
                    "args": args if isinstance(args, dict) else {},
                    "description": str(description) if isinstance(description, str) else "",
                }
            )

    result_text = ws.get("result_text")
    result_present = isinstance(result_text, str) and bool(result_text.strip())
    execution_log_count = ws.get("execution_log_count")
    try:
        log_count = int(execution_log_count or 0)
    except Exception:
        log_count = 0

    execution_status = None
    if state == "completed" and isinstance(result_text, str) and result_text.strip():
        execution_status = _extract_execution_status_from_result_text(result_text)

    recommended_next_action = "review_then_approve_or_reject" if state == "active" else "review_results"
    review_summary = (
        f"agent={agent} policy.allowed={str(policy_allowed).lower()} approval={approval_status or 'n/a'} "
        + (
            f"execution={execution_status}" if execution_status else "execution=not_started"
        )
    )

    files_present = []
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
        "review": {
            "summary": review_summary,
            "recommended_next_action": recommended_next_action,
        },
    }
