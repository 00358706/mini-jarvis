"""
plans.py — Structured plan objects for the gateway (no execution).

No model calls, no registry writes, no sandbox. Used by policy and approvals.
"""

from __future__ import annotations

import secrets
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ──────────────────────────────────────────────────────────────────────────────
# Types
# ──────────────────────────────────────────────────────────────────────────────

PlanRisk = Literal[
    "level_0",
    "level_1",
    "level_2",
    "level_3",
    "level_4",
    "level_5",
]

PlanStatus = Literal[
    "proposed",
    "pending_approval",
    "approved",
    "executed",
    "rejected",
    "failed",
]

_SAFE_STORAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def validate_storage_id(value: str, *, field_name: str = "id") -> str:
    """
    Validate ids used as filesystem path segments.

    These ids are not paths: they must be a single conservative ASCII segment.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be non-empty")
    if ".." in cleaned:
        raise ValueError(f"{field_name} must not contain traversal ('..')")
    if not _SAFE_STORAGE_ID_RE.fullmatch(cleaned):
        raise ValueError(
            f"{field_name} may contain only letters, numbers, underscore, dash, and dot"
        )
    return cleaned


def validate_plan_id(plan_id: str) -> str:
    """Validate a plan id before using it for storage."""
    return validate_storage_id(plan_id, field_name="plan_id")

# ──────────────────────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────────────────────


class StepSafety(BaseModel):
    """
    Evidence-only step metadata for review (idempotency, dry-run intent, rollback notes).

    The gateway does not execute compensation, rollback, or dry-run branches from
    these fields in the current implementation; they document intent and review context.
    """

    dry_run: bool = False
    idempotent: bool = False
    idempotency_key: str | None = None
    idempotency_scope: str | None = None
    compensation: str | None = None
    compensation_implemented: bool = False
    rollback_notes: str | None = None

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def _compensation_required_when_implemented(self) -> StepSafety:
        if self.compensation_implemented:
            c = self.compensation
            if not (isinstance(c, str) and c.strip()):
                raise ValueError(
                    "compensation must be non-empty when compensation_implemented is true"
                )
        return self


class PlanStep(BaseModel):
    step_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    safety: StepSafety = Field(default_factory=StepSafety)

    model_config = ConfigDict(extra="ignore")

    @field_validator("tool")
    @classmethod
    def _tool_non_empty(cls, v: str) -> str:
        if not (v and str(v).strip()):
            raise ValueError("tool must be non-empty")
        return v.strip()


class PlanLimits(BaseModel):
    max_tool_calls: int = 6
    max_runtime_seconds: int = 90
    allow_cloud: bool = False
    allow_delete: bool = False

    model_config = ConfigDict(extra="ignore")


class Plan(BaseModel):
    plan_id: str
    summary: str
    agent: str
    risk: PlanRisk
    requires_approval: bool
    steps: list[PlanStep]
    limits: PlanLimits
    status: PlanStatus

    model_config = ConfigDict(extra="ignore")

    @field_validator("plan_id")
    @classmethod
    def _plan_id_safe(cls, v: str) -> str:
        return validate_plan_id(v)

    @field_validator("agent")
    @classmethod
    def _agent_id_safe(cls, v: str) -> str:
        return validate_storage_id(v, field_name="agent")


# ──────────────────────────────────────────────────────────────────────────────
# Serialization helpers
# ──────────────────────────────────────────────────────────────────────────────


def create_plan_id() -> str:
    """Return a new opaque plan identifier (no registry or filesystem side effects)."""
    return f"plan_{secrets.token_hex(12)}"


def plan_to_dict(plan: Plan) -> dict[str, Any]:
    """Serialize a Plan to a JSON-friendly dict matching the plan wire shape."""
    return plan.model_dump(mode="json")


def plan_from_dict(data: dict[str, Any]) -> Plan:
    """Parse and validate a plan dict into a Plan model."""
    return Plan.model_validate(data)
