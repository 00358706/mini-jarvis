"""
approvals.py — Store plan JSON on disk under data/plans/ (no execution).

Transitions: pending → approved | rejected; approved → executed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from plans import Plan, plan_from_dict, plan_to_dict, validate_plan_id

logger = logging.getLogger("gateway.approvals")

# ──────────────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────────────

_PLANS_ROOT = Path(__file__).resolve().parent / "data" / "plans"

_SUBDIRS = ("pending", "approved", "rejected", "executed")

PlanFolder = Literal["pending", "approved", "rejected", "executed"]


def _subdir(name: str) -> Path:
    return _PLANS_ROOT / name


def _ensure_trees() -> None:
    _PLANS_ROOT.mkdir(parents=True, exist_ok=True)
    for s in _SUBDIRS:
        _subdir(s).mkdir(parents=True, exist_ok=True)


def _path_for(plan_id: str, status: PlanFolder) -> Path:
    safe_id = validate_plan_id(plan_id)
    base = _subdir(status).resolve()
    path = (base / f"{safe_id}.json").resolve()
    try:
        path.relative_to(base)
    except ValueError:
        raise ValueError("plan_id resolved outside plan storage.") from None
    return path


# ──────────────────────────────────────────────────────────────────────────────
# Transitions
# ──────────────────────────────────────────────────────────────────────────────


def save_pending_plan(plan: Plan) -> Path:
    """Write ``plan`` to pending (overwrites same plan_id). Returns path written."""
    _ensure_trees()
    path = _path_for(plan.plan_id, "pending")
    body = plan_to_dict(plan)
    body["status"] = "pending_approval"
    text = json.dumps(body, indent=2, default=str)
    path.write_text(text, encoding="utf-8")
    logger.info("approvals | saved pending plan | %s", plan.plan_id)
    return path


def approve_plan(plan_id: str) -> Path:
    """Move pending → approved."""
    _ensure_trees()
    src = _path_for(plan_id, "pending")
    if not src.is_file():
        raise FileNotFoundError(f"No pending plan {plan_id!r} at {src}")
    data = json.loads(src.read_text(encoding="utf-8"))
    data["status"] = "approved"
    dst = _path_for(plan_id, "approved")
    dst.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    src.unlink()
    logger.info("approvals | approved | %s", plan_id)
    return dst


def reject_plan(plan_id: str, reason: str | None = None) -> Path:
    """Move pending → rejected; optional reason stored on the JSON."""
    _ensure_trees()
    src = _path_for(plan_id, "pending")
    if not src.is_file():
        raise FileNotFoundError(f"No pending plan {plan_id!r} at {src}")
    data = json.loads(src.read_text(encoding="utf-8"))
    data["status"] = "rejected"
    if reason:
        data["rejection_reason"] = reason
    dst = _path_for(plan_id, "rejected")
    dst.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    src.unlink()
    logger.info("approvals | rejected | %s", plan_id)
    return dst


def mark_executed(plan_id: str, result: Any | None = None) -> Path:
    """Move approved → executed; optional ``result`` appended to stored JSON."""
    _ensure_trees()
    src = _path_for(plan_id, "approved")
    if not src.is_file():
        raise FileNotFoundError(f"No approved plan {plan_id!r} at {src}")
    data = json.loads(src.read_text(encoding="utf-8"))
    data["status"] = "executed"
    if result is not None:
        data["execution_result"] = result
    dst = _path_for(plan_id, "executed")
    dst.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    src.unlink()
    logger.info("approvals | executed | %s", plan_id)
    return dst


# ──────────────────────────────────────────────────────────────────────────────
# Queries
# ──────────────────────────────────────────────────────────────────────────────


def load_plan(
    plan_id: str,
    status: PlanFolder = "pending",
) -> Plan:
    """Load plan JSON from disk and validate."""
    path = _path_for(plan_id, status)
    if not path.is_file():
        raise FileNotFoundError(f"No {status} plan {plan_id!r} at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return plan_from_dict(data)


def list_pending_plans() -> list[str]:
    """Return plan ids (filenames without .json) under pending."""
    _ensure_trees()
    return sorted(p.stem for p in _subdir("pending").glob("*.json"))
