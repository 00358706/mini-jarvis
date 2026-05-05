#!/usr/bin/env python3
"""
Regression test: /plans/from-message must create a proposal only.

The test patches every local tool execution boundary to fail. If the endpoint
ever executes a tool while creating the proposal, this script exits non-zero.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import approvals
import main
import sandbox
import tools
import workspace


def _use_temp_storage(root: Path) -> None:
    approvals._PLANS_ROOT = root / "plans"  # type: ignore[attr-defined]
    workspace._WORKSPACES_ROOT = root / "workspaces"  # type: ignore[attr-defined]
    workspace._ACTIVE = workspace._WORKSPACES_ROOT / "active"  # type: ignore[attr-defined]
    workspace._COMPLETED = workspace._WORKSPACES_ROOT / "completed"  # type: ignore[attr-defined]
    workspace._REJECTED = workspace._WORKSPACES_ROOT / "rejected"  # type: ignore[attr-defined]


def main_test() -> int:
    calls: list[str] = []

    async def fail_run_installed_tool(*args, **kwargs):
        calls.append("run_installed_tool")
        raise AssertionError("/plans/from-message executed run_installed_tool")

    async def fail_sandbox_run(*args, **kwargs):
        calls.append("sandbox.run")
        raise AssertionError("/plans/from-message executed sandbox.run")

    async def fail_run_tool_by_name(*args, **kwargs):
        calls.append("run_tool_by_name")
        raise AssertionError("/plans/from-message executed run_tool_by_name")

    main.run_installed_tool = fail_run_installed_tool
    tools.run_installed_tool = fail_run_installed_tool
    sandbox.run = fail_sandbox_run
    tools.sandbox.run = fail_sandbox_run
    tools.run_tool_by_name = fail_run_tool_by_name

    with tempfile.TemporaryDirectory(prefix="mini_jarvis_from_message_") as tmp:
        _use_temp_storage(Path(tmp))
        client = TestClient(main.app)
        response = client.post(
            "/plans/from-message",
            headers={"X-API-Key": main.cfg.api_key},
            json={
                "message": "search repo for README.md",
                "agent": "project_maintainer_agent",
                "plan_id": "test_from_message_no_execute",
            },
        )

    if response.status_code != 200:
        print(response.text)
        return 1

    body = response.json()
    if body.get("status") != "pending_approval":
        print(f"Unexpected status: {body!r}")
        return 1
    if calls:
        print(f"Unexpected execution call(s): {calls}")
        return 1

    print("OK: /plans/from-message proposed a plan without executing tools.")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
