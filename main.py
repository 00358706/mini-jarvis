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

import logging
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

import audit
import registry as reg
from config import cfg
from dispatch import process
from ingestion import normalise
from models import (
    GatewayResponse,
    IngestRequest,
    ToolApprovalRequest,
    ToolProposal,
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
