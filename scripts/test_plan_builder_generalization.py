#!/usr/bin/env python3
"""
Generalized /plans/from-message plan builder: maintainer + media + missing capability,
role gates, and authority boundaries (no tool/sandbox/registry/approve/execute).
"""

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
import config
import main
import notifications
import registry as reg
import sandbox
import tools
import workspace


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


def _fail(msg: str) -> int:
    print(msg)
    return 1


def main_test() -> int:
    cfg = config.cfg
    saved_keys = (cfg.api_key, cfg.input_api_key, cfg.approval_api_key, cfg.admin_api_key)
    real_installed = main._installed_tool_names

    approve_calls: list[str] = []
    reject_calls: list[str] = []
    execute_calls: list[str] = []
    tool_calls: list[str] = []
    sandbox_calls: list[str] = []
    reg_calls: list[str] = []

    def track_approve(pid: str):
        approve_calls.append(pid)
        raise AssertionError("approve_plan")

    def track_reject(pid: str, reason: str | None = None):
        reject_calls.append(pid)
        raise AssertionError("reject_plan")

    def track_mark_executed(pid: str, result=None):
        execute_calls.append(pid)
        raise AssertionError("mark_executed")

    async def track_run_tool(*args, **kwargs):
        tool_calls.append("run")
        raise AssertionError("run_installed_tool")

    async def track_sandbox(*args, **kwargs):
        sandbox_calls.append("sandbox")
        raise AssertionError("sandbox.run")

    def track_reg(name: str):
        def inner(*a, **k):
            reg_calls.append(name)
            raise AssertionError(f"registry.{name}")

        return inner

    approvals.approve_plan = track_approve  # type: ignore[assignment]
    approvals.reject_plan = track_reject  # type: ignore[assignment]
    approvals.mark_executed = track_mark_executed  # type: ignore[assignment]
    main.run_installed_tool = track_run_tool  # type: ignore[assignment]
    tools.run_installed_tool = track_run_tool  # type: ignore[assignment]
    sandbox.run = track_sandbox  # type: ignore[assignment]
    tools.sandbox.run = track_sandbox  # type: ignore[assignment]
    reg.propose = track_reg("propose")  # type: ignore[assignment]
    reg.approve = track_reg("approve")  # type: ignore[assignment]
    reg.install = track_reg("install")  # type: ignore[assignment]
    reg.reject = track_reg("reject")  # type: ignore[assignment]

    cfg.api_key = "pb-master-key"
    cfg.input_api_key = "pb-input-key"
    cfg.approval_api_key = "pb-approval-key"
    cfg.admin_api_key = "pb-admin-key"
    h_in = {"X-API-Key": cfg.input_api_key}
    h_apr = {"X-API-Key": cfg.approval_api_key}
    h_adm = {"X-API-Key": cfg.admin_api_key}

    try:
        with tempfile.TemporaryDirectory(prefix="mini_jarvis_pb_gen_") as tmp:
            root = Path(tmp)
            _use_temp_storage(root)
            client = TestClient(main.app)
            jsonl = notifications.PENDING_APPROVALS_JSONL

            def nlines() -> int:
                if not jsonl.is_file():
                    return 0
                return len([x for x in jsonl.read_text(encoding="utf-8").splitlines() if x.strip()])

            # --- 1: Maintainer cases (pending + notification) ---
            for msg, pid in (
                ("list project files", "pb_maint_list"),
                ("search repo for README.md", "pb_maint_search"),
                ("inspect README.md", "pb_maint_inspect"),
            ):
                n0 = nlines()
                r = client.post(
                    "/plans/from-message",
                    headers=h_in,
                    json={"message": msg, "agent": "project_maintainer_agent", "plan_id": pid},
                )
                if r.status_code != 200 or r.json().get("status") != "pending_approval":
                    return _fail(f"maintainer case failed {msg!r}: {r.status_code} {r.text}")
                if nlines() != n0 + 1:
                    return _fail("expected notification append for maintainer pending plan")
            if approve_calls or tool_calls or sandbox_calls or reg_calls:
                return _fail("unexpected side effects during maintainer from-message")

            # --- 2: media_agent with full installed set ---
            main._installed_tool_names = real_installed  # type: ignore[method-assign]
            n1 = nlines()
            for body, pid in (
                (
                    {"message": "search for movie Inception", "agent": "media_agent", "plan_id": "pb_media_movie"},
                    "pb_media_movie",
                ),
                (
                    {
                        "message": "search for series Breaking Bad",
                        "agent": "media_agent",
                        "plan_id": "pb_media_series",
                    },
                    "pb_media_series",
                ),
                (
                    {"message": "show sabnzbd queue", "agent": "media_agent", "plan_id": "pb_media_q"},
                    "pb_media_q",
                ),
            ):
                r = client.post("/plans/from-message", headers=h_in, json=body)
                if r.status_code != 200 or r.json().get("status") != "pending_approval":
                    return _fail(f"media case failed {body!r}: {r.status_code} {r.text}")
            if nlines() < n1 + 3:
                return _fail("expected three notification lines for three media proposals")
            if tool_calls or sandbox_calls or reg_calls:
                return _fail("media from-message must not execute tools or mutate registry")

            # --- 3: Navidrome → missing_capability, no notification bump ---
            n2 = nlines()
            r_nav = client.post(
                "/plans/from-message",
                headers=h_in,
                json={
                    "message": "recent Navidrome albums",
                    "agent": "media_agent",
                    "plan_id": "pb_nav_missing",
                },
            )
            if r_nav.status_code != 400:
                return _fail(f"navidrome expected 400, got {r_nav.status_code} {r_nav.text}")
            j = r_nav.json()
            if j.get("status") != "missing_capability" or not j.get("proposal_needed"):
                return _fail(f"bad missing_capability body: {j}")
            if nlines() != n2:
                return _fail("navidrome must not append notification")

            # radarr requested but not "installed" in builder view
            def no_radarr():
                return {x for x in real_installed() if x != "radarr_search"}

            main._installed_tool_names = no_radarr  # type: ignore[method-assign]
            r_nr = client.post(
                "/plans/from-message",
                headers=h_in,
                json={
                    "message": "search for movie Matrix",
                    "agent": "media_agent",
                    "plan_id": "pb_no_radarr",
                },
            )
            if r_nr.status_code != 400 or r_nr.json().get("status") != "missing_capability":
                return _fail(f"expected missing_capability without radarr_search: {r_nr.text}")
            main._installed_tool_names = real_installed  # type: ignore[method-assign]

            # --- 4: Unsupported agent ---
            r_ua = client.post(
                "/plans/from-message",
                headers=h_in,
                json={"message": "hello", "agent": "unknown_agent_x", "plan_id": "pb_bad_agent"},
            )
            if r_ua.status_code != 400:
                return _fail(f"unsupported agent expected 400: {r_ua.text}")
            if "detail" not in r_ua.json():
                return _fail("unsupported agent should return FastAPI detail shape")

            # --- 5: Role keys ---
            fm_body = {
                "message": "search for movie Z",
                "agent": "media_agent",
                "plan_id": "pb_role_fm",
            }
            if client.post("/plans/from-message", headers=h_apr, json=fm_body).status_code != 403:
                return _fail("approval key must not POST from-message")
            if client.post("/plans/from-message", headers=h_adm, json=fm_body).status_code != 403:
                return _fail("admin key must not POST from-message")
            if client.post("/plans/pb_media_movie/approve", headers=h_in).status_code != 403:
                return _fail("input must not approve")

    finally:
        cfg.api_key, cfg.input_api_key, cfg.approval_api_key, cfg.admin_api_key = saved_keys
        main._installed_tool_names = real_installed  # type: ignore[method-assign]

    print("OK: plan builder generalization.")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
