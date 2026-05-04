"""
plans.py — Structured plan objects for the gateway (no execution).

No model calls, no registry writes, no sandbox. Used by policy and approvals.
"""

from __future__ import annotations

import secrets
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

# ──────────────────────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────────────────────


class PlanStep(BaseModel):
    step_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    description: str = ""

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
