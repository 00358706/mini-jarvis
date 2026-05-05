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
import fnmatch
from datetime import datetime, timezone
from pathlib import Path, PurePath
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


_INSPECT_MAX_BYTES = 100 * 1024
_PATCH_MAX_BYTES = 100 * 1024
_DEFAULT_TEXT_MAX_BYTES = 100 * 1024
_SECRET_BASENAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.test",
    "secrets.json",
    "credentials.json",
    "id_rsa",
    "id_dsa",
    ".pypirc",
}
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_SECRET_NAME_SUBSTRINGS = ("token", "password", "secret", "credential", "apikey", "api_key")
_DEFAULT_INCLUDE_GLOBS = [
    "*.py",
    "*.md",
    "*.ps1",
    "*.sh",
    "*.yaml",
    "*.yml",
    "*.json",
]
_MANDATORY_EXCLUDE_DIRS = [
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "data/workspaces",
    "data/plans",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _is_secret_name(path_obj: Path) -> bool:
    name = path_obj.name.lower()
    if name in _SECRET_BASENAMES:
        return True
    if name.endswith(_SECRET_SUFFIXES):
        return True
    if any(s in name for s in _SECRET_NAME_SUBSTRINGS):
        return True
    return False


def _resolve_repo_path(
    *,
    raw_path: str,
    repo_root: Path,
) -> tuple[Path | None, str | None]:
    """
    Resolve a user-supplied path against repo_root with traversal protection.
    Returns (resolved_path, error_message).
    """
    requested = raw_path.strip()
    pure = PurePath(requested)
    if ".." in pure.parts:
        return None, "Path traversal ('..') is not allowed."

    requested_path = Path(requested)
    if requested_path.is_absolute():
        candidate = requested_path.resolve()
    else:
        candidate = (repo_root / requested_path).resolve()

    try:
        candidate.relative_to(repo_root)
    except ValueError:
        return None, "Path must stay inside the repository root."

    return candidate, None


def _normalize_globs(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                s = item.strip()
                if s:
                    out.append(s)
        return out
    return []


def _normalize_str_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                s = item.strip()
                if s:
                    out.append(s)
        return out
    return []


def _matches_any_glob(path_str: str, globs: list[str]) -> bool:
    if not globs:
        return True
    return any(fnmatch.fnmatch(path_str, g) for g in globs)


def _is_probably_binary(path_obj: Path) -> bool:
    try:
        with path_obj.open("rb") as f:
            chunk = f.read(4096)
        return b"\x00" in chunk
    except OSError:
        return True


def _repo_relative_file(path_obj: Path, repo_root: Path) -> str | None:
    """
    Return a repo-relative path for non-symlinked files that resolve inside repo_root.
    """
    try:
        if path_obj.is_symlink() or path_obj.is_dir():
            return None
        path_obj.resolve().relative_to(repo_root)
        return str(path_obj.relative_to(repo_root)).replace("\\", "/")
    except Exception:
        return None


def _exclude_prefixes(extra_exclude_dirs: object = None) -> list[str]:
    exclude_dirs = [*_MANDATORY_EXCLUDE_DIRS, *_normalize_str_list(extra_exclude_dirs)]
    prefixes: list[str] = []
    for d in exclude_dirs:
        d_norm = d.strip().strip("/").strip("\\")
        if d_norm:
            prefixes.append(d_norm.replace("\\", "/") + "/")
    return prefixes


async def inspect_file(args: dict) -> ToolResult:
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return ToolResult(
            tool_name="inspect_file",
            success=False,
            error="Field 'path' must be a non-empty string.",
        )

    requested = raw_path.strip()
    pure = PurePath(requested)
    if ".." in pure.parts:
        return ToolResult(
            tool_name="inspect_file",
            success=False,
            error="Path traversal ('..') is not allowed.",
        )

    repo_root = _repo_root()
    candidate, err = _resolve_repo_path(raw_path=requested, repo_root=repo_root)
    if err:
        return ToolResult(
            tool_name="inspect_file",
            success=False,
            error=err,
        )
    assert candidate is not None

    if _is_secret_name(candidate):
        return ToolResult(
            tool_name="inspect_file",
            success=False,
            error="Access to secret-like files is blocked.",
        )

    if not candidate.is_file():
        return ToolResult(
            tool_name="inspect_file",
            success=False,
            error=f"File not found: {requested}",
        )

    size_bytes = candidate.stat().st_size
    if size_bytes > _INSPECT_MAX_BYTES:
        return ToolResult(
            tool_name="inspect_file",
            success=False,
            error=f"File exceeds 102400 byte limit: {size_bytes}",
        )

    try:
        content = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ToolResult(
            tool_name="inspect_file",
            success=False,
            error=f"Failed to read file: {exc}",
        )

    return ToolResult(
        tool_name="inspect_file",
        success=True,
        data={
            "path": str(candidate.relative_to(repo_root)).replace("\\", "/"),
            "size_bytes": size_bytes,
            "content": content,
        },
    )


async def propose_patch(args: dict) -> ToolResult:
    raw_path = args.get("path")
    raw_summary = args.get("summary")
    raw_patch = args.get("patch")

    if not isinstance(raw_path, str) or not raw_path.strip():
        return ToolResult(
            tool_name="propose_patch",
            success=False,
            error="Field 'path' must be a non-empty string.",
        )
    if not isinstance(raw_summary, str) or not raw_summary.strip():
        return ToolResult(
            tool_name="propose_patch",
            success=False,
            error="Field 'summary' must be a non-empty string.",
        )
    if not isinstance(raw_patch, str) or not raw_patch.strip():
        return ToolResult(
            tool_name="propose_patch",
            success=False,
            error="Field 'patch' must be a non-empty string.",
        )

    requested = raw_path.strip()
    summary = raw_summary.strip()
    patch_text = raw_patch

    if len(patch_text.encode("utf-8", errors="replace")) > _PATCH_MAX_BYTES:
        return ToolResult(
            tool_name="propose_patch",
            success=False,
            error=f"Patch exceeds 102400 byte limit.",
        )

    pure = PurePath(requested)
    if ".." in pure.parts:
        return ToolResult(
            tool_name="propose_patch",
            success=False,
            error="Path traversal ('..') is not allowed.",
        )

    repo_root = _repo_root()
    candidate, err = _resolve_repo_path(raw_path=requested, repo_root=repo_root)
    if err:
        return ToolResult(
            tool_name="propose_patch",
            success=False,
            error=err,
        )
    assert candidate is not None
    rel_path = candidate.relative_to(repo_root)

    if _is_secret_name(candidate):
        return ToolResult(
            tool_name="propose_patch",
            success=False,
            error="Access to secret-like files is blocked.",
        )

    return ToolResult(
        tool_name="propose_patch",
        success=True,
        data={
            "path": str(rel_path).replace("\\", "/"),
            "summary": summary,
            "patch": patch_text,
            "applied": False,
            "proposal_only": True,
        },
    )


async def list_project_files(args: dict) -> ToolResult:
    repo_root = _repo_root()

    raw_root = args.get("root", ".")
    if not isinstance(raw_root, str) or not raw_root.strip():
        return ToolResult(
            tool_name="list_project_files",
            success=False,
            error="Field 'root' must be a string.",
        )

    raw_max = args.get("max_results", 200)
    max_results = 200
    if isinstance(raw_max, int):
        max_results = raw_max
    elif isinstance(raw_max, str) and raw_max.strip().isdigit():
        max_results = int(raw_max.strip())
    if max_results < 1:
        max_results = 1
    if max_results > 1000:
        max_results = 1000

    include_hidden = bool(args.get("include_hidden", False))
    include_globs = _normalize_globs(args.get("include_globs")) or list(_DEFAULT_INCLUDE_GLOBS)

    root_path, err = _resolve_repo_path(raw_path=raw_root, repo_root=repo_root)
    if err:
        return ToolResult(tool_name="list_project_files", success=False, error=err)
    assert root_path is not None
    if not root_path.is_dir():
        return ToolResult(
            tool_name="list_project_files",
            success=False,
            error=f"Root is not a directory: {raw_root}",
        )

    exclude_prefixes = _exclude_prefixes(args.get("exclude_dirs"))

    results: list[dict[str, Any]] = []
    for p in root_path.rglob("*"):
        if len(results) >= max_results:
            break
        rel_str = _repo_relative_file(p, repo_root)
        if rel_str is None:
            continue

        rel_parts = Path(rel_str).parts

        if not include_hidden:
            if any(part.startswith(".") for part in rel_parts):
                continue

        # directory exclusions (prefix match)
        if any(rel_str.startswith(pref) for pref in exclude_prefixes):
            continue

        if _is_secret_name(p):
            continue

        if not _matches_any_glob(p.name, include_globs) and not _matches_any_glob(rel_str, include_globs):
            continue

        try:
            st = p.stat()
        except OSError:
            continue

        results.append(
            {
                "path": rel_str,
                "size_bytes": int(st.st_size),
                "modified_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            }
        )

    return ToolResult(
        tool_name="list_project_files",
        success=True,
        data={"count": len(results), "files": results},
    )


async def search_repo(args: dict) -> ToolResult:
    repo_root = _repo_root()

    raw_query = args.get("query")
    if not isinstance(raw_query, str) or not raw_query.strip():
        return ToolResult(
            tool_name="search_repo",
            success=False,
            error="Field 'query' must be a non-empty string.",
        )
    query = raw_query.strip()
    if len(query) > 200:
        return ToolResult(
            tool_name="search_repo",
            success=False,
            error="Query is too long (max 200 characters).",
        )

    raw_root = args.get("root", ".")
    if not isinstance(raw_root, str) or not raw_root.strip():
        return ToolResult(tool_name="search_repo", success=False, error="Field 'root' must be a string.")

    raw_max = args.get("max_results", 50)
    max_results = 50
    if isinstance(raw_max, int):
        max_results = raw_max
    elif isinstance(raw_max, str) and raw_max.strip().isdigit():
        max_results = int(raw_max.strip())
    if max_results < 1:
        max_results = 1
    if max_results > 500:
        max_results = 500

    raw_max_size = args.get("max_file_size_bytes", _DEFAULT_TEXT_MAX_BYTES)
    max_size = _DEFAULT_TEXT_MAX_BYTES
    if isinstance(raw_max_size, int):
        max_size = raw_max_size
    elif isinstance(raw_max_size, str) and raw_max_size.strip().isdigit():
        max_size = int(raw_max_size.strip())
    if max_size < 1:
        max_size = 1
    if max_size > 500_000:
        max_size = 500_000

    include_globs = _normalize_globs(args.get("include_globs")) or list(_DEFAULT_INCLUDE_GLOBS)

    root_path, err = _resolve_repo_path(raw_path=raw_root, repo_root=repo_root)
    if err:
        return ToolResult(tool_name="search_repo", success=False, error=err)
    assert root_path is not None
    if not root_path.is_dir():
        return ToolResult(tool_name="search_repo", success=False, error=f"Root is not a directory: {raw_root}")

    exclude_prefixes = _exclude_prefixes(args.get("exclude_dirs"))

    matches: list[dict[str, Any]] = []
    files_scanned = 0
    for p in root_path.rglob("*"):
        if len(matches) >= max_results:
            break
        rel_str = _repo_relative_file(p, repo_root)
        if rel_str is None:
            continue

        if any(rel_str.startswith(pref) for pref in exclude_prefixes):
            continue
        if _is_secret_name(p):
            continue
        if not _matches_any_glob(p.name, include_globs) and not _matches_any_glob(rel_str, include_globs):
            continue

        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size > max_size:
            continue
        if _is_probably_binary(p):
            continue

        files_scanned += 1
        try:
            with p.open("r", encoding="utf-8", errors="replace") as f:
                for idx, line in enumerate(f, start=1):
                    if query in line:
                        excerpt = line.strip()
                        if len(excerpt) > 240:
                            excerpt = excerpt[:240] + "…"
                        matches.append(
                            {
                                "path": rel_str,
                                "line": idx,
                                "excerpt": excerpt,
                            }
                        )
                        if len(matches) >= max_results:
                            break
        except OSError:
            continue

    return ToolResult(
        tool_name="search_repo",
        success=True,
        data={
            "query": query,
            "files_scanned": files_scanned,
            "match_count": len(matches),
            "matches": matches,
        },
    )


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
    "inspect_file": inspect_file,
    "propose_patch": propose_patch,
    "list_project_files": list_project_files,
    "search_repo": search_repo,
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
    unexpected = sorted(str(k) for k in set(args) - set(schema))
    if unexpected:
        return False, f"Unexpected field(s): {', '.join(unexpected)}."

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
        if want == "integer" and type(val) is not int:
            return False, f"Field '{field_name}' must be an integer."
        if want == "number" and (isinstance(val, bool) or not isinstance(val, (int, float))):
            return False, f"Field '{field_name}' must be a number."
        if want == "boolean" and type(val) is not bool:
            return False, f"Field '{field_name}' must be a boolean."
        if want == "array" and not isinstance(val, list):
            return False, f"Field '{field_name}' must be an array."

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
