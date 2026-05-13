"""
main.py — Agentic Gateway, Phase 4

Phase 4:
  - Single /ingest path with unified GatewayResponse (status, routed_to, result,
    fail_reason, timestamp).
  - Deterministic Ollama classifier (temp=0); LOCAL_TOOLS on /ingest is gated
    (no direct tool execution). Approved plan execution still uses the sandbox subprocess.

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
import re
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import audit
import registry as reg
from agent_loader import get_agent_tool_policy, load_agent
from approvals import (
    approve_plan,
    compute_plan_sha256,
    list_pending_plans,
    load_plan_storage_dict,
    mark_executed,
    plan_already_executed,
    reject_plan,
    save_pending_plan,
    storage_dict_to_plan,
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
from plans import Plan, PlanLimits, PlanStep, create_plan_id, validate_plan_id
from policy import evaluate_plan
from tools import run_installed_tool
from workspace import (
    append_execution_log,
    create_workspace,
    list_workspaces,
    move_workspace,
    write_patch_proposal,
    read_workspace_summary,
    read_workspace_file,
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


class PlanFromMessageRequest(BaseModel):
    message: str
    agent: str
    plan_id: str | None = None


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


def _write_workspace_policy_state(plan: Plan, decision: dict) -> None:
    _ensure_workspace_for_plan(plan)
    write_plan(plan.plan_id, plan)
    write_policy_decision(plan.plan_id, decision)


def _write_workspace_agent_context(plan: Plan, agent_tool_policy_note: str | None = None) -> None:
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
        + (f"- Agent tool policy: {agent_tool_policy_note}\n\n" if agent_tool_policy_note else "")
        +
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
    Normalises → classifies → routes → returns structured response.
    ``LOCAL_TOOLS`` classifications are gated: they do not execute installed tools
    or invoke the sandbox from this path; use ``/plans/*`` for proposal, explicit
    approval, and execution. All activity is written to the audit log (GET /logs).
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
    base_decision = evaluate_plan(plan, installed_tools=_installed_tool_names())
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
        _write_workspace_policy_state(plan, policy_out)
        _write_workspace_agent_context(plan, agent_tool_policy_note=agent_tool_policy_note)
        if not allowed:
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


def _extract_simple_filename(message: str) -> str | None:
    """
    Extract a simple repo-relative filename token like README.md from message.
    Rejects separators to avoid paths in this first version.
    """
    m = re.search(r"(?i)\b([A-Z0-9][A-Z0-9_.-]{0,127}\.[A-Z0-9]{1,8})\b", message)
    if not m:
        return None
    token = m.group(1).strip()
    if "/" in token or "\\" in token:
        return None
    return token


def _build_project_maintainer_plan_from_message(
    *,
    message: str,
    agent: str,
    plan_id: str,
) -> Plan:
    """
    Deterministic first version (no LLM planner): build a single-step Plan.
    """
    msg = (message or "").strip()
    msg_l = msg.lower()

    tool = "list_project_files"
    args: dict = {"root": ".", "max_results": 200}
    desc = "List repository files (safe discovery)."

    # Explicitly ignore attempts to request non-maintainer tools.
    if "radarr_search" in msg_l or "radarr" in msg_l or "sonarr" in msg_l or "sabnzbd" in msg_l:
        tool = "list_project_files"
        args = {"root": ".", "max_results": 200}
        desc = "Safe fallback: list repository files (maintainer tools only)."
    elif ("search" in msg_l) or ("find references" in msg_l) or ("find reference" in msg_l):
        tool = "search_repo"
        query = None
        # Prefer extracting a token after "for", e.g. "search repo for PATCH_PROPOSAL.md"
        mm = re.search(r"(?i)\bfor\s+['\"]?([A-Z0-9_.-]{1,200})['\"]?\b", msg)
        if mm:
            query = mm.group(1).strip()
        if not query:
            # Fall back to a short query derived from the message.
            query = msg[:200]
        args = {"query": query, "root": ".", "max_results": 50, "max_file_size_bytes": 100000}
        desc = "Literal search over repository text files."
    elif ("list files" in msg_l) or ("show files" in msg_l) or ("list project files" in msg_l):
        tool = "list_project_files"
        args = {"root": ".", "max_results": 200}
        desc = "List repository files."
    elif ("inspect" in msg_l) or ("read file" in msg_l) or ("read " in msg_l):
        fn = _extract_simple_filename(msg)
        if fn:
            tool = "inspect_file"
            args = {"path": fn}
            desc = "Read a repository file for review."
        else:
            tool = "list_project_files"
            args = {"root": ".", "max_results": 200}
            desc = "Safe fallback: list repository files (no filename detected)."

    summary = msg if msg else "Plan proposed from message."
    if len(summary) > 200:
        summary = summary[:200] + "…"

    return Plan(
        plan_id=plan_id,
        summary=summary,
        agent=agent,
        risk="level_0",
        requires_approval=True,
        steps=[
            PlanStep(step_id="step_1", tool=tool, args=args, description=desc),
        ],
        limits=PlanLimits(
            max_tool_calls=6,
            max_runtime_seconds=90,
            allow_cloud=False,
            allow_delete=False,
        ),
        status="proposed",
    )


@app.post("/plans/from-message")
async def plans_from_message(req: PlanFromMessageRequest):
    """
    Frontend convenience endpoint for proposal creation only.
    Builds a deterministic single-step plan and routes through /plans/propose logic.
    Does not execute tools or approve plans.
    """
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

    if agent == "project_maintainer_agent":
        plan = _build_project_maintainer_plan_from_message(
            message=message, agent=agent, plan_id=plan_id
        )
    else:
        # Minimal first version: do not guess tools for unknown agents.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported agent for /plans/from-message: {agent!r}",
        )

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


@app.get("/plans/pending")
async def plans_pending_list():
    """Plan API — non-breaking planning/approval layer. No execution."""
    plan_ids = list_pending_plans()
    return {"count": len(plan_ids), "plans": plan_ids}


@app.get("/plans/pending/{plan_id}")
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
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
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
    verify approved content hash, re-check policy, then run each step via
    `run_installed_tool` (registry + schema + sandbox).
    Does not call models. Pending or proposed plans are not executable here.
    """
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

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

    ok_steps = sum(1 for s in step_results if s["status"] == "ok")
    err_steps = len(step_results) - ok_steps
    exec_status = "executed_success" if err_steps == 0 else "executed_with_errors"

    response_body = {
        "status": exec_status,
        "plan_id": plan_id,
        "steps": step_results,
    }

    mark_executed(plan_id, result=response_body)
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
        result_summary=f"status={exec_status}",
    )

    return response_body


# ──────────────────────────────────────────────────────────────────────────────
# Workspace review API (read-only)
# ──────────────────────────────────────────────────────────────────────────────


_WORKSPACE_STATE_VALUES = {"active", "completed", "rejected"}
_WORKSPACE_FILENAME_TRAILER_LIMIT = 255


@app.get("/workspaces")
async def workspaces_list(state: str = Query(default="active")):
    """
    Workspace review API — list readable workspace summaries (read-only).
    """
    if state not in _WORKSPACE_STATE_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state.")
    summaries = list_workspaces(state)  # type: ignore[arg-type]
    return {"count": len(summaries), "workspaces": summaries}


@app.get("/workspaces/{state}/{task_id}")
async def workspace_summary_endpoint(state: str, task_id: str):
    if state not in _WORKSPACE_STATE_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state.")
    try:
        return read_workspace_summary(task_id=task_id, state=state)  # type: ignore[arg-type]
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None


@app.get("/workspaces/{state}/{task_id}/files/{filename}")
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


@app.get("/workspaces/{state}/{task_id}/compact")
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
