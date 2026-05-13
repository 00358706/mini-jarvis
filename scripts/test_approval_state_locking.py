#!/usr/bin/env python3
"""
Regression: approval bound to plan content hash; execute fail-closed; no double execute.
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
import main
import notifications
import sandbox
import tools
import workspace
from models import ToolResult


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


def _minimal_maintainer_plan(plan_id: str) -> dict:
    return {
        "plan_id": plan_id,
        "summary": "hash lock test plan",
        "agent": "project_maintainer_agent",
        "risk": "level_0",
        "requires_approval": True,
        "steps": [
            {
                "step_id": "step_1",
                "tool": "list_project_files",
                "args": {"root": ".", "max_results": 5},
                "description": "read-only list",
            }
        ],
        "limits": {
            "max_tool_calls": 6,
            "max_runtime_seconds": 90,
            "allow_cloud": False,
            "allow_delete": False,
        },
        "status": "proposed",
        "reviewed_plan_sha256": "client_should_not_trust_this_deadbeef",
        "approved_plan_sha256": "client_should_not_trust_this_cafebabe",
    }


def main_test() -> int:
    tool_calls: list[tuple[str, dict]] = []

    async def stub_run_installed_tool(tool_name: str, args: dict):
        tool_calls.append((tool_name, args))
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

    main.run_installed_tool = stub_run_installed_tool
    tools.run_installed_tool = stub_run_installed_tool

    async def fail_sandbox_run(*args, **kwargs):
        raise AssertionError("sandbox.run must not be reached when hash gate fails")

    sandbox.run = fail_sandbox_run
    tools.sandbox.run = fail_sandbox_run

    with tempfile.TemporaryDirectory(prefix="mini_jarvis_approval_lock_") as tmp:
        root = Path(tmp)
        _use_temp_storage(root)
        client = TestClient(main.app)
        headers = {"X-API-Key": main.cfg.api_key}

        plan_id = "approval_lock_test_001"
        body = _minimal_maintainer_plan(plan_id)

        r_prop = client.post("/plans/propose", headers=headers, json=body)
        if r_prop.status_code != 200:
            print("propose failed:", r_prop.text)
            return 1
        if r_prop.json().get("status") != "pending_approval":
            print("unexpected propose:", r_prop.json())
            return 1

        pending_path = approvals._path_for(plan_id, "pending")
        raw_pending = json.loads(pending_path.read_text(encoding="utf-8"))
        reviewed = raw_pending.get("reviewed_plan_sha256")
        if not reviewed or not isinstance(reviewed, str):
            print("missing reviewed_plan_sha256 on pending")
            return 1
        if reviewed in (
            "client_should_not_trust_this_deadbeef",
            "client_should_not_trust_this_cafebabe",
        ):
            print("client-supplied hash was persisted (must be server-owned)")
            return 1
        if approvals.compute_plan_sha256(raw_pending) != reviewed:
            print("pending hash mismatch recompute")
            return 1

        r_get = client.get(f"/plans/pending/{plan_id}", headers=headers)
        if r_get.status_code != 200:
            print("pending get failed:", r_get.text)
            return 1
        j = r_get.json()
        if j.get("reviewed_plan_sha256") != reviewed:
            print("GET pending missing hash echo")
            return 1

        tool_calls.clear()
        r_apr = client.post(f"/plans/{plan_id}/approve", headers=headers)
        if r_apr.status_code != 200:
            print("approve failed:", r_apr.text)
            return 1
        if tool_calls:
            print("approve must not execute tools:", tool_calls)
            return 1

        approved_path = approvals._path_for(plan_id, "approved")
        raw_ap = json.loads(approved_path.read_text(encoding="utf-8"))
        aph = raw_ap.get("approved_plan_sha256")
        if not aph or aph != reviewed:
            print("approved_plan_sha256 missing or wrong", aph, reviewed)
            return 1

        tool_calls.clear()
        r_ex1 = client.post(f"/plans/{plan_id}/execute", headers=headers)
        if r_ex1.status_code != 200:
            print("first execute failed:", r_ex1.text)
            return 1
        if len(tool_calls) < 1:
            print("expected first execute to call run_installed_tool")
            return 1

        tool_calls.clear()
        r_ex2 = client.post(f"/plans/{plan_id}/execute", headers=headers)
        if r_ex2.status_code != 409:
            print("expected 409 already_executed, got", r_ex2.status_code, r_ex2.text)
            return 1
        if tool_calls:
            print("second execute must not run tools:", tool_calls)
            return 1

        # --- new plan id for mutation / missing-hash tests ---
        plan_id_b = "approval_lock_test_002"
        body_b = _minimal_maintainer_plan(plan_id_b)
        body_b["summary"] = "mutation test"
        r2 = client.post("/plans/propose", headers=headers, json=body_b)
        if r2.status_code != 200:
            print("propose b failed:", r2.text)
            return 1
        client.post(f"/plans/{plan_id_b}/approve", headers=headers)
        raw_b = json.loads(approvals._path_for(plan_id_b, "approved").read_text(encoding="utf-8"))
        raw_b["summary"] = "tampered after approval"
        approvals._path_for(plan_id_b, "approved").write_text(
            json.dumps(raw_b, indent=2), encoding="utf-8"
        )
        tool_calls.clear()
        r_mut = client.post(f"/plans/{plan_id_b}/execute", headers=headers)
        if r_mut.status_code != 400:
            print("expected 400 on tampered plan, got", r_mut.status_code, r_mut.text)
            return 1
        if tool_calls:
            print("tampered execute must not call tools:", tool_calls)
            return 1

        plan_id_c = "approval_lock_test_003"
        body_c = _minimal_maintainer_plan(plan_id_c)
        body_c["summary"] = "missing approved hash test"
        r3 = client.post("/plans/propose", headers=headers, json=body_c)
        if r3.status_code != 200:
            print("propose c failed:", r3.text)
            return 1
        client.post(f"/plans/{plan_id_c}/approve", headers=headers)
        raw_c = json.loads(approvals._path_for(plan_id_c, "approved").read_text(encoding="utf-8"))
        del raw_c["approved_plan_sha256"]
        approvals._path_for(plan_id_c, "approved").write_text(
            json.dumps(raw_c, indent=2), encoding="utf-8"
        )
        tool_calls.clear()
        r_miss = client.post(f"/plans/{plan_id_c}/execute", headers=headers)
        if r_miss.status_code != 400:
            print("expected 400 missing hash, got", r_miss.status_code, r_miss.text)
            return 1
        if tool_calls:
            print("missing-hash execute must not call tools:", tool_calls)
            return 1

        # --- reject cannot execute ---
        plan_id_d = "approval_lock_test_004"
        body_d = _minimal_maintainer_plan(plan_id_d)
        body_d["summary"] = "reject path"
        r4 = client.post("/plans/propose", headers=headers, json=body_d)
        if r4.status_code != 200:
            print("propose d failed:", r4.text)
            return 1
        client.post(
            f"/plans/{plan_id_d}/reject",
            headers=headers,
            json={"reason": "test reject"},
        )
        tool_calls.clear()
        r_rej_ex = client.post(f"/plans/{plan_id_d}/execute", headers=headers)
        if r_rej_ex.status_code == 200:
            print("rejected plan must not execute")
            return 1
        if tool_calls:
            print("reject execute must not call tools:", tool_calls)
            return 1

        # --- legacy pending without hash: approve fails ---
        plan_id_e = "approval_lock_legacy_pending"
        legacy = {
            "plan_id": plan_id_e,
            "summary": "legacy",
            "agent": "project_maintainer_agent",
            "risk": "level_0",
            "requires_approval": True,
            "steps": [
                {
                    "step_id": "step_1",
                    "tool": "list_project_files",
                    "args": {"root": ".", "max_results": 3},
                    "description": "x",
                }
            ],
            "limits": {
                "max_tool_calls": 6,
                "max_runtime_seconds": 90,
                "allow_cloud": False,
                "allow_delete": False,
            },
            "status": "pending_approval",
        }
        approvals._ensure_trees()
        approvals._path_for(plan_id_e, "pending").write_text(
            json.dumps(legacy, indent=2), encoding="utf-8"
        )
        r_leg = client.post(f"/plans/{plan_id_e}/approve", headers=headers)
        if r_leg.status_code != 400:
            print("expected 400 approve on legacy pending without hash", r_leg.status_code)
            return 1

        # --- pending content changed vs stored reviewed hash: approve fails ---
        plan_id_f = "approval_lock_stale_review"
        body_f = _minimal_maintainer_plan(plan_id_f)
        body_f["summary"] = "stale review"
        r5 = client.post("/plans/propose", headers=headers, json=body_f)
        if r5.status_code != 200:
            print("propose f failed:", r5.text)
            return 1
        p_path = approvals._path_for(plan_id_f, "pending")
        stale = json.loads(p_path.read_text(encoding="utf-8"))
        stale["summary"] = "changed without recomputing hash"
        p_path.write_text(json.dumps(stale, indent=2), encoding="utf-8")
        r_stale = client.post(f"/plans/{plan_id_f}/approve", headers=headers)
        if r_stale.status_code != 400:
            print("expected 400 stale pending hash", r_stale.status_code, r_stale.text)
            return 1

    print("OK: approval state locking and execute gates.")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
