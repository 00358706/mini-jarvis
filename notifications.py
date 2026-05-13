"""
Append-only local notifications for operator visibility (not authority).

Pending-approval records are written to ``data/notifications/pending_approvals.jsonl``
(one JSON object per line, UTF-8). Re-proposing the same ``plan_id`` appends another
line (append-only visibility, not a deduplicated inbox).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from plans import Plan

logger = logging.getLogger("gateway.notifications")

_REPO = Path(__file__).resolve().parent
NOTIFICATIONS_DIR: Path = _REPO / "data" / "notifications"
PENDING_APPROVALS_JSONL: Path = NOTIFICATIONS_DIR / "pending_approvals.jsonl"
PENDING_APPROVALS_READ_CAP_DEFAULT = 200


def append_pending_approval_notification(plan: Plan) -> None:
    """Append one informational record when a plan is saved as pending approval."""
    NOTIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "notification_id": str(uuid.uuid4()),
        "type": "pending_approval",
        "plan_id": plan.plan_id,
        "agent": plan.agent,
        "summary": plan.summary,
        "risk": plan.risk,
        "requires_approval": plan.requires_approval,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workspace": {
            "state": "active",
            "summary_url": f"/workspaces/active/{plan.plan_id}",
        },
        "action_required": "review_plan",
        "side_effect": "none",
        "can_approve": False,
        "can_execute": False,
    }
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n"
    with PENDING_APPROVALS_JSONL.open("a", encoding="utf-8") as f:
        f.write(line)


def read_pending_approval_notifications(
    *, limit: int = PENDING_APPROVALS_READ_CAP_DEFAULT
) -> list[dict]:
    """
    Return the latest ``limit`` notification records from the JSONL file, oldest first
    within the returned window. No mutation. Missing file yields an empty list.
    """
    if not PENDING_APPROVALS_JSONL.is_file():
        return []
    text = PENDING_APPROVALS_JSONL.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    cap = max(0, int(limit))
    tail = lines[-cap:] if cap else lines
    out: list[dict] = []
    for line in tail:
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                out.append(row)
        except json.JSONDecodeError:
            logger.warning("Skipping invalid JSONL line in pending approvals notifications")
    return out
