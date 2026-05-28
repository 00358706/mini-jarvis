"""
sandbox_worker.py — Subprocess entrypoint for isolated tool execution.

Started by sandbox.run(); reads JSON stdin:
  {"name": str, "args": dict, "_child_env": dict | null}

`_child_env` is merged into os.environ (allowlisted keys only) before `tools`
is imported so tools.py can keep using os.getenv while the parent passes a
PATH-only subprocess environment to Popen.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# Keep this local so importing the worker does not import sandbox/config before
# _child_env is applied; tools.py imports config after these env keys are set.
SANDBOX_TOOL_ENV_INJECT_KEYS: frozenset[str] = frozenset(
    {
        "RADARR_URL",
        "RADARR_API_KEY",
        "RADARR_ROOT_FOLDER_PATH",
        "RADARR_QUALITY_PROFILE_ID",
        "SONARR_URL",
        "SONARR_API_KEY",
        "SABNZBD_URL",
        "SABNZBD_API_KEY",
        "TOOL_TIMEOUT",
    }
)


def _apply_child_env(pairs: object) -> None:
    if not isinstance(pairs, dict):
        return

    for key, val in pairs.items():
        if key not in SANDBOX_TOOL_ENV_INJECT_KEYS:
            continue
        if val is None:
            continue
        os.environ[str(key)] = str(val)


async def _main() -> None:
    data = json.load(sys.stdin)
    name = data["name"]
    args = data.get("args") or {}
    _apply_child_env(data.get("_child_env"))

    from tools import run_tool_by_name

    result = await run_tool_by_name(name, args)
    payload = json.dumps(result.model_dump(mode="json"), ensure_ascii=True)
    sys.stdout.write(payload)
    sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(_main())
