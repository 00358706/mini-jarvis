"""
main.py — Agentic Gateway, Phase 4

Phase 4:
  - Single /ingest path with unified GatewayResponse (status, routed_to, result,
    fail_reason, timestamp).
  - Deterministic Ollama classifier (temp=0); LOCAL_TOOLS on /ingest is gated
    (no direct tool execution). Approved plan execution still uses the sandbox subprocess.

HTTP routes are composed from ``routers/`` modules; ``dispatch.py`` remains the
ingest lane router (no rename on this branch).

Run:
    python main.py
    # or:
    uvicorn main:app --host 0.0.0.0 --port 8000

Environment variables (see config.py):
    GATEWAY_API_KEY       — master X-API-Key; all routes when present (local default)
    GATEWAY_INPUT_API_KEY — optional; input/proposal POSTs only (see middleware route map)
    GATEWAY_APPROVAL_API_KEY — optional; plan approve/reject/execute + explicit read GETs
    GATEWAY_ADMIN_API_KEY — optional; registry tool lifecycle POSTs + same read GETs
    GATEWAY_HOST          — bind address (default 0.0.0.0)
    GATEWAY_PORT          — bind port (default 8000)
    OLLAMA_URL            — Ollama base URL
    CLASSIFIER_MODEL      — Ollama model for classification
    LOCAL_LLM_MODEL       — Ollama model for LOCAL_LLM routing
    OPENROUTER_API_KEY    — required for CLOUD_LLM routing
    RADARR_API_KEY / SONARR_API_KEY / SABNZBD_API_KEY
"""

from __future__ import annotations

import logging
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

import registry as reg
from config import cfg
from models import GatewayResponse
from policy import evaluate_plan
from routers.ingest import router as ingest_router
from routers.logs import router as logs_router
from routers.notifications import router as notifications_router
from routers.plans import router as plans_router
from routers.tools import router as tools_router
from routers.workspaces import router as workspaces_router
from services.auth_roles import classify_api_key, key_allows_route, route_api_role
from tools import run_installed_tool

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
# Authentication middleware (role-separated API keys)
# ──────────────────────────────────────────────────────────────────────────────


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    provided = request.headers.get("X-API-Key", "")
    key_kind = classify_api_key(provided)
    if key_kind is None:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "status": "error",
                "error": (
                    "Invalid or missing X-API-Key header."
                    if not (provided or "").strip()
                    else "Unknown X-API-Key (not a configured gateway key)."
                ),
            },
        )
    route_role = route_api_role(request.method, request.url.path)
    if not key_allows_route(route_role=route_role, key_kind=key_kind):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "status": "error",
                "error": (
                    f"This X-API-Key is not permitted for {request.method} {request.url.path}. "
                    f"Required role: {route_role}."
                ),
                "route_role": route_role,
                "key_kind": key_kind,
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


app.include_router(ingest_router)
app.include_router(plans_router)
app.include_router(notifications_router)
app.include_router(workspaces_router)
app.include_router(logs_router)
app.include_router(tools_router)

# Test introspection compatibility (same function object as the mounted handler).
from routers.plans import plans_execute  # noqa: E402

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
