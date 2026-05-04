"""
audit.py — Structured audit log and event store.

Responsibility:
  - Maintain an in-memory ring buffer of AuditEntry records.
  - Provide a queryable log (GET /logs) and event feed (GET /events).
  - Never block the hot path — append is O(1).

Design notes:
  - Ring buffer capped at MAX_ENTRIES (default 10 000) to bound memory use.
  - Two views:
      /logs   → all entries (ingest, route, tool, error)
      /events → entries where kind == "event" (device/sensor triggers)
  - Thread-safe: uses a plain list + asyncio.Lock (single-process, no threads
    in practice; lock is there for correctness if a background thread ever
    appends).
  - No persistence — entries are lost on restart. Add a SQLite/Redis backend
    here when durability is needed.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any, Literal

from models import AuditEntry

# ──────────────────────────────────────────────────────────────────────────────
# Store
# ──────────────────────────────────────────────────────────────────────────────

MAX_ENTRIES: int = 10_000

_store: deque[AuditEntry] = deque(maxlen=MAX_ENTRIES)
_lock: asyncio.Lock = asyncio.Lock()


async def append(
    *,
    kind: Literal["ingest", "route", "tool", "drop", "error", "event", "lifecycle"],
    input_summary: str,
    decision: str | None = None,
    route: str | None = None,
    tool: str | None = None,
    result_summary: str | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEntry:
    """
    Append a structured entry to the audit log.
    Returns the entry so callers can inspect it if needed.
    """
    entry = AuditEntry(
        kind=kind,
        input=input_summary,
        decision=decision,
        route=route,
        tool=tool,
        result=result_summary,
        error=error,
        metadata=metadata or {},
        timestamp=datetime.now(timezone.utc),
    )
    async with _lock:
        _store.append(entry)
    return entry


# ──────────────────────────────────────────────────────────────────────────────
# Query helpers (used by /logs and /events endpoints)
# ──────────────────────────────────────────────────────────────────────────────


async def all_entries(limit: int = 200) -> list[AuditEntry]:
    """Return the most recent `limit` entries across all kinds."""
    async with _lock:
        entries = list(_store)
    return entries[-limit:]


async def event_entries(limit: int = 200) -> list[AuditEntry]:
    """Return the most recent `limit` entries where kind == 'event'."""
    async with _lock:
        entries = [e for e in _store if e.kind == "event"]
    return entries[-limit:]
