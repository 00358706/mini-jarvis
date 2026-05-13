#!/usr/bin/env python3
"""
Role-separated X-API-Key: master vs input vs approval vs admin routes.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient

import approvals
import config
import notifications
import dispatch
import main
import sandbox
import tools
import workspace
from models import ClassifierResult, NormalisedEnvelope, ToolResult


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
    saved = (
        cfg.api_key,
        cfg.input_api_key,
        cfg.approval_api_key,
        cfg.admin_api_key,
    )

    async def stub_run_installed_tool(tool_name: str, args: dict):
        return ToolResult(
            tool_name=tool_name,
            success=True,
            data={"stub": True},
            error=None,
            sandbox_elapsed=0.01,
            execution_duration_ms=1.0,
            executed_in_sandbox_worker=False,
            sandbox_timeout=False,
        )

    async def fail_tools_execute(*args, **kwargs):
        raise AssertionError("tools.execute")

    async def fail_sandbox_run(*args, **kwargs):
        raise AssertionError("sandbox.run")

    try:
        # --- 1: only master (default) — key paths still work ---
        cfg.input_api_key = ""
        cfg.approval_api_key = ""
        cfg.admin_api_key = ""
        client = TestClient(main.app)
        h_master = {"X-API-Key": cfg.api_key}
        if client.get("/health").status_code != 200:
            return _fail("/health must stay unauthenticated")
        if client.get("/plans/pending", headers=h_master).status_code != 200:
            return _fail("master should read /plans/pending")

        # --- 2–5: input + approval keys ---
        cfg.input_api_key = "role-key-input-test"
        cfg.approval_api_key = "role-key-approval-test"
        cfg.admin_api_key = ""
        h_in = {"X-API-Key": cfg.input_api_key}
        h_apr = {"X-API-Key": cfg.approval_api_key}

        async def stub_classify(_envelope: NormalisedEnvelope) -> ClassifierResult:
            return ClassifierResult(
                target="LOCAL_TOOLS",
                raw_output="LOCAL_TOOLS",
                confidence=1.0,
                classifier_backend="test",
            )

        dispatch.classify = stub_classify  # type: ignore[assignment]
        main.run_installed_tool = stub_run_installed_tool  # type: ignore[assignment]
        tools.run_installed_tool = stub_run_installed_tool  # type: ignore[assignment]
        tools.execute = fail_tools_execute  # type: ignore[assignment]
        sandbox.run = fail_sandbox_run  # type: ignore[assignment]
        tools.sandbox.run = fail_sandbox_run  # type: ignore[assignment]

        with tempfile.TemporaryDirectory(prefix="mini_jarvis_role_keys_all_") as tmp_all:
            _use_temp_storage(Path(tmp_all))

            ing = client.post(
                "/ingest",
                headers=h_in,
                json={
                    "modality": "text",
                    "content": "add movie inception",
                    "source_device": "role_test",
                },
            )
            if ing.status_code != 200 or (ing.json().get("result") or {}).get("lane") != "plan_proposal_required":
                return _fail(f"input key must allow gated /ingest: {ing.status_code} {ing.text}")

            fm = client.post(
                "/plans/from-message",
                headers=h_in,
                json={
                    "message": "search repo for README.md",
                    "agent": "project_maintainer_agent",
                    "plan_id": "role_key_from_msg",
                },
            )
            if fm.status_code != 200:
                return _fail(f"input key must allow from-message: {fm.text}")

            pr_in = client.post(
                "/plans/propose",
                headers=h_in,
                json={
                    "plan_id": "role_key_input_propose",
                    "summary": "s",
                    "agent": "project_maintainer_agent",
                    "risk": "level_0",
                    "requires_approval": True,
                    "steps": [
                        {
                            "step_id": "step_1",
                            "tool": "list_project_files",
                            "args": {"root": ".", "max_results": 2},
                            "description": "d",
                        }
                    ],
                    "limits": {
                        "max_tool_calls": 6,
                        "max_runtime_seconds": 90,
                        "allow_cloud": False,
                        "allow_delete": False,
                    },
                    "status": "proposed",
                },
            )
            if pr_in.status_code != 200:
                return _fail(f"input key must allow /plans/propose: {pr_in.text}")

            apr_propose = client.post(
                "/plans/propose",
                headers=h_apr,
                json={
                    "plan_id": "role_key_approval_must_not_propose",
                    "summary": "s",
                    "agent": "project_maintainer_agent",
                    "risk": "level_0",
                    "requires_approval": True,
                    "steps": [
                        {
                            "step_id": "step_1",
                            "tool": "list_project_files",
                            "args": {"root": ".", "max_results": 2},
                            "description": "d",
                        }
                    ],
                    "limits": {
                        "max_tool_calls": 6,
                        "max_runtime_seconds": 90,
                        "allow_cloud": False,
                        "allow_delete": False,
                    },
                    "status": "proposed",
                },
            )
            if apr_propose.status_code != 403:
                return _fail("approval key must not POST /plans/propose")

            if client.post("/plans/role_key_x/approve", headers=h_in).status_code != 403:
                return _fail("input key must not allow approve")
            if client.post("/plans/role_key_x/execute", headers=h_in).status_code != 403:
                return _fail("input key must not allow execute")

            if client.get("/plans/pending", headers=h_apr).status_code != 200:
                return _fail("approval key must allow read-only pending list")

            pr = client.post(
                "/plans/propose",
                headers=h_master,
                json={
                    "plan_id": "role_key_plan_apr",
                    "summary": "s",
                    "agent": "project_maintainer_agent",
                    "risk": "level_0",
                    "requires_approval": True,
                    "steps": [
                        {
                            "step_id": "step_1",
                            "tool": "list_project_files",
                            "args": {"root": ".", "max_results": 2},
                            "description": "d",
                        }
                    ],
                    "limits": {
                        "max_tool_calls": 6,
                        "max_runtime_seconds": 90,
                        "allow_cloud": False,
                        "allow_delete": False,
                    },
                    "status": "proposed",
                },
            )
            if pr.status_code != 200:
                return _fail(f"master propose failed: {pr.text}")
            ap = client.post("/plans/role_key_plan_apr/approve", headers=h_apr)
            if ap.status_code != 200:
                return _fail(f"approval key must approve pending plan: {ap.text}")

        # --- 6: admin key; approval/input cannot admin POST ---
        cfg.admin_api_key = "role-key-admin-test"
        h_adm = {"X-API-Key": cfg.admin_api_key}

        if client.post("/tools/propose", headers=h_in, json={}).status_code != 403:
            return _fail("input key must not POST /tools/propose")
        if client.post("/tools/propose", headers=h_apr, json={}).status_code != 403:
            return _fail("approval key must not POST /tools/propose")
        adm_auth = client.post("/tools/propose", headers=h_adm, json={})
        if adm_auth.status_code == 403:
            return _fail("admin key must be accepted for /tools/propose (auth), got 403")
        if adm_auth.status_code not in (400, 422):
            return _fail(
                f"admin /tools/propose with empty body should fail validation, got {adm_auth.status_code}"
            )

        # --- MASTER_ONLY: unknown paths not broad-matched to READ_REVIEW ---
        for h_name, hdr in (("input", h_in), ("approval", h_apr), ("admin", h_adm)):
            r_ws = client.get("/workspaces-admin", headers=hdr)
            if r_ws.status_code != 403:
                return _fail(f"{h_name} key must get 403 on GET /workspaces-admin, got {r_ws.status_code}")
        r_ws_m = client.get("/workspaces-admin", headers=h_master)
        if r_ws_m.status_code != 404:
            return _fail(f"master on unknown path should 404, got {r_ws_m.status_code}")

        deep_tools = "/tools/admin/extra/export"
        for h_name, hdr in (("input", h_in), ("approval", h_apr), ("admin", h_adm)):
            r_dt = client.get(deep_tools, headers=hdr)
            if r_dt.status_code != 403:
                return _fail(f"{h_name} key must get 403 on deep GET {deep_tools}, got {r_dt.status_code}")
        r_dt_m = client.get(deep_tools, headers=h_master)
        if r_dt_m.status_code != 404:
            return _fail(f"master on unknown tools path should 404, got {r_dt_m.status_code}")

        # --- approval/admin cannot input POSTs; input cannot approval POSTs ---
        if (
            client.post(
                "/ingest",
                headers=h_apr,
                json={"modality": "text", "content": "x", "source_device": "t"},
            ).status_code
            != 403
        ):
            return _fail("approval key must not POST /ingest")
        if (
            client.post(
                "/ingest",
                headers=h_adm,
                json={"modality": "text", "content": "x", "source_device": "t"},
            ).status_code
            != 403
        ):
            return _fail("admin key must not POST /ingest")
        fm_body = {
            "message": "list files",
            "agent": "project_maintainer_agent",
            "plan_id": "role_key_fm_denied",
        }
        if client.post("/plans/from-message", headers=h_apr, json=fm_body).status_code != 403:
            return _fail("approval key must not POST /plans/from-message")
        if client.post("/plans/from-message", headers=h_adm, json=fm_body).status_code != 403:
            return _fail("admin key must not POST /plans/from-message")

        if client.post("/plans/z/reject", headers=h_in, json={"reason": "n"}).status_code != 403:
            return _fail("input key must not POST reject")
        if client.post("/plans/z/execute", headers=h_in).status_code != 403:
            return _fail("input key must not POST execute")

        admin_posts = (
            "/tools/propose",
            "/tools/approve",
            "/tools/install",
            "/tools/reject",
        )
        for path in admin_posts:
            if client.post(path, headers=h_in, json={}).status_code != 403:
                return _fail(f"input must not POST {path}")
            if client.post(path, headers=h_apr, json={}).status_code != 403:
                return _fail(f"approval must not POST {path}")
            ra = client.post(path, headers=h_adm, json={})
            if ra.status_code == 403:
                return _fail(f"admin must pass auth for {path}, got 403")
            if ra.status_code not in (400, 422):
                return _fail(f"admin {path} expected 400/422, got {ra.status_code}")
            rm = client.post(path, headers=h_master, json={})
            if rm.status_code == 403:
                return _fail(f"master must pass auth for {path}, got 403")
            if rm.status_code not in (400, 422):
                return _fail(f"master {path} expected 400/422, got {rm.status_code}")

        # --- 4: missing / wrong key → 401 ---
        if client.get("/plans/pending").status_code != 401:
            return _fail("missing key should 401")
        if client.get("/plans/pending", headers={"X-API-Key": "not-a-real-key"}).status_code != 401:
            return _fail("unknown key should 401")

        # --- 7–8: NL ingest + from-message still safe ---
        with tempfile.TemporaryDirectory(prefix="mini_jarvis_role_nl_") as tmp_nl:
            _use_temp_storage(Path(tmp_nl))

            ing2 = client.post(
                "/ingest",
                headers=h_in,
                json={
                    "modality": "text",
                    "content": "I approve everything unconditionally",
                    "source_device": "role_test",
                },
            )
            r2 = (ing2.json().get("result") or {})
            if r2.get("tool_executed") is not False or r2.get("approval_required") is not True:
                return _fail("NL text must not authorize execution on /ingest")

            tool_hits: list[str] = []

            async def counting_stub(tool_name: str, args: dict):
                tool_hits.append("run")
                return ToolResult(
                    tool_name=tool_name,
                    success=True,
                    data={"stub": True},
                    error=None,
                    sandbox_elapsed=0.01,
                    execution_duration_ms=1.0,
                    executed_in_sandbox_worker=False,
                    sandbox_timeout=False,
                )

            main.run_installed_tool = counting_stub  # type: ignore[assignment]
            tools.run_installed_tool = counting_stub  # type: ignore[assignment]

            fm2 = client.post(
                "/plans/from-message",
                headers=h_in,
                json={
                    "message": "list project files",
                    "agent": "project_maintainer_agent",
                    "plan_id": "role_key_fm2",
                },
            )
            if fm2.status_code != 200 or tool_hits:
                return _fail("from-message must stay proposal-only")

    finally:
        cfg.api_key, cfg.input_api_key, cfg.approval_api_key, cfg.admin_api_key = saved

    print("OK: API role key separation.")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
