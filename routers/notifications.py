from __future__ import annotations

from fastapi import APIRouter

from notifications import read_pending_approval_notifications

router = APIRouter()


@router.get("/notifications/pending-approvals")
async def notifications_pending_approvals():
    """
    Read-only: latest pending-approval notification records (informational only).

    Does not approve, reject, execute, or mutate registry. Operators still use
    ``POST /plans/{plan_id}/approve`` and ``POST /plans/{plan_id}/execute`` with
    an approval-capable key and valid hashes; see ``GET /plans/pending/{plan_id}``
    for ``reviewed_plan_sha256``.
    """
    rows = read_pending_approval_notifications()
    return {"notifications": rows, "count": len(rows)}
