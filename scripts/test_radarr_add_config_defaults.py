#!/usr/bin/env python3
"""Regression tests for radarr_add configurable payload defaults.

This does not contact Radarr or add a movie. It replaces the shared HTTP client
factory with an in-memory fake and asserts the outgoing JSON payload.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

_KEYS = (
    "RADARR_URL",
    "RADARR_API_KEY",
    "RADARR_ROOT_FOLDER_PATH",
    "RADARR_QUALITY_PROFILE_ID",
    "TOOL_TIMEOUT",
)


class _FakeResponse:
    def __init__(self, payload: Any):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    def __init__(self, calls: list[tuple[str, str, Any]]):
        self._calls = calls

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def get(self, url: str, *, params: dict[str, Any]) -> _FakeResponse:
        self._calls.append(("GET", url, params))
        return _FakeResponse([{"title": "Arrival", "tmdbId": 329865, "year": 2016}])

    async def post(
        self, url: str, *, params: dict[str, Any], json: dict[str, Any]
    ) -> _FakeResponse:
        self._calls.append(("POST", url, {"params": params, "json": json}))
        return _FakeResponse({"id": 123})


def _load_tools_with_env(env: dict[str, str]):
    for key in _KEYS:
        if key in env:
            os.environ[key] = env[key]
        else:
            os.environ.pop(key, None)
    for module_name in ("config", "sandbox", "tools"):
        sys.modules.pop(module_name, None)
    return importlib.import_module("tools")


async def _run_case(env: dict[str, str]) -> tuple[Any, list[tuple[str, str, Any]]]:
    tools = _load_tools_with_env(env)
    calls: list[tuple[str, str, Any]] = []
    tools.tools_http.async_http_client = lambda timeout: _FakeClient(calls)
    result = await tools.radarr_add({"title": "Arrival"})
    return result, calls


def test_radarr_add_uses_explicit_env_defaults() -> None:
    result, calls = asyncio.run(
        _run_case(
            {
                "RADARR_URL": "http://radarr.local:7878",
                "RADARR_API_KEY": "test-key",
                "RADARR_ROOT_FOLDER_PATH": "/media/movies",
                "RADARR_QUALITY_PROFILE_ID": "6",
                "TOOL_TIMEOUT": "3.5",
            }
        )
    )

    assert result.success, result
    posts = [call for call in calls if call[0] == "POST"]
    assert len(posts) == 1, calls
    payload = posts[0][2]["json"]
    params = posts[0][2]["params"]
    assert payload["rootFolderPath"] == "/media/movies"
    assert payload["qualityProfileId"] == 6
    assert payload["apikey"] == "test-key"
    assert params["apikey"] == "test-key"


def test_radarr_add_uses_configured_fallbacks_when_env_unset() -> None:
    result, calls = asyncio.run(_run_case({}))

    assert result.success, result
    posts = [call for call in calls if call[0] == "POST"]
    assert len(posts) == 1, calls
    payload = posts[0][2]["json"]
    assert payload["rootFolderPath"] == "/media/movies"
    assert payload["qualityProfileId"] == 6


def test_sandbox_injects_radarr_add_default_env_keys() -> None:
    sandbox = importlib.import_module("sandbox")
    assert "RADARR_ROOT_FOLDER_PATH" in sandbox.SANDBOX_TOOL_ENV_INJECT_KEYS
    assert "RADARR_QUALITY_PROFILE_ID" in sandbox.SANDBOX_TOOL_ENV_INJECT_KEYS


def main() -> int:
    tests = (
        test_radarr_add_uses_explicit_env_defaults,
        test_radarr_add_uses_configured_fallbacks_when_env_unset,
        test_sandbox_injects_radarr_add_default_env_keys,
    )
    original_env = {key: os.environ.get(key) for key in _KEYS}
    try:
        for test in tests:
            test()
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for module_name in ("config", "tools"):
            sys.modules.pop(module_name, None)
    print("OK: radarr_add config/env defaults")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
