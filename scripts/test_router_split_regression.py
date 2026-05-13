#!/usr/bin/env python3
"""
Structural regression for FastAPI router split: paths, auth roles, composition root.

No HTTP calls to external services; uses app introspection and auth role helpers only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import main
from services.auth_roles import classify_api_key, key_allows_route, route_api_role


def _fail(msg: str) -> int:
    print(msg)
    return 1


# Minimum OpenAPI path templates that must exist after the router split.
_REQUIRED_OPENAPI_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/ingest",
        "/plans/propose",
        "/plans/from-message",
        "/plans/pending",
        "/plans/pending/{plan_id}",
        "/plans/{plan_id}/approve",
        "/plans/{plan_id}/reject",
        "/plans/{plan_id}/execute",
        "/notifications/pending-approvals",
        "/workspaces",
        "/logs",
        "/events",
        "/tools",
        "/tools/propose",
        "/tools/approve",
        "/tools/install",
        "/tools/reject",
    }
)


def main_test() -> int:
    app = main.app
    schema = app.openapi()
    paths = set(schema.get("paths", {}).keys())

    missing = sorted(_REQUIRED_OPENAPI_PATHS - paths)
    if missing:
        return _fail(f"OpenAPI missing required paths: {missing}")

    # --- /health remains public (no API-key dependency in OpenAPI) ---
    if "/health" not in paths:
        return _fail("OpenAPI missing /health")
    health_ops = schema["paths"]["/health"]
    if "get" not in health_ops:
        return _fail("/health must expose GET in OpenAPI")
    health_get = health_ops["get"] or {}
    if health_get.get("security"):
        return _fail("/health must not declare security dependencies in OpenAPI (public liveness)")
    if health_get.get("dependencies"):
        return _fail("/health must not declare FastAPI dependencies in OpenAPI (public liveness)")

    # --- route_api_role samples (must match services/auth_roles.py) ---
    _samples: list[tuple[str, str, str]] = [
        ("POST", "/ingest", "INPUT_POST"),
        ("POST", "/plans/from-message", "INPUT_POST"),
        ("GET", "/notifications/pending-approvals", "READ_REVIEW"),
        ("POST", "/plans/abc/approve", "APPROVAL_ACTION"),
        ("POST", "/tools/propose", "ADMIN_ACTION"),
        ("GET", "/workspaces-admin", "MASTER_ONLY"),
        ("GET", "/tools/deep/path/extra", "MASTER_ONLY"),
    ]
    for method, path, expected in _samples:
        got = route_api_role(method, path)
        if got != expected:
            return _fail(f"route_api_role({method!r}, {path!r}) expected {expected!r}, got {got!r}")

    # Non-master keys must not pass MASTER_ONLY.
    if key_allows_route(route_role="MASTER_ONLY", key_kind="input"):
        return _fail("input key must not allow MASTER_ONLY")
    if key_allows_route(route_role="MASTER_ONLY", key_kind="approval"):
        return _fail("approval key must not allow MASTER_ONLY")

    # --- main.py composition root: only /health as @app HTTP route; no large pasted handlers ---
    main_src = (_REPO_ROOT / "main.py").read_text(encoding="utf-8")
    main_lines = main_src.splitlines()

    bad_route_decos: list[str] = []
    for line in main_lines:
        m = re.match(r"^@app\.(get|post|put|delete|patch)\b", line)
        if not m:
            continue
        stripped = line.strip()
        if stripped.startswith('@app.get("/health")'):
            continue
        bad_route_decos.append(stripped)
    if bad_route_decos:
        return _fail(f"main.py must not declare @app HTTP routes beyond /health; found: {bad_route_decos}")

    async_defs = re.findall(r"^async def (\w+)\s*\(", main_src, re.MULTILINE)
    allowed_async = frozenset({"lifespan", "require_api_key", "global_exception_handler", "health"})
    extra = sorted(set(async_defs) - allowed_async)
    if extra:
        return _fail(f"main.py must not define extra async route bodies; unexpected async def: {extra}")

    # Refactor guard: composition root stays small (no big handler paste into main).
    if len(main_lines) > 260:
        return _fail(f"main.py unexpectedly large ({len(main_lines)} lines); route bodies should live in routers/")

    # Test monkeypatch surface preserved on main.
    if not callable(getattr(main, "plans_execute", None)):
        return _fail("main.plans_execute missing")
    if not callable(getattr(main, "_installed_tool_names", None)):
        return _fail("main._installed_tool_names missing")
    if classify_api_key("") is not None:
        return _fail("empty key classify")

    print("OK: router split regression.")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
