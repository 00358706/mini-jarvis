"""
tools_http.py — Approved HTTP client surface for tool execution.

Used by ``tools.py`` (sandbox subprocess) and ``sandbox.execute_http_tool``.
Centralizes ``httpx`` so static guards can forbid direct HTTP client imports
elsewhere on the tool execution surface.

Call sites should continue using :func:`http_allowlist.validate_http_destination`
where URLs are built from configuration. This module does **not** yet enforce
registry-wide ``http_allowlist`` metadata; that remains future work.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

# Re-export for ``except tools_http.HTTPError`` at call sites.
HTTPError = httpx.HTTPError


@asynccontextmanager
async def async_http_client(timeout: float = 15.0) -> AsyncIterator[httpx.AsyncClient]:
    """Async context manager yielding an ``httpx.AsyncClient`` with the given timeout."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        yield client


def sync_post_json_raise(
    url: str,
    json_body: dict[str, Any],
    *,
    timeout_seconds: float = 15.0,
) -> tuple[Any, int]:
    """
    Synchronous JSON POST; ``raise_for_status`` then return ``(parsed_json, status_code)``.

    Caller is responsible for registry / URL policy before invoking.
    """
    with httpx.Client(timeout=timeout_seconds) as client:
        resp = client.post(url, json=json_body)
        resp.raise_for_status()
        return resp.json(), resp.status_code
