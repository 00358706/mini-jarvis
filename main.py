"""
main.py — Agentic Gateway, Phase 4

Phase 4:
  - Single /ingest path with unified GatewayResponse (status, routed_to, result,
    fail_reason, timestamp).
  - Deterministic Ollama classifier (temp=0); tools run via sandbox subprocess.

Phase 3 (retained):
  GET  /logs                 — structured audit log (all entries)
  GET  /events               — audit log filtered to device/sensor events
  GET  /tools                — list all tools in the registry
  GET  /tools/{name}/{version} — inspect a specific tool definition
  POST /tools/propose        — propose a new tool (lifecycle: proposed)
  POST /tools/approve        — approve a proposed tool (→ approved)
  POST /tools/install        — mark an approved tool as installed (→ installed)
  POST /tools/reject         — reject a proposed tool (→ rejected, terminal)

Run:
    python main.py
    # or:
    uvicorn main:app --host 0.0.0.0 --port 8000

Environment variables (see config.py):
    GATEWAY_API_KEY       — required; default is 'change-me-before-use'
    GATEWAY_HOST          — bind address (default 0.0.0.0)
    GATEWAY_PORT          — bind port (default 8000)
    OLLAMA_URL            — Ollama base URL
    CLASSIFIER_MODEL      — Ollama model for classification
    LOCAL_LLM_MODEL       — Ollama model for LOCAL_LLM routing
    OPENROUTER_API_KEY    — required for CLOUD_LLM routing
    RADARR_API_KEY / SONARR_API_KEY / SABNZBD_API_KEY

Example calls:
    # Ingest
    curl -X POST http://localhost:8000/ingest \\
         -H "Content-Type: application/json" \\
         -H "X-API-Key: your-key" \\
         -d '{"modality":"text","content":"add movie inception","source_device":"curl"}'

    # Logs
    curl -H "X-API-Key: your-key" "http://localhost:8000/logs?limit=50"

    # Events
    curl -H "X-API-Key: your-key" "http://localhost:8000/events"

    # Tool registry
    curl -H "X-API-Key: your-key" http://localhost:8000/tools

    # Propose a new tool
    curl -X POST http://localhost:8000/tools/propose \\
         -H "Content-Type: application/json" \\
         -H "X-API-Key: your-key" \\
         -d '{"name":"ping","endpoint":"http://internal/ping","description":"Ping a host","permissions":["net:read"]}'
"""

from __future__ import annotations

import json
import logging
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import audit
import registry as reg
from agent_loader import load_agent
from approvals import (
    approve_plan,
    list_pending_plans,
    load_plan,
    mark_executed,
    reject_plan,
    save_pending_plan,
)
from config import cfg
from dispatch import process
from ingestion import normalise
from models import (
    GatewayResponse,
    IngestRequest,
    ToolApprovalRequest,
    ToolProposal,
)
from plans import Plan
from policy import evaluate_plan
from tools import run_installed_tool
from workspace import (
    append_execution_log,
    create_workspace,
    move_workspace,
    workspace_path,
    write_approval,
    write_agent,
    write_context,
    write_route,
    write_plan,
    write_policy_decision,
    write_request,
    write_result,
)

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("gateway")


def _installed_tool_names() -> set[str]:
    return {t.name for t in reg.installed_tools()}


class PlanRejectRequest(BaseModel):
    reason: str | None = None


def _workspace_exists_active(task_id: str) -> bool:
    return workspace_path(task_id, state="active").is_dir()


def _route_metadata_for_plan(plan: Plan) -> dict:
    return {
        "plan_id": plan.plan_id,
        "agent": plan.agent,
        "risk": plan.risk,
        "requires_approval": plan.requires_approval,
        "status": plan.status,
        "source": "plans_api",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": "/plans/propose",
    }


def _ensure_workspace_for_plan(plan: Plan) -> None:
    route_meta = _route_metadata_for_plan(plan)
    if not _workspace_exists_active(plan.plan_id):
        create_workspace(
            task_id=plan.plan_id,
            request_text="# Request\n\nPlan proposed via /plans/propose.\n",
            metadata=route_meta,
        )
    else:
        write_request(plan.plan_id, "# Request\n\nPlan proposed via /plans/propose.\n")
        write_route(plan.plan_id, route_meta, state="active")


def _write_workspace_policy_state(plan: Plan, decision) -> None:
    _ensure_workspace_for_plan(plan)
    write_plan(plan.plan_id, plan)
    write_policy_decision(plan.plan_id, decision)


def _write_workspace_agent_context(plan: Plan) -> None:
    source_endpoint = "/plans/propose"
    agent_id = (plan.agent or "").strip() or "unknown_agent"
    try:
        cfg = load_agent(agent_id)
        agent_md = (
            f"# Agent context\n\n"
            f"- agent id: `{cfg.agent_id}`\n"
            f"- display name: `{cfg.display_name or 'n/a'}`\n"
            f"- version: `{cfg.version or 'n/a'}`\n"
            f"- purpose: {cfg.purpose or 'n/a'}\n"
            f"- parsed_with_yaml_library: `{cfg.parsed_with_yaml_library}`\n\n"
            f"## agent.yaml summary\n\n"
            f"```json\n{json.dumps(cfg.agent_yaml_data, indent=2, default=str)}\n```\n\n"
            f"## prompt.md\n\n{cfg.prompt_md or '_missing_'}\n\n"
            f"## tools.yaml\n\n```yaml\n{cfg.tools_yaml or '# missing'}\n```\n\n"
            f"## policy.yaml\n\n```yaml\n{cfg.policy_yaml or '# missing'}\n```\n\n"
            f"## examples.md\n\n{cfg.examples_md or '_missing_'}\n"
        )
    except FileNotFoundError:
        agent_md = (
            "# Agent context\n\n"
            f"Agent folder was not found for `{agent_id}`.\n\n"
            "Policy and registry still decide whether a plan is allowed.\n"
        )

    context_md = (
        "# Context\n\n"
        "This is the readable context used for planning/review.\n\n"
        f"- Plan id: `{plan.plan_id}`\n"
        f"- Agent id: `{agent_id}`\n"
        f"- Risk level: `{plan.risk}`\n"
        f"- Requires approval: `{plan.requires_approval}`\n"
        f"- Source endpoint: `{source_endpoint}`\n\n"
        "This workspace is readable state only. Policy, registry, approval state, "
        "and sandbox execution remain authoritative.\n"
    )
    write_agent(plan.plan_id, agent_md, state="active")
    write_context(plan.plan_id, context_md, state="active")


# ──────────────────────────────────────────────────────────────────────────────
# App lifecycle
# ──────────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    installed = reg.installed_tools()
    logger.info("Gateway Phase 3 starting on %s:%s", cfg.host, cfg.port)
    logger.info(
        "Classifier: %s | Local LLM: %s | Cloud: %s",
        cfg.classifier_model,
        cfg.local_llm_model,
        cfg.cloud_model,
    )
    logger.info(
        "Tool registry: %d installed tool(s): %s",
        len(installed),
        ", ".join(t.name for t in installed),
    )
    if cfg.api_key == "change-me-before-use":
        logger.warning(
            "⚠  GATEWAY_API_KEY is set to the default placeholder. "
            "Set a strong secret before exposing to the network."
        )
    yield
    logger.info("Gateway shutting down")


app = FastAPI(
    title="Agentic Gateway",
    version="0.4.0",
    description=(
        "Single ingestion point for all modalities. "
        "Phase 4: deterministic classification, failure taxonomy, sandboxed tools, cloud guard."
    ),
    lifespan=lifespan,
)


# ──────────────────────────────────────────────────────────────────────────────
# Authentication middleware
# ──────────────────────────────────────────────────────────────────────────────


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    provided = request.headers.get("X-API-Key", "")
    if provided != cfg.api_key:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "status": "error",
                "error": "Invalid or missing X-API-Key header.",
            },
        )
    return await call_next(request)


# ──────────────────────────────────────────────────────────────────────────────
# Global error handler
# ──────────────────────────────────────────────────────────────────────────────


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=GatewayResponse(
            status="error",
            routed_to=None,
            result=None,
            fail_reason="EXECUTION_ERROR",
            timestamp=datetime.now(timezone.utc),
            error=str(exc),
        ).model_dump(mode="json"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Core endpoints
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Unauthenticated liveness check."""
    return {
        "status": "ok",
        "phase": 4,
        "host": socket.gethostname(),
        "utc": datetime.now(timezone.utc).isoformat(),
        "installed_tools": len(reg.installed_tools()),
    }


@app.post("/ingest", response_model=GatewayResponse)
async def ingest(request: IngestRequest):
    """
    Main ingestion endpoint. Authenticated via X-API-Key header.
    Normalises → classifies → routes → executes → returns structured response.
    All activity is written to the audit log (queryable via GET /logs).
    """
    envelope = await normalise(request)

    logger.info(
        "ingest | modality=%-6s source=%-20s ts=%s",
        envelope.modality,
        envelope.source_device,
        envelope.timestamp.isoformat(),
    )

    try:
        result = await process(envelope)
    except Exception as exc:
        logger.exception("dispatch.process raised an unhandled exception")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Dispatch error: {exc}",
        ) from exc

    return GatewayResponse(
        status="ok",
        routed_to=result.get("routed_to"),
        result=result,
        fail_reason=result.get("fail_reason"),
        timestamp=datetime.now(timezone.utc),
        envelope=envelope,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Plan API — planning, approval, and approved-only execution (registry + sandbox).
# ──────────────────────────────────────────────────────────────────────────────


@app.post("/plans/propose")
async def plans_propose(plan: Plan):
    """
    Plan API — non-breaking planning/approval layer. No execution.

    Policy-check a structured plan; optionally persist as pending approval.
    Does not call sandbox, tools, or models.
    """
    decision = evaluate_plan(plan, installed_tools=_installed_tool_names())
    policy_out = {"allowed": decision.allowed, "reasons": decision.reasons}

    try:
        _write_workspace_policy_state(plan, decision)
        _write_workspace_agent_context(plan)
        if not decision.allowed:
            write_result(
                plan.plan_id,
                "# Result\n\nPolicy rejected the proposed plan.\n",
            )
            if _workspace_exists_active(plan.plan_id):
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

    if not decision.allowed:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "status": "policy_rejected",
                "plan_id": plan.plan_id,
                "policy": policy_out,
            },
        )

    if plan.requires_approval:
        save_pending_plan(plan)
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


@app.get("/plans/pending")
async def plans_pending_list():
    """Plan API — non-breaking planning/approval layer. No execution."""
    plan_ids = list_pending_plans()
    return {"count": len(plan_ids), "plans": plan_ids}


@app.get("/plans/pending/{plan_id}")
async def plans_pending_get(plan_id: str):
    """Plan API — non-breaking planning/approval layer. No execution."""
    try:
        p = load_plan(plan_id, status="pending")
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pending plan {plan_id!r} not found.",
        ) from None
    return p.model_dump(mode="json")


@app.post("/plans/{plan_id}/approve")
async def plans_approve(plan_id: str):
    """Plan API — non-breaking planning/approval layer. No execution."""
    try:
        approve_plan(plan_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pending plan {plan_id!r} not found.",
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


@app.post("/plans/{plan_id}/reject")
async def plans_reject(plan_id: str, req: PlanRejectRequest):
    """Plan API — non-breaking planning/approval layer. No execution."""
    try:
        reject_plan(plan_id, reason=req.reason)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pending plan {plan_id!r} not found.",
        ) from None
    try:
        write_approval(
            plan_id,
            f"# Approval\n\nStatus: rejected\n\nReason: {req.reason or 'n/a'}\n",
            state="active",
        )
        write_result(plan_id, "# Result\n\nPlan rejected.\n")
        if _workspace_exists_active(plan_id):
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


@app.post("/plans/{plan_id}/execute")
async def plans_execute(plan_id: str):
    """
    Plan API — execute an **approved** plan only: load from `data/plans/approved/`,
    re-check policy, then run each step via `run_installed_tool` (registry + schema + sandbox).
    Does not call models. Pending or proposed plans are not executable here.
    """
    try:
        plan = load_plan(plan_id, status="approved")
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plan is not in approved state or was not found under approved plans.",
        ) from None

    if plan.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plan status must be approved to execute.",
        )

    decision = evaluate_plan(plan, installed_tools=_installed_tool_names())
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

    step_results: list[dict] = []
    for step in plan.steps:
        tool_result = await run_installed_tool(step.tool, step.args)
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
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "status": step_payload["status"],
                    "result": step_payload["result"],
                },
            )
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.warning("plans/execute workspace log append failed for %s: %s", plan_id, exc)
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

    response_body = {
        "status": "executed",
        "plan_id": plan_id,
        "steps": step_results,
    }

    mark_executed(plan_id, result=response_body)
    try:
        ok_steps = sum(1 for s in step_results if s["status"] == "ok")
        err_steps = len(step_results) - ok_steps
        write_result(
            plan_id,
            (
                "# Result\n\n"
                f"Plan executed.\n\n"
                f"- Steps total: {len(step_results)}\n"
                f"- Steps ok: {ok_steps}\n"
                f"- Steps error: {err_steps}\n"
            ),
        )
        if _workspace_exists_active(plan_id):
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
        result_summary="status=executed",
    )

    return response_body


# ──────────────────────────────────────────────────────────────────────────────
# Observability — spec §10
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/logs")
async def get_logs(limit: int = Query(default=200, ge=1, le=10_000)):
    """
    Return the most recent `limit` audit log entries (all kinds).
    Authenticated. Spec §10.
    """
    entries = await audit.all_entries(limit=limit)
    return {
        "count": len(entries),
        "entries": [e.model_dump(mode="json") for e in entries],
    }


@app.get("/events")
async def get_events(limit: int = Query(default=200, ge=1, le=10_000)):
    """
    Return the most recent `limit` device/sensor event entries from the audit log.
    Filters to entries where kind == 'event'. Authenticated. Spec §10.
    """
    entries = await audit.event_entries(limit=limit)
    return {
        "count": len(entries),
        "events": [e.model_dump(mode="json") for e in entries],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Tool registry — spec §6 + §7
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/tools")
async def list_tools():
    """List all tools in the registry (all lifecycle states)."""
    tools = reg.all_tools()
    return {
        "count": len(tools),
        "tools": [t.model_dump(mode="json") for t in tools],
    }


@app.get("/tools/{name}/{version}")
async def get_tool(name: str, version: str):
    """Inspect a specific tool definition by name and version."""
    entry = reg.get(name, version)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{name}:{version}' not found in registry.",
        )
    return entry.model_dump(mode="json")


@app.post("/tools/propose", status_code=status.HTTP_201_CREATED)
async def propose_tool(proposal: ToolProposal):
    """
    Submit a new tool proposal. Status starts as 'proposed'.
    The tool cannot execute until it is approved and installed.
    Spec §7 lifecycle: propose → review → approve → install → register.
    """
    try:
        entry = reg.propose(proposal)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    await audit.append(
        kind="lifecycle",
        input_summary=f"Tool proposed: {proposal.name}:{proposal.version}",
        tool=proposal.name,
        result_summary="status=proposed",
    )
    logger.info("tool lifecycle | proposed | %s:%s", proposal.name, proposal.version)
    return {"status": "proposed", "tool": entry.model_dump(mode="json")}


@app.post("/tools/approve")
async def approve_tool(req: ToolApprovalRequest):
    """
    Approve a proposed tool. Status moves proposed → approved.
    Approved tools still cannot execute until installed.
    """
    try:
        entry = reg.approve(req.name, req.version)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await audit.append(
        kind="lifecycle",
        input_summary=f"Tool approved: {req.name}:{req.version}",
        tool=req.name,
        result_summary=f"status=approved reason={req.reason or 'n/a'}",
    )
    logger.info("tool lifecycle | approved | %s:%s", req.name, req.version)
    return {"status": "approved", "tool": entry.model_dump(mode="json")}


@app.post("/tools/install")
async def install_tool(req: ToolApprovalRequest):
    """
    Mark an approved tool as installed (registered and callable).
    Status moves approved → installed. After this, the tool can execute.
    """
    try:
        entry = reg.install(req.name, req.version)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await audit.append(
        kind="lifecycle",
        input_summary=f"Tool installed: {req.name}:{req.version}",
        tool=req.name,
        result_summary="status=installed",
    )
    logger.info("tool lifecycle | installed | %s:%s", req.name, req.version)
    return {"status": "installed", "tool": entry.model_dump(mode="json")}


@app.post("/tools/reject")
async def reject_tool(req: ToolApprovalRequest):
    """
    Reject a proposed tool. Terminal state — the tool cannot be re-proposed
    under the same name:version key. Submit a new proposal with an updated
    version string if rework is needed.
    """
    try:
        entry = reg.reject(req.name, req.version, reason=req.reason)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await audit.append(
        kind="lifecycle",
        input_summary=f"Tool rejected: {req.name}:{req.version}",
        tool=req.name,
        result_summary=f"status=rejected reason={req.reason or 'n/a'}",
    )
    logger.info(
        "tool lifecycle | rejected | %s:%s | reason=%s",
        req.name,
        req.version,
        req.reason,
    )
    return {"status": "rejected", "tool": entry.model_dump(mode="json")}


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=cfg.host,
        port=cfg.port,
        reload=False,
        log_level="info",
    )
