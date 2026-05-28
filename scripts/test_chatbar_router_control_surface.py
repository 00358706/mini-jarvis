#!/usr/bin/env python3
"""Regression tests for chatbar automatic routing and proposal-only boundaries."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient

import approvals
import main
import notifications
import routers.plans as plans_router
import sandbox
import tools
import workspace
from config import cfg


def _fail(msg: str) -> int:
    print(msg)
    return 1


def _use_temp_storage(root: Path) -> None:
    approvals._PLANS_ROOT = root / "plans"  # type: ignore[attr-defined]
    workspace._WORKSPACES_ROOT = root / "workspaces"  # type: ignore[attr-defined]
    workspace._ACTIVE = workspace._WORKSPACES_ROOT / "active"  # type: ignore[attr-defined]
    workspace._COMPLETED = workspace._WORKSPACES_ROOT / "completed"  # type: ignore[attr-defined]
    workspace._REJECTED = workspace._WORKSPACES_ROOT / "rejected"  # type: ignore[attr-defined]
    nd = root / "notifications"
    nd.mkdir(parents=True, exist_ok=True)
    notifications.NOTIFICATIONS_DIR = nd  # type: ignore[attr-defined]
    notifications.PENDING_APPROVALS_JSONL = nd / "pending_approvals.jsonl"  # type: ignore[attr-defined]


def _client(root: Path) -> TestClient:
    _use_temp_storage(root)
    return TestClient(main.app)


async def _auto_media_route(*, message, candidate_routes, route_to_agent, manual_agent=None, model_call=None):
    if manual_agent:
        raise AssertionError("automatic test should not pass manual_agent")
    return {
        "selected_route": "media",
        "selected_agent": "media_agent",
        "reason": "router_selected",
        "router_reason": "media wording",
        "confidence": 0.96,
        "authority": False,
        "model_called": True,
        "tool_executed": False,
        "approval_granted": False,
        "estimated_input_tokens": 20,
    }


async def _manual_should_not_route(*, message, candidate_routes, route_to_agent, manual_agent=None, model_call=None):
    if manual_agent != "project_maintainer_agent":
        raise AssertionError(f"expected manual_agent override, got {manual_agent!r}")
    return {
        "selected_route": "manual_override",
        "selected_agent": manual_agent,
        "reason": "manual_agent_selected",
        "router_reason": "manual agent override; tiny router bypassed",
        "confidence": 1.0,
        "authority": False,
        "model_called": False,
        "tiny_router_bypassed": True,
        "tool_executed": False,
        "approval_granted": False,
        "estimated_input_tokens": 0,
    }


async def _unsafe_execute_claim_route(*, message, candidate_routes, route_to_agent, manual_agent=None, model_call=None):
    return {
        "selected_route": "media",
        "selected_agent": "media_agent",
        "reason": "router_selected",
        "router_reason": "malicious execute claim ignored by gateway contract",
        "confidence": 0.99,
        "authority": False,
        "model_called": True,
        "tool_executed": False,
        "approval_granted": False,
        "estimated_input_tokens": 20,
    }


def main_test() -> int:
    original_select_route = plans_router.select_route
    original_safe = cfg.small_router_safe_input_tokens
    execution_calls: list[str] = []

    async def fail_run_installed_tool(*args, **kwargs):
        execution_calls.append("run_installed_tool")
        raise AssertionError("proposal endpoint must not execute installed tools")

    async def fail_sandbox_run(*args, **kwargs):
        execution_calls.append("sandbox.run")
        raise AssertionError("proposal endpoint must not call sandbox")

    main.run_installed_tool = fail_run_installed_tool
    tools.run_installed_tool = fail_run_installed_tool
    sandbox.run = fail_sandbox_run
    tools.sandbox.run = fail_sandbox_run

    try:
        with tempfile.TemporaryDirectory(prefix="mini_jarvis_chatbar_") as tmp:
            client = _client(Path(tmp))
            headers = {"X-API-Key": main.cfg.api_key}

            plans_router.select_route = _auto_media_route  # type: ignore[assignment]
            auto_resp = client.post(
                "/plans/from-message",
                headers=headers,
                json={"message": "search movie Arrival", "plan_id": "chatbar_auto_supported"},
            )
            if auto_resp.status_code != 200:
                return _fail(f"automatic supported route failed: {auto_resp.status_code} {auto_resp.text}")
            auto_body = auto_resp.json()
            if auto_body.get("status") != "pending_approval" or auto_body.get("agent") != "media_agent":
                return _fail(f"automatic route wrong response: {auto_body}")
            routing = auto_body.get("routing") or {}
            if routing.get("selected_route") != "media" or routing.get("authority") is not False:
                return _fail(f"automatic route details missing/sunsafe: {routing}")

            plans_router.select_route = _manual_should_not_route  # type: ignore[assignment]
            manual_resp = client.post(
                "/plans/from-message",
                headers=headers,
                json={
                    "message": "search movie Arrival",
                    "agent": "project_maintainer_agent",
                    "plan_id": "chatbar_manual_override",
                },
            )
            if manual_resp.status_code != 200:
                return _fail(f"manual override failed: {manual_resp.status_code} {manual_resp.text}")
            manual_body = manual_resp.json()
            if manual_body.get("agent") != "project_maintainer_agent":
                return _fail(f"manual selection did not bypass automatic agent: {manual_body}")
            if manual_body.get("routing", {}).get("model_called") is not False:
                return _fail(f"manual selection should bypass tiny router: {manual_body}")

            cfg.small_router_safe_input_tokens = 8
            plans_router.select_route = original_select_route  # type: ignore[assignment]
            oversized_resp = client.post(
                "/plans/from-message",
                headers=headers,
                json={"message": "x" * 5000, "plan_id": "chatbar_oversized"},
            )
            if oversized_resp.status_code != 400:
                return _fail(f"oversized prompt should fall back safely: {oversized_resp.status_code} {oversized_resp.text}")
            oversized_body = oversized_resp.json()
            if oversized_body.get("status") != "manual_agent_required":
                return _fail(f"oversized prompt wrong status: {oversized_body}")

            plans_router.select_route = _unsafe_execute_claim_route  # type: ignore[assignment]
            radarr_resp = client.post(
                "/plans/from-message",
                headers=headers,
                json={"message": "add movie Arrival", "plan_id": "chatbar_radarr_add_proposal"},
            )
            if radarr_resp.status_code != 200:
                return _fail(f"radarr add proposal failed: {radarr_resp.status_code} {radarr_resp.text}")
            radarr_body = radarr_resp.json()
            if radarr_body.get("status") != "pending_approval":
                return _fail(f"radarr add should create proposal only: {radarr_body}")
            plan_path = Path(tmp) / "plans" / "pending" / "chatbar_radarr_add_proposal.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if plan.get("steps", [{}])[0].get("tool") != "radarr_add":
                return _fail(f"radarr add request did not propose radarr_add: {plan}")
            if execution_calls:
                return _fail(f"proposal path executed unexpectedly: {execution_calls}")

        print("OK: chatbar automatic router control surface remains proposal-only.")
        return 0
    finally:
        plans_router.select_route = original_select_route  # type: ignore[assignment]
        cfg.small_router_safe_input_tokens = original_safe


if __name__ == "__main__":
    sys.exit(main_test())
