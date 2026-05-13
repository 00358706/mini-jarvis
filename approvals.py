"""
approvals.py — Store plan JSON on disk under data/plans/ (no execution).

Transitions: pending → approved | rejected; approved → executed.

Plan approval is bound to a canonical SHA-256 of the plan core (server-computed).
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Literal

from notifications import append_pending_approval_notification
from plans import Plan, plan_from_dict, plan_to_dict, validate_plan_id

logger = logging.getLogger("gateway.approvals")

# ──────────────────────────────────────────────────────────────────────────────
# Canonical plan hash (server-owned; never trust client-supplied hash fields)
# ──────────────────────────────────────────────────────────────────────────────

# Excluded from the canonical core digest (lifecycle / envelope only).
_EXCLUDE_FROM_PLAN_CORE: frozenset[str] = frozenset(
    {
        "status",
        "reviewed_plan_sha256",
        "approved_plan_sha256",
        "execution_result",
        "rejection_reason",
        "executed_at",
        "approved_at",
        "rejected_at",
    }
)

# Never persist client-supplied digest fields; always recompute.
_CLIENT_HASH_KEYS: frozenset[str] = frozenset(
    {"reviewed_plan_sha256", "approved_plan_sha256"}
)


def canonical_plan_core(plan_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Return a copy of ``plan_dict`` with lifecycle/server-only keys removed,
    suitable for stable JSON canonicalization before hashing.
    """
    return {k: v for k, v in plan_dict.items() if k not in _EXCLUDE_FROM_PLAN_CORE}


def compute_plan_sha256(plan_dict: dict[str, Any]) -> str:
    """
    Deterministic SHA-256 (hex) of the canonical plan core: sort_keys, compact
    separators, UTF-8, excluding lifecycle-only fields.
    """
    core = canonical_plan_core(plan_dict)
    payload = json.dumps(
        core,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _strip_client_hash_fields(body: dict[str, Any]) -> None:
    for k in _CLIENT_HASH_KEYS:
        body.pop(k, None)


def storage_dict_to_plan(data: dict[str, Any]) -> Plan:
    """Build a validated ``Plan`` from on-disk JSON (ignores storage-only keys)."""
    allowed = set(Plan.model_fields.keys())
    core = {k: v for k, v in data.items() if k in allowed}
    return plan_from_dict(core)


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


def load_plan_storage_dict(plan_id: str, status: PlanFolder) -> dict[str, Any]:
    """Load raw plan JSON from disk (includes server hash fields)."""
    path = _path_for(plan_id, status)
    if not path.is_file():
        raise FileNotFoundError(f"No {status} plan {plan_id!r} at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def plan_already_executed(plan_id: str) -> bool:
    """True if an executed record exists and there is no approved copy."""
    _ensure_trees()
    ex = _path_for(plan_id, "executed")
    ap = _path_for(plan_id, "approved")
    return ex.is_file() and not ap.is_file()


# ──────────────────────────────────────────────────────────────────────────────
# Transitions
# ──────────────────────────────────────────────────────────────────────────────


def save_pending_plan(plan: Plan) -> Path:
    """Write ``plan`` to pending (overwrites same plan_id). Returns path written."""
    _ensure_trees()
    path = _path_for(plan.plan_id, "pending")
    body = plan_to_dict(plan)
    _strip_client_hash_fields(body)
    body["status"] = "pending_approval"
    body["reviewed_plan_sha256"] = compute_plan_sha256(body)
    text = json.dumps(body, indent=2, default=str)
    path.write_text(text, encoding="utf-8")
    logger.info("approvals | saved pending plan | %s", plan.plan_id)
    try:
        append_pending_approval_notification(plan)
    except Exception:
        logger.exception(
            "approvals | pending approval notification append failed | %s", plan.plan_id
        )
    return path


def approve_plan(plan_id: str) -> Path:
    """
    Move pending → approved.

    Requires ``reviewed_plan_sha256`` on the pending document and verifies it
    matches a fresh digest of the plan core. Sets ``approved_plan_sha256``.
    """
    _ensure_trees()
    src = _path_for(plan_id, "pending")
    if not src.is_file():
        raise FileNotFoundError(f"No pending plan {plan_id!r} at {src}")
    data = json.loads(src.read_text(encoding="utf-8"))
    stored_reviewed = data.get("reviewed_plan_sha256")
    if not isinstance(stored_reviewed, str) or not stored_reviewed.strip():
        raise ValueError(
            "Pending plan is missing server-reviewed_plan_sha256 "
            "(re-propose the plan; legacy pending plans without hashes cannot be approved)."
        )
    current = compute_plan_sha256(data)
    if current != stored_reviewed:
        raise ValueError(
            "Plan content no longer matches reviewed_plan_sha256; "
            "approval refused (plan was modified after review snapshot)."
        )
    data["status"] = "approved"
    data["approved_plan_sha256"] = current
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
    data = load_plan_storage_dict(plan_id, status)
    return storage_dict_to_plan(data)


def list_pending_plans() -> list[str]:
    """Return plan ids (filenames without .json) under pending."""
    _ensure_trees()
    return sorted(p.stem for p in _subdir("pending").glob("*.json"))
