from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import audit
from agent_loader import get_agent_tool_policy
from approvals import (
    PlanTransitionLockTimeout,
    _mark_executed_body,
    approve_plan,
    async_plan_transition_lock,
    compute_plan_sha256,
    list_pending_plans,
    load_plan_storage_dict,
    plan_already_executed,
    reject_plan,
    save_pending_plan,
    storage_dict_to_plan,
)
from plans import Plan, create_plan_id, validate_plan_id
from services.plan_builder import (
    BuildMissingCapability,
    BuildUnsupportedAgent,
    build_plan_from_message,
)
from services.workspace_mirror import (
    workspace_exists_active,
    write_workspace_agent_context,
    write_workspace_policy_state,
)
from workspace import (
    append_execution_log,
    move_workspace,
    write_patch_proposal,
    write_approval,
    write_result,
    workspace_path,
)

logger = logging.getLogger("gateway")

router = APIRouter()


class PlanRejectRequest(BaseModel):
    reason: str | None = None


class PlanFromMessageRequest(BaseModel):
    message: str
    agent: str
    plan_id: str | None = None


def plan_transition_locked_exc(plan_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "status": "plan_transition_locked",
            "plan_id": plan_id,
            "message": "execution or transition already in progress.",
        },
    )


@router.post("/plans/propose")
async def plans_propose(plan: Plan):
    """
    Plan API — non-breaking planning/approval layer. No execution.

    Policy-check a structured plan; optionally persist as pending approval.
    Does not call sandbox, tools, or models.
    """
    import main as _gw

    base_decision = _gw.evaluate_plan(plan, installed_tools=_gw._installed_tool_names())
    reasons = list(base_decision.reasons)
    allowed = bool(base_decision.allowed)

    agent_tool_policy_note: str | None = None
    agent_id = (plan.agent or "").strip()
    if agent_id:
        tool_policy = get_agent_tool_policy(agent_id)
        if tool_policy is None:
            note = (
                f"Agent '{agent_id}' tools.yaml allowlist missing/unparseable; "
                "no additional agent-tool constraint enforced."
            )
            reasons.append(note)
            agent_tool_policy_note = note
        else:
            mode = str(tool_policy.get("mode") or "advisory").lower()
            allowed_tools = tool_policy.get("allowed_tools")
            if not isinstance(allowed_tools, set):
                allowed_tools = set()
            blocked = [step.tool for step in plan.steps if step.tool not in allowed_tools]
            if blocked and mode == "strict":
                for t in blocked:
                    reasons.append(
                        f"Tool {t} is not allowed by agent {agent_id} tools.yaml strict policy."
                    )
                allowed = False
                agent_tool_policy_note = (
                    f"strict mode blocked: {', '.join(blocked)}"
                )
            elif blocked:
                note = (
                    f"Agent '{agent_id}' advisory tools policy would block: "
                    + ", ".join(blocked)
                )
                reasons.append(note)
                agent_tool_policy_note = note
            else:
                agent_tool_policy_note = (
                    f"All plan tools are in agent '{agent_id}' allowed_tools (mode={mode})."
                )
    else:
        reasons.append("No plan.agent supplied; no additional agent-tool constraint enforced.")
        agent_tool_policy_note = "No plan.agent supplied."

    policy_out = {"allowed": allowed, "reasons": reasons}

    try:
        write_workspace_policy_state(plan, policy_out)
        write_workspace_agent_context(plan, agent_tool_policy_note=agent_tool_policy_note)
        if not allowed:
            write_result(
                plan.plan_id,
                "# Result\n\nPolicy rejected the proposed plan.\n",
            )
            if workspace_exists_active(plan.plan_id):
                move_workspace(plan.plan_id, "rejected")
    except Exception as exc:
        logger.exception("plans/propose workspace mirror failed for %s", plan.plan_id)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "workspace_write_error",
                "plan_id": plan.plan_id,
                "policy": policy_out,
                "error": f"Workspace mirror failed: {exc}",
            },
        )

    if not allowed:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "status": "policy_rejected",
                "plan_id": plan.plan_id,
                "policy": policy_out,
            },
        )

    if plan.requires_approval:
        try:
            await asyncio.to_thread(save_pending_plan, plan)
        except PlanTransitionLockTimeout:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "status": "plan_transition_locked",
                    "plan_id": plan.plan_id,
                    "message": "execution or transition already in progress.",
                },
            )
        try:
            approval_path = workspace_path(plan.plan_id, state="active") / "APPROVAL.md"
            approval_path.write_text(
                "# Approval\n\nStatus: pending_approval\n",
                encoding="utf-8",
            )
        except Exception as exc:
            logger.exception("plans/propose approval workspace write failed for %s", plan.plan_id)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "status": "workspace_write_error",
                    "plan_id": plan.plan_id,
                    "policy": policy_out,
                    "error": f"Workspace mirror failed: {exc}",
                },
            )
        await audit.append(
            kind="plan",
            input_summary=f"Plan proposed: {plan.plan_id}",
            result_summary="status=pending_approval",
        )
        return {
            "status": "pending_approval",
            "plan_id": plan.plan_id,
            "policy": policy_out,
        }

    try:
        write_result(
            plan.plan_id,
            "# Result\n\nPolicy allowed. Execution was not started from /plans/propose.\n",
        )
    except Exception as exc:
        logger.exception("plans/propose result workspace write failed for %s", plan.plan_id)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "workspace_write_error",
                "plan_id": plan.plan_id,
                "policy": policy_out,
                "error": f"Workspace mirror failed: {exc}",
            },
        )
    return {
        "status": "policy_allowed_not_executed",
        "plan_id": plan.plan_id,
        "policy": policy_out,
        "note": "Plan execution is not wired into this endpoint yet.",
    }


@router.post("/plans/from-message")
async def plans_from_message(req: PlanFromMessageRequest):
    """
    Frontend convenience endpoint for proposal creation only.
    Uses services.plan_builder (deterministic); on success routes through /plans/propose logic.
    Does not execute tools or approve plans.
    """
    import main as _gw

    agent = (req.agent or "").strip()
    if not agent:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="agent is required.")

    raw_plan_id = (req.plan_id or "").strip() or create_plan_id()
    try:
        plan_id = validate_plan_id(raw_plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="message is required.")

    built = build_plan_from_message(
        message=message,
        agent=agent,
        plan_id=plan_id,
        installed_tool_names=_gw._installed_tool_names(),
    )
    if isinstance(built, BuildUnsupportedAgent):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=built.detail)
    elif isinstance(built, BuildMissingCapability):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "status": "missing_capability",
                "reason": built.reason_code,
                "detail": built.detail,
                "hint": built.hint,
                "proposal_needed": built.proposal_needed,
                "agent": agent,
                "plan_id": plan_id,
            },
        )
    else:
        plan = built.plan

    resp = await plans_propose(plan)
    if isinstance(resp, JSONResponse):
        # Mirror /plans/propose status code, but wrap with the Open WebUI friendly shape.
        try:
            body = json.loads((resp.body or b"{}").decode("utf-8", errors="replace"))
        except Exception:
            body = {}
        status_text = body.get("status") or "policy_rejected"
        policy_obj = body.get("policy") if isinstance(body, dict) else None
        content = {
            "status": status_text,
            "plan_id": plan_id,
            "agent": agent,
            "policy": policy_obj,
            "workspace": {
                "state": "rejected",
                "summary_url": f"/workspaces/rejected/{plan_id}",
            },
        }
        return JSONResponse(status_code=resp.status_code, content=content)

    # Normal pending_approval shape.
    out = dict(resp) if isinstance(resp, dict) else {}
    return {
        "status": out.get("status", "pending_approval"),
        "plan_id": out.get("plan_id", plan_id),
        "agent": agent,
        "policy": out.get("policy"),
        "workspace": {
            "state": "active",
            "summary_url": f"/workspaces/active/{plan_id}",
        },
    }


@router.get("/plans/pending")
async def plans_pending_list():
    """Plan API — non-breaking planning/approval layer. No execution."""
    plan_ids = list_pending_plans()
    return {"count": len(plan_ids), "plans": plan_ids}


@router.get("/plans/pending/{plan_id}")
async def plans_pending_get(plan_id: str):
    """Plan API — non-breaking planning/approval layer. No execution."""
    try:
        raw = load_plan_storage_dict(plan_id, "pending")
        p = storage_dict_to_plan(raw)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pending plan {plan_id!r} not found.",
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    out = p.model_dump(mode="json")
    h = raw.get("reviewed_plan_sha256")
    if isinstance(h, str) and h.strip():
        out["reviewed_plan_sha256"] = h.strip()
    return out


@router.post("/plans/{plan_id}/approve")
async def plans_approve(plan_id: str):
    """Plan API — non-breaking planning/approval layer. No execution."""
    try:
        await asyncio.to_thread(approve_plan, plan_id)
    except PlanTransitionLockTimeout:
        raise plan_transition_locked_exc(plan_id) from None
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pending plan {plan_id!r} not found.",
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
    try:
        write_approval(
            plan_id,
            "# Approval\n\nStatus: approved\n",
            state="active",
        )
    except FileNotFoundError:
        # Workspace mirror is optional for lifecycle endpoints.
        pass
    except Exception as exc:
        logger.warning("plans/approve workspace update failed for %s: %s", plan_id, exc)
        await audit.append(
            kind="plan",
            input_summary=f"Workspace update failed on approve: {plan_id}",
            result_summary=f"warning={str(exc)[:200]}",
        )
    await audit.append(
        kind="plan",
        input_summary=f"Plan approved: {plan_id}",
        result_summary="status=approved",
    )
    return {"status": "approved", "plan_id": plan_id}


@router.post("/plans/{plan_id}/reject")
async def plans_reject(plan_id: str, req: PlanRejectRequest):
    """Plan API — non-breaking planning/approval layer. No execution."""
    try:
        await asyncio.to_thread(reject_plan, plan_id, req.reason)
    except PlanTransitionLockTimeout:
        raise plan_transition_locked_exc(plan_id) from None
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pending plan {plan_id!r} not found.",
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    try:
        write_approval(
            plan_id,
            f"# Approval\n\nStatus: rejected\n\nReason: {req.reason or 'n/a'}\n",
            state="active",
        )
        write_result(plan_id, "# Result\n\nPlan rejected.\n")
        if workspace_exists_active(plan_id):
            move_workspace(plan_id, "rejected")
    except FileNotFoundError:
        # No workspace to mirror; API success is still valid.
        pass
    except Exception as exc:
        logger.warning("plans/reject workspace update failed for %s: %s", plan_id, exc)
        await audit.append(
            kind="plan",
            input_summary=f"Workspace update failed on reject: {plan_id}",
            result_summary=f"warning={str(exc)[:200]}",
        )
    await audit.append(
        kind="plan",
        input_summary=f"Plan rejected: {plan_id}",
        result_summary=f"status=rejected reason={req.reason or 'n/a'}",
    )
    return {
        "status": "rejected",
        "plan_id": plan_id,
        "reason": req.reason,
    }


@router.post("/plans/{plan_id}/execute")
async def plans_execute(plan_id: str):
    """
    Plan API — execute an **approved** plan only: load from `data/plans/approved/`,
    verify approved content hash, re-check policy, then run each step via
    `run_installed_tool` (registry + schema + sandbox).
    Does not call models. Pending or proposed plans are not executable here.
    """
    import main as _gw

    try:
        async with async_plan_transition_lock(plan_id):
            if plan_already_executed(plan_id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "status": "already_executed",
                        "plan_id": plan_id,
                        "message": "This plan was already executed; re-execution is not allowed.",
                    },
                )

            try:
                raw_approved = load_plan_storage_dict(plan_id, "approved")
            except FileNotFoundError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Plan is not in approved state or was not found under approved plans.",
                ) from None

            stored_hash = raw_approved.get("approved_plan_sha256")
            if not isinstance(stored_hash, str) or not stored_hash.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "approval_hash_missing",
                        "plan_id": plan_id,
                        "message": (
                            "Approved plan is missing approved_plan_sha256; execution refused. "
                            "Re-approve from a current pending plan with server-owned hashes."
                        ),
                    },
                )

            if compute_plan_sha256(raw_approved) != stored_hash.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "plan_hash_mismatch",
                        "plan_id": plan_id,
                        "message": (
                            "Plan content no longer matches approved_plan_sha256; execution refused."
                        ),
                    },
                )

            try:
                plan = storage_dict_to_plan(raw_approved)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from None

            if plan.status != "approved":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Plan status must be approved to execute.",
                )

            decision = _gw.evaluate_plan(plan, installed_tools=_gw._installed_tool_names())
            if not decision.allowed:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "status": "policy_rejected",
                        "plan_id": plan_id,
                        "reasons": decision.reasons,
                    },
                )

            await audit.append(
                kind="plan",
                input_summary=f"Plan execution started: {plan_id}",
                result_summary="status=executing",
            )
            try:
                append_execution_log(
                    plan_id,
                    {
                        "event": "execution_started",
                        "plan_id": plan_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except FileNotFoundError:
                pass
            except Exception as exc:
                logger.warning("plans/execute workspace start log failed for %s: %s", plan_id, exc)
                await audit.append(
                    kind="plan",
                    input_summary=f"Workspace update failed on execute start: {plan_id}",
                    result_summary=f"warning={str(exc)[:200]}",
                )

            step_results: list[dict] = []
            for step in plan.steps:
                tool_result = await _gw.run_installed_tool(step.tool, step.args)
                step_payload = {
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "status": "ok" if tool_result.success else "error",
                    "result": tool_result.model_dump(mode="json"),
                }
                step_results.append(step_payload)
                try:
                    append_execution_log(
                        plan_id,
                        {
                            "event": "step_completed",
                            "plan_id": plan_id,
                            "step_id": step.step_id,
                            "tool": step.tool,
                            "success": tool_result.success,
                            "error": tool_result.error,
                        },
                    )
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    logger.warning(
                        "plans/execute workspace log append failed for %s: %s", plan_id, exc
                    )
                    await audit.append(
                        kind="plan",
                        input_summary=f"Workspace update failed on execute step: {plan_id}",
                        result_summary=f"warning={str(exc)[:200]}",
                    )
                await audit.append(
                    kind="plan",
                    input_summary=f"Plan step {step.step_id} tool={step.tool} plan={plan_id}",
                    result_summary=(
                        "ok"
                        if tool_result.success
                        else (tool_result.error or "error")[:200]
                    ),
                )

            ok_steps = sum(1 for s in step_results if s["status"] == "ok")
            err_steps = len(step_results) - ok_steps
            exec_status = "executed_success" if err_steps == 0 else "executed_with_errors"

            response_body = {
                "status": exec_status,
                "plan_id": plan_id,
                "steps": step_results,
            }

            _mark_executed_body(plan_id, result=response_body)
            try:
                append_execution_log(
                    plan_id,
                    {
                        "event": "execution_completed",
                        "plan_id": plan_id,
                        "status": exec_status,
                    },
                )
                step_lines = "\n".join(
                    (
                        f"- `{s['step_id']}` / `{s['tool']}`: {s['status']}"
                        + (
                            f" — {(s['result'].get('error') or 'error')}"
                            if s["status"] == "error"
                            else ""
                        )
                    )
                    for s in step_results
                ) or "- (no steps)"
                for s in step_results:
                    step_result = s.get("result")
                    if not isinstance(step_result, dict):
                        continue
                    step_data = step_result.get("data")
                    if not isinstance(step_data, dict):
                        continue
                    if step_data.get("proposal_only") is not True:
                        continue
                    patch_text = step_data.get("patch")
                    if not isinstance(patch_text, str) or not patch_text:
                        continue
                    target_path = str(step_data.get("path") or "")
                    summary = str(step_data.get("summary") or "")
                    applied = bool(step_data.get("applied"))
                    write_patch_proposal(
                        plan_id,
                        target_path=target_path,
                        summary=summary,
                        patch=patch_text,
                        applied=applied,
                    )
                    break
                write_result(
                    plan_id,
                    (
                        "# Result\n\n"
                        f"- plan id: `{plan_id}`\n"
                        f"- status: `{exec_status}`\n\n"
                        "## Step summary\n\n"
                        f"{step_lines}\n\n"
                        "## Totals\n\n"
                        f"- Steps total: {len(step_results)}\n"
                        f"- Steps ok: {ok_steps}\n"
                        f"- Steps error: {err_steps}\n"
                        "\n"
                        "Execution ran through the installed tool path with registry/schema checks "
                        "and sandboxed tool execution.\n"
                    ),
                )
                if workspace_exists_active(plan_id):
                    move_workspace(plan_id, "completed")
            except FileNotFoundError:
                pass
            except Exception as exc:
                logger.warning("plans/execute workspace finalize failed for %s: %s", plan_id, exc)
                await audit.append(
                    kind="plan",
                    input_summary=f"Workspace update failed on execute finalize: {plan_id}",
                    result_summary=f"warning={str(exc)[:200]}",
                )

            await audit.append(
                kind="plan",
                input_summary=f"Plan execution completed: {plan_id}",
                result_summary=f"status={exec_status}",
            )

            return response_body
    except PlanTransitionLockTimeout:
        raise plan_transition_locked_exc(plan_id) from None
