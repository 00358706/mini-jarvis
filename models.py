"""
models.py — All Pydantic schemas for the Agentic Gateway (Phase 4).

Phase 4 additions:
  LoopInferenceResult   — wraps LLM response with loop dynamics
  FeedbackCorrection    — payload for POST /feedback/correct
  ProposedToolCode      — payload for POST /tools/propose_code
  SystemCapabilities    — response for GET /system/capabilities
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

# ──────────────────────────────────────────────────────────────────────────────
# Ingestion / Normalisation
# ──────────────────────────────────────────────────────────────────────────────


class IngestRequest(BaseModel):
    modality: Literal["text", "image", "voice", "event"] = Field(...)
    content: Any = Field(...)
    source_device: str = Field(...)
    timestamp: datetime | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalisedEnvelope(BaseModel):
    modality: Literal["text", "image", "voice", "event"]
    content: Any
    source_device: str
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Phase 4: preprocessed text for non-text modalities
    text_content: str | None = Field(
        default=None,
        description="Text extracted from voice/image/event for routing.",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Classification / Routing
# ──────────────────────────────────────────────────────────────────────────────

RoutingTarget = Literal["LOCAL_TOOLS", "LOCAL_LLM", "CLOUD_LLM", "DROP"]

ALLOWED_ROUTING_TOKENS: frozenset[str] = frozenset(
    {"LOCAL_TOOLS", "LOCAL_LLM", "CLOUD_LLM", "DROP"}
)


class ClassifierResult(BaseModel):
    target: RoutingTarget
    raw_output: str
    confidence: float = 0.5  # from loop dynamics or adapter
    loop_count: int = 1
    classifier_backend: str = "ollama"


# ──────────────────────────────────────────────────────────────────────────────
# Tool Execution
# ──────────────────────────────────────────────────────────────────────────────


class ToolResult(BaseModel):
    tool_name: str
    success: bool
    data: Any = None
    error: str | None = None
    sandbox_elapsed: float | None = None  # seconds spent in sandbox
    # Execution observability (filled by sandbox / tools.execute; not tool business logic)
    execution_duration_ms: float | None = None
    executed_in_sandbox_worker: bool | None = None
    sandbox_timeout: bool | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Tool Registry (Phase 3+)
# ──────────────────────────────────────────────────────────────────────────────

ToolLifecycleStatus = Literal["proposed", "approved", "installed", "rejected"]


class ToolDefinition(BaseModel):
    name: str
    endpoint: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)
    version: str = "v1"
    description: str = ""
    status: ToolLifecycleStatus = "proposed"


class ToolProposal(BaseModel):
    name: str
    endpoint: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)
    version: str = "v1"
    description: str = ""


class ToolApprovalRequest(BaseModel):
    name: str
    version: str = "v1"
    reason: str = ""


class ProposedToolCode(BaseModel):
    """
    Phase 4: A model-generated tool proposal including runnable Python code.
    Code is tested in the sandbox before being submitted for human approval.
    The model proposes → sandbox tests → human approves → gateway installs.
    """

    name: str = Field(..., description="Tool identifier.")
    description: str = Field(..., description="What this tool does.")
    code: str = Field(..., description="Complete Python async function implementation.")
    fn_name: str = Field(..., description="Name of the async function in the code.")
    input_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)
    test_args: dict[str, Any] = Field(
        default_factory=dict,
        description="Args to use when sandbox-testing the proposed code.",
    )
    version: str = "v1"


# ──────────────────────────────────────────────────────────────────────────────
# Audit Log (Phase 3+)
# ──────────────────────────────────────────────────────────────────────────────


class AuditEntry(BaseModel):
    kind: Literal["ingest", "route", "tool", "drop", "error", "event", "lifecycle"]
    input: str
    decision: str | None = None
    route: str | None = None
    tool: str | None = None
    result: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


# ──────────────────────────────────────────────────────────────────────────────
# Feedback (Phase 4)
# ──────────────────────────────────────────────────────────────────────────────


class FeedbackCorrection(BaseModel):
    """Human correction for a misrouted request."""

    text: str = Field(..., description="The input text that was misrouted.")
    correct_label: RoutingTarget = Field(
        ..., description="What it should have been routed to."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Gateway Response
# ──────────────────────────────────────────────────────────────────────────────


class GatewayResponse(BaseModel):
    """
    Standard API envelope. Required logical fields per Phase 4:
      status, routed_to, result, fail_reason, timestamp
    """

    status: Literal["ok", "error"]
    routed_to: RoutingTarget | str | None = None
    result: Any = None
    fail_reason: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    envelope: NormalisedEnvelope | None = None
    error: str | None = None
    loop_info: dict[str, Any] | None = None
