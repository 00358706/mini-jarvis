"""
registry.py — Formal tool registry with lifecycle management.

Responsibility:
  - Maintain a registry of approved, installed tools (ToolDefinition records).
  - Manage the full lifecycle:  propose → review → approve → install → register
  - Expose registry state for the /tools family of endpoints.

Lifecycle states:
  proposed   — tool has been submitted for review (not yet runnable)
  approved   — reviewed and cleared (not yet installed)
  installed  — code / endpoint is ready; registered and callable
  rejected   — proposal denied (terminal)

Security invariants:
  - Only tools in state "installed" may be executed.
  - Registry is the single source of truth — no tool can be called unless
    it appears here with status == "installed".
  - Tool definitions include an input_schema so callers can validate args
    before dispatch.

Design notes:
  - In-memory store (dict keyed by name + version string "name:v1").
  - Seed the registry with the built-in tools at startup.
  - A future version can back this with SQLite; the interface stays the same.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from models import ToolDefinition, ToolLifecycleStatus, ToolProposal

logger = logging.getLogger("gateway.registry")

# ──────────────────────────────────────────────────────────────────────────────
# Internal store
# ──────────────────────────────────────────────────────────────────────────────

# Key: "<name>:<version>" e.g. "radarr_add:v1"
_registry: dict[str, ToolDefinition] = {}


def _key(name: str, version: str) -> str:
    return f"{name}:{version}"


# ──────────────────────────────────────────────────────────────────────────────
# Lifecycle operations
# ──────────────────────────────────────────────────────────────────────────────


def propose(proposal: ToolProposal) -> ToolDefinition:
    """
    Submit a new tool proposal. Status starts as 'proposed'.
    Raises ValueError if a tool with the same name+version already exists.
    """
    if not isinstance(proposal.input_schema, dict):
        raise ValueError(
            "input_schema must be an object mapping field names to type specs."
        )
    for fname, spec in proposal.input_schema.items():
        if not isinstance(fname, str) or not fname.strip():
            raise ValueError("input_schema keys must be non-empty strings.")
        if spec is not None and not isinstance(spec, dict):
            raise ValueError(
                f"input_schema['{fname}'] must be an object with type/required keys."
            )

    k = _key(proposal.name, proposal.version)
    if k in _registry:
        raise ValueError(f"Tool '{k}' already exists in the registry.")
    entry = ToolDefinition(
        name=proposal.name,
        endpoint=proposal.endpoint,
        input_schema=proposal.input_schema,
        permissions=proposal.permissions,
        version=proposal.version,
        description=proposal.description,
        status="proposed",
    )
    _registry[k] = entry
    logger.info("registry.propose | %s", k)
    return entry


def approve(name: str, version: str) -> ToolDefinition:
    """
    Approve a proposed tool. Status moves from 'proposed' → 'approved'.
    Raises KeyError if not found; ValueError if not in a proposable state.
    """
    k = _key(name, version)
    entry = _registry.get(k)
    if entry is None:
        raise KeyError(f"Tool '{k}' not found in registry.")
    if entry.status != "proposed":
        raise ValueError(f"Tool '{k}' is '{entry.status}', expected 'proposed'.")
    entry.status = "approved"
    logger.info("registry.approve | %s", k)
    return entry


def install(name: str, version: str) -> ToolDefinition:
    """
    Mark an approved tool as installed/registered (ready to execute).
    Status moves from 'approved' → 'installed'.
    """
    k = _key(name, version)
    entry = _registry.get(k)
    if entry is None:
        raise KeyError(f"Tool '{k}' not found in registry.")
    if entry.status != "approved":
        raise ValueError(f"Tool '{k}' is '{entry.status}', expected 'approved'.")
    entry.status = "installed"
    logger.info("registry.install | %s", k)
    return entry


def reject(name: str, version: str, reason: str = "") -> ToolDefinition:
    """Reject a proposed tool. Terminal state."""
    k = _key(name, version)
    entry = _registry.get(k)
    if entry is None:
        raise KeyError(f"Tool '{k}' not found in registry.")
    entry.status = "rejected"
    logger.info("registry.reject | %s | reason=%s", k, reason)
    return entry


# ──────────────────────────────────────────────────────────────────────────────
# Query
# ──────────────────────────────────────────────────────────────────────────────


def get(name: str, version: str) -> ToolDefinition | None:
    return _registry.get(_key(name, version))


def get_installed(name: str) -> ToolDefinition | None:
    """
    Return the installed version of a tool by name, or None.
    If multiple versions are installed (unusual), returns the last one.
    """
    for entry in _registry.values():
        if entry.name == name and entry.status == "installed":
            return entry
    return None


def all_tools() -> list[ToolDefinition]:
    return list(_registry.values())


def installed_tools() -> list[ToolDefinition]:
    return [t for t in _registry.values() if t.status == "installed"]


# ──────────────────────────────────────────────────────────────────────────────
# Bootstrap — seed built-in tools at import time
# ──────────────────────────────────────────────────────────────────────────────


def _seed_builtin(
    name: str,
    endpoint: str,
    description: str,
    input_schema: dict[str, Any],
    permissions: list[str],
    version: str = "v1",
) -> None:
    """Register a built-in tool directly as 'installed' (no lifecycle needed)."""
    k = _key(name, version)
    _registry[k] = ToolDefinition(
        name=name,
        endpoint=endpoint,
        input_schema=input_schema,
        permissions=permissions,
        version=version,
        description=description,
        status="installed",
    )


# Radarr
_seed_builtin(
    name="radarr_search",
    endpoint="internal://tools/radarr_search",
    description="Search for a movie in Radarr by title.",
    input_schema={"title": {"type": "string", "required": True}},
    permissions=["radarr:read"],
)
_seed_builtin(
    name="radarr_add",
    endpoint="internal://tools/radarr_add",
    description="Add a movie to Radarr's monitored list and trigger a search.",
    input_schema={"title": {"type": "string", "required": True}},
    permissions=["radarr:write"],
)

# Sonarr
_seed_builtin(
    name="sonarr_search",
    endpoint="internal://tools/sonarr_search",
    description="Search for a TV series in Sonarr by title.",
    input_schema={"title": {"type": "string", "required": True}},
    permissions=["sonarr:read"],
)
_seed_builtin(
    name="sonarr_add",
    endpoint="internal://tools/sonarr_add",
    description="Add a TV series to Sonarr and trigger episode search.",
    input_schema={"title": {"type": "string", "required": True}},
    permissions=["sonarr:write"],
)

# SABnzbd
_seed_builtin(
    name="sabnzbd_queue",
    endpoint="internal://tools/sabnzbd_queue",
    description="Return current SABnzbd download queue status.",
    input_schema={},
    permissions=["sabnzbd:read"],
)
_seed_builtin(
    name="sabnzbd_pause",
    endpoint="internal://tools/sabnzbd_pause",
    description="Pause SABnzbd downloads.",
    input_schema={},
    permissions=["sabnzbd:write"],
)
_seed_builtin(
    name="sabnzbd_resume",
    endpoint="internal://tools/sabnzbd_resume",
    description="Resume SABnzbd downloads.",
    input_schema={},
    permissions=["sabnzbd:write"],
)

# Project maintainer
_seed_builtin(
    name="inspect_file",
    endpoint="internal://tools/inspect_file",
    description="Read a small text file inside the repository for review.",
    input_schema={"path": {"type": "string", "required": True}},
    permissions=["file:read"],
)
_seed_builtin(
    name="propose_patch",
    endpoint="internal://tools/propose_patch",
    description="Return a patch proposal artifact without applying file changes.",
    input_schema={
        "path": {"type": "string", "required": True},
        "summary": {"type": "string", "required": True},
        "patch": {"type": "string", "required": True},
    },
    permissions=["file:proposal"],
)

_seed_builtin(
    name="list_project_files",
    endpoint="internal://tools/list_project_files",
    description="List repository files without reading contents (repo-confined).",
    input_schema={
        "root": {"type": "string", "required": False},
        "max_results": {"type": "integer", "required": False},
        "include_hidden": {"type": "boolean", "required": False},
        "include_globs": {"type": "array", "required": False},
        "exclude_dirs": {"type": "array", "required": False},
    },
    permissions=["file:list"],
)
_seed_builtin(
    name="search_repo",
    endpoint="internal://tools/search_repo",
    description="Literal text search in repository text files (repo-confined).",
    input_schema={
        "query": {"type": "string", "required": True},
        "root": {"type": "string", "required": False},
        "max_results": {"type": "integer", "required": False},
        "max_file_size_bytes": {"type": "integer", "required": False},
        "include_globs": {"type": "array", "required": False},
        "exclude_dirs": {"type": "array", "required": False},
    },
    permissions=["file:search"],
)

# ──────────────────────────────────────────────────────────────────────────────
# Persistent reviewed generated-tool metadata (no execution dispatch)
# ──────────────────────────────────────────────────────────────────────────────

_GENERATED_REGISTRY_PATH = (
    Path(__file__).resolve().parent / "data" / "registry" / "generated_installed_tools.json"
)


def _load_generated_installed_tools() -> None:
    """
    Load metadata-only installed tool rows from disk after built-in seed.

    Does not import candidate code, sandbox, tools, or gateway modules.
    Skips invalid rows and collisions; does not create a dispatch path in tools.py.
    """
    path = _GENERATED_REGISTRY_PATH
    if not path.is_file():
        return
    try:
        raw = path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.warning("generated registry | skip load: %s", exc)
        return
    if not isinstance(data, list):
        logger.warning(
            "generated registry | expected JSON array, got %s", type(data).__name__
        )
        return
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("generated registry | skip row %s: not an object", i)
            continue
        try:
            entry = ToolDefinition.model_validate(item)
        except Exception as exc:  # noqa: BLE001 — best-effort per row
            logger.warning(
                "generated registry | skip row %s: invalid ToolDefinition (%s)", i, exc
            )
            continue
        if entry.status != "installed":
            logger.warning(
                "generated registry | skip row %s: status=%s (expected installed)",
                i,
                entry.status,
            )
            continue
        k = _key(entry.name, entry.version)
        if k in _registry:
            logger.warning("generated registry | skip row %s: collision on %s", i, k)
            continue
        _registry[k] = entry
        logger.info("generated registry | loaded %s", k)


_load_generated_installed_tools()
