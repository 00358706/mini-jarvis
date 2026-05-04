"""
tools.py — Tool execution layer (Phase 4).

Phase 4 change: all tool execution goes through sandbox.run()
instead of direct function calls. The tool functions still exist
in this module (imported by the sandbox subprocess) but the
gateway itself never calls them directly.

Ring 1 (model) → proposes intent
Ring 2 (gateway) → validates against registry
Ring 3 (sandbox) → executes in isolation
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import registry as reg
import sandbox
from http_allowlist import validate_http_destination
from models import NormalisedEnvelope, ToolResult

logger = logging.getLogger("gateway.tools")


def _http_policy_block(
    tool_name: str, full_url: str, approved_base_url: str
) -> ToolResult | None:
    """Return a ToolResult error if the URL is outside the configured service base."""
    err = validate_http_destination(full_url, approved_base_url)
    if err:
        return ToolResult(tool_name=tool_name, success=False, error=err)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Tool implementations
# (These are imported by the sandbox subprocess — keep them self-contained)
# ──────────────────────────────────────────────────────────────────────────────


async def radarr_search(args: dict) -> ToolResult:
    title: str = args.get("title", "").strip()
    if not title:
        return ToolResult(
            tool_name="radarr_search", success=False, error="No title provided."
        )
    import os

    params = {"term": title, "apikey": os.getenv("RADARR_API_KEY", "")}
    url = os.getenv("RADARR_URL", "http://localhost:7878")
    lookup_url = f"{url}/api/v3/movie/lookup"
    blocked = _http_policy_block("radarr_search", lookup_url, url)
    if blocked:
        return blocked
    try:
        async with httpx.AsyncClient(
            timeout=float(os.getenv("TOOL_TIMEOUT", "15"))
        ) as client:
            resp = await client.get(lookup_url, params=params)
            resp.raise_for_status()
            results = resp.json()
    except httpx.HTTPError as exc:
        return ToolResult(tool_name="radarr_search", success=False, error=str(exc))
    return ToolResult(
        tool_name="radarr_search",
        success=True,
        data={"count": len(results), "results": results[:5]},
    )


async def radarr_add(args: dict) -> ToolResult:
    title: str = args.get("title", "").strip()
    if not title:
        return ToolResult(
            tool_name="radarr_add", success=False, error="No title provided."
        )
    import os

    api_key = os.getenv("RADARR_API_KEY", "")
    url = os.getenv("RADARR_URL", "http://localhost:7878")
    timeout = float(os.getenv("TOOL_TIMEOUT", "15"))
    lookup_url = f"{url}/api/v3/movie/lookup"
    blocked = _http_policy_block("radarr_add", lookup_url, url)
    if blocked:
        return blocked
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            lookup = await client.get(
                lookup_url, params={"term": title, "apikey": api_key}
            )
            lookup.raise_for_status()
            candidates = lookup.json()
    except httpx.HTTPError as exc:
        return ToolResult(tool_name="radarr_add", success=False, error=str(exc))
    if not candidates:
        return ToolResult(
            tool_name="radarr_add", success=False, error=f"Movie not found: {title}"
        )
    movie = candidates[0]
    payload = {
        "title": movie["title"],
        "tmdbId": movie["tmdbId"],
        "qualityProfileId": 1,
        "rootFolderPath": "/movies",
        "monitored": True,
        "addOptions": {"searchForMovie": True},
        "apikey": api_key,
    }
    post_url = f"{url}/api/v3/movie"
    blocked_post = _http_policy_block("radarr_add", post_url, url)
    if blocked_post:
        return blocked_post
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(post_url, json=payload)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        return ToolResult(tool_name="radarr_add", success=False, error=str(exc))
    return ToolResult(
        tool_name="radarr_add",
        success=True,
        data={"added": movie["title"], "year": movie.get("year")},
    )


async def sonarr_search(args: dict) -> ToolResult:
    title: str = args.get("title", "").strip()
    if not title:
        return ToolResult(
            tool_name="sonarr_search", success=False, error="No title provided."
        )
    import os

    params = {"term": title, "apikey": os.getenv("SONARR_API_KEY", "")}
    url = os.getenv("SONARR_URL", "http://localhost:8989")
    lookup_url = f"{url}/api/v3/series/lookup"
    blocked = _http_policy_block("sonarr_search", lookup_url, url)
    if blocked:
        return blocked
    try:
        async with httpx.AsyncClient(
            timeout=float(os.getenv("TOOL_TIMEOUT", "15"))
        ) as client:
            resp = await client.get(lookup_url, params=params)
            resp.raise_for_status()
            results = resp.json()
    except httpx.HTTPError as exc:
        return ToolResult(tool_name="sonarr_search", success=False, error=str(exc))
    return ToolResult(
        tool_name="sonarr_search",
        success=True,
        data={"count": len(results), "results": results[:5]},
    )


async def sonarr_add(args: dict) -> ToolResult:
    title: str = args.get("title", "").strip()
    if not title:
        return ToolResult(
            tool_name="sonarr_add", success=False, error="No title provided."
        )
    import os

    api_key = os.getenv("SONARR_API_KEY", "")
    url = os.getenv("SONARR_URL", "http://localhost:8989")
    timeout = float(os.getenv("TOOL_TIMEOUT", "15"))
    lookup_url = f"{url}/api/v3/series/lookup"
    blocked = _http_policy_block("sonarr_add", lookup_url, url)
    if blocked:
        return blocked
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            lookup = await client.get(
                lookup_url, params={"term": title, "apikey": api_key}
            )
            lookup.raise_for_status()
            candidates = lookup.json()
    except httpx.HTTPError as exc:
        return ToolResult(tool_name="sonarr_add", success=False, error=str(exc))
    if not candidates:
        return ToolResult(
            tool_name="sonarr_add", success=False, error=f"Series not found: {title}"
        )
    series = candidates[0]
    payload = {
        "title": series["title"],
        "tvdbId": series["tvdbId"],
        "qualityProfileId": 1,
        "rootFolderPath": "/tv",
        "monitored": True,
        "addOptions": {"searchForMissingEpisodes": True},
        "apikey": api_key,
    }
    post_url = f"{url}/api/v3/series"
    blocked_post = _http_policy_block("sonarr_add", post_url, url)
    if blocked_post:
        return blocked_post
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(post_url, json=payload)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        return ToolResult(tool_name="sonarr_add", success=False, error=str(exc))
    return ToolResult(
        tool_name="sonarr_add", success=True, data={"added": series["title"]}
    )


async def sabnzbd_queue(args: dict) -> ToolResult:
    import os

    params = {
        "apikey": os.getenv("SABNZBD_API_KEY", ""),
        "output": "json",
        "mode": "queue",
    }
    url = os.getenv("SABNZBD_URL", "http://localhost:8090")
    api_url = f"{url}/api"
    blocked = _http_policy_block("sabnzbd_queue", api_url, url)
    if blocked:
        return blocked
    try:
        async with httpx.AsyncClient(
            timeout=float(os.getenv("TOOL_TIMEOUT", "15"))
        ) as client:
            resp = await client.get(api_url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        return ToolResult(tool_name="sabnzbd_queue", success=False, error=str(exc))
    queue = data.get("queue", {})
    return ToolResult(
        tool_name="sabnzbd_queue",
        success=True,
        data={
            "status": queue.get("status"),
            "speed": queue.get("speed"),
            "eta": queue.get("eta"),
            "items": len(queue.get("slots", [])),
        },
    )


async def sabnzbd_pause(args: dict) -> ToolResult:
    import os

    params = {
        "apikey": os.getenv("SABNZBD_API_KEY", ""),
        "output": "json",
        "mode": "pause",
    }
    url = os.getenv("SABNZBD_URL", "http://localhost:8090")
    api_url = f"{url}/api"
    blocked = _http_policy_block("sabnzbd_pause", api_url, url)
    if blocked:
        return blocked
    try:
        async with httpx.AsyncClient(
            timeout=float(os.getenv("TOOL_TIMEOUT", "15"))
        ) as client:
            resp = await client.get(api_url, params=params)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        return ToolResult(tool_name="sabnzbd_pause", success=False, error=str(exc))
    return ToolResult(tool_name="sabnzbd_pause", success=True, data={"paused": True})


async def sabnzbd_resume(args: dict) -> ToolResult:
    import os

    params = {
        "apikey": os.getenv("SABNZBD_API_KEY", ""),
        "output": "json",
        "mode": "resume",
    }
    url = os.getenv("SABNZBD_URL", "http://localhost:8090")
    api_url = f"{url}/api"
    blocked = _http_policy_block("sabnzbd_resume", api_url, url)
    if blocked:
        return blocked
    try:
        async with httpx.AsyncClient(
            timeout=float(os.getenv("TOOL_TIMEOUT", "15"))
        ) as client:
            resp = await client.get(api_url, params=params)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        return ToolResult(tool_name="sabnzbd_resume", success=False, error=str(exc))
    return ToolResult(tool_name="sabnzbd_resume", success=True, data={"resumed": True})


# ──────────────────────────────────────────────────────────────────────────────
# Registry — name → implementation (subprocess worker resolves by name)
# ──────────────────────────────────────────────────────────────────────────────

_TOOL_FUNCS: dict[str, Any] = {
    "radarr_search": radarr_search,
    "radarr_add": radarr_add,
    "sonarr_search": sonarr_search,
    "sonarr_add": sonarr_add,
    "sabnzbd_queue": sabnzbd_queue,
    "sabnzbd_pause": sabnzbd_pause,
    "sabnzbd_resume": sabnzbd_resume,
}


async def run_tool_by_name(name: str, args: dict) -> ToolResult:
    """Invoke a built-in tool by registry name (used from sandbox_worker)."""
    fn = _TOOL_FUNCS.get(name)
    if fn is None:
        return ToolResult(
            tool_name=name,
            success=False,
            error=f"Unknown tool implementation: {name}",
        )
    return await fn(args)


def validate_args_against_schema(
    args: dict,
    schema: dict[str, Any],
) -> tuple[bool, str | None]:
    """
    Lightweight validation for registry input_schema dicts.

    Schema shape per field:
      {"field_name": {"type": "string", "required": true}}
    """
    for field_name, spec in schema.items():
        if not isinstance(spec, dict):
            continue
        required = bool(spec.get("required"))
        if required:
            if field_name not in args:
                return False, f"Missing required field '{field_name}'."
            val = args.get(field_name)
            if val is None or (isinstance(val, str) and not val.strip()):
                return False, f"Required field '{field_name}' is empty."

        if field_name not in args:
            continue

        val = args[field_name]
        want = spec.get("type")
        if want == "string" and not isinstance(val, str):
            return False, f"Field '{field_name}' must be a string."
        if want == "integer" and not isinstance(val, int):
            return False, f"Field '{field_name}' must be an integer."
        if want == "number" and not isinstance(val, (int, float)):
            return False, f"Field '{field_name}' must be a number."

    return True, None


# ──────────────────────────────────────────────────────────────────────────────
# Intent map
# ──────────────────────────────────────────────────────────────────────────────

_INTENT_MAP: list[tuple[str, str]] = [
    ("sabnzbd pause", "sabnzbd_pause"),
    ("pause download", "sabnzbd_pause"),
    ("sabnzbd resume", "sabnzbd_resume"),
    ("resume download", "sabnzbd_resume"),
    ("download queue", "sabnzbd_queue"),
    ("sabnzbd queue", "sabnzbd_queue"),
    ("sabnzbd status", "sabnzbd_queue"),
    ("add movie", "radarr_add"),
    ("download movie", "radarr_add"),
    ("search movie", "radarr_search"),
    ("find movie", "radarr_search"),
    ("add show", "sonarr_add"),
    ("add series", "sonarr_add"),
    ("download show", "sonarr_add"),
    ("search show", "sonarr_search"),
    ("find show", "sonarr_search"),
    ("search series", "sonarr_search"),
]


def _parse_intent(envelope: NormalisedEnvelope) -> tuple[str | None, dict]:
    # Use preprocessed text_content if available (handles voice/image input)
    text = (envelope.text_content or "").lower()
    if not text and envelope.modality == "text":
        text = str(envelope.content).lower()
    if not text and envelope.modality == "event":
        text = str(envelope.content.get("action", "")).lower()

    for keyword, tool_key in _INTENT_MAP:
        if keyword in text:
            return tool_key, _extract_args(text, tool_key)
    return None, {}


def _extract_args(text: str, tool_key: str) -> dict:
    args: dict = {}
    if tool_key in ("radarr_search", "radarr_add"):
        for prefix in ("add movie", "download movie", "search movie", "find movie"):
            if prefix in text:
                rest = text.split(prefix, 1)[-1].strip()
                if rest:
                    args["title"] = rest
                break
    elif tool_key in ("sonarr_search", "sonarr_add"):
        for prefix in (
            "add show",
            "add series",
            "download show",
            "search show",
            "find show",
            "search series",
        ):
            if prefix in text:
                rest = text.split(prefix, 1)[-1].strip()
                if rest:
                    args["title"] = rest
                break
    return args


# ──────────────────────────────────────────────────────────────────────────────
# Public execute — now routes through sandbox
# ──────────────────────────────────────────────────────────────────────────────


def _exec_meta_ms(t0: float) -> tuple[float, bool, bool]:
    """(duration_ms, executed_in_sandbox_worker, sandbox_timeout) for pre-sandbox exits."""
    return (
        round((time.perf_counter() - t0) * 1000.0, 3),
        False,
        False,
    )


async def execute(envelope: NormalisedEnvelope) -> ToolResult:
    """
    Parse intent → validate registry → execute in sandbox.
    The gateway (Ring 2) validates. The sandbox (Ring 3) executes.
    The model (Ring 1) never reaches here directly.
    """
    t_exec = time.perf_counter()
    tool_key, args = _parse_intent(envelope)

    if tool_key is None:
        logger.info("tools | no intent matched | source=%s", envelope.source_device)
        d_ms, in_w, to = _exec_meta_ms(t_exec)
        return ToolResult(
            tool_name="none",
            success=False,
            error="No matching tool intent found in input.",
            execution_duration_ms=d_ms,
            executed_in_sandbox_worker=in_w,
            sandbox_timeout=to,
        )

    # Registry gate
    registry_entry = reg.get_installed(tool_key)
    if registry_entry is None:
        logger.warning("tools | '%s' not installed in registry", tool_key)
        d_ms, in_w, to = _exec_meta_ms(t_exec)
        return ToolResult(
            tool_name=tool_key,
            success=False,
            error=(
                f"Tool '{tool_key}' is not installed. "
                "Use POST /tools/propose → /tools/approve → /tools/install."
            ),
            execution_duration_ms=d_ms,
            executed_in_sandbox_worker=in_w,
            sandbox_timeout=to,
        )

    ok, verr = validate_args_against_schema(args, registry_entry.input_schema)
    if not ok:
        logger.warning("tools | schema validation failed | %s | %s", tool_key, verr)
        d_ms, in_w, to = _exec_meta_ms(t_exec)
        return ToolResult(
            tool_name=tool_key,
            success=False,
            error=verr or "Input validation failed.",
            execution_duration_ms=d_ms,
            executed_in_sandbox_worker=in_w,
            sandbox_timeout=to,
        )

    logger.info("tools | dispatching %s via sandbox | args=%r", tool_key, args)
    start = time.monotonic()

    result = await sandbox.run(tool_name=tool_key, args=args)

    if result.sandbox_elapsed is None:
        result = result.model_copy(
            update={"sandbox_elapsed": time.monotonic() - start},
        )
    return result


async def run_installed_tool(tool_name: str, args: dict[str, Any]) -> ToolResult:
    """
    Run one installed registry tool by explicit name and args.

    Same gate as ``execute()`` after intent resolution: ``get_installed`` →
    ``validate_args_against_schema`` → ``sandbox.run``. Does not parse ingest text.
    """
    t_exec = time.perf_counter()
    registry_entry = reg.get_installed(tool_name)
    if registry_entry is None:
        logger.warning("tools | '%s' not installed in registry (direct call)", tool_name)
        d_ms, in_w, to = _exec_meta_ms(t_exec)
        return ToolResult(
            tool_name=tool_name,
            success=False,
            error=(
                f"Tool '{tool_name}' is not installed. "
                "Use POST /tools/propose → /tools/approve → /tools/install."
            ),
            execution_duration_ms=d_ms,
            executed_in_sandbox_worker=in_w,
            sandbox_timeout=to,
        )

    ok, verr = validate_args_against_schema(args, registry_entry.input_schema)
    if not ok:
        logger.warning(
            "tools | schema validation failed (direct call) | %s | %s",
            tool_name,
            verr,
        )
        d_ms, in_w, to = _exec_meta_ms(t_exec)
        return ToolResult(
            tool_name=tool_name,
            success=False,
            error=verr or "Input validation failed.",
            execution_duration_ms=d_ms,
            executed_in_sandbox_worker=in_w,
            sandbox_timeout=to,
        )

    logger.info("tools | dispatching %s via sandbox (direct) | args=%r", tool_name, args)
    start = time.monotonic()
    result = await sandbox.run(tool_name=tool_name, args=args)
    if result.sandbox_elapsed is None:
        result = result.model_copy(
            update={"sandbox_elapsed": time.monotonic() - start},
        )
    return result
