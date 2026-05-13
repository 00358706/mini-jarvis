from __future__ import annotations

from fastapi import APIRouter, Query

import audit

router = APIRouter()


@router.get("/logs")
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


@router.get("/events")
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
