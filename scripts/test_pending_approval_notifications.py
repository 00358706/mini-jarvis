#!/usr/bin/env python3
"""
Pending-approval notifications: append-only JSONL + read-only GET endpoint.

Ensures informational records only (no approve/execute from notifications),
role-gated read, and no tool/sandbox/registry mutation during propose/from-message.
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
from plans import Plan, PlanLimits, PlanStep


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


def _plan(plan_id: str, *, summary: str = "notif test plan") -> Plan:
    return Plan(
        plan_id=plan_id,
        summary=summary,
        agent="project_maintainer_agent",
        risk="level_0",  # type: ignore[arg-type]
        requires_approval=True,
        steps=[
            PlanStep(
                step_id="s1",
                tool="list_project_files",
                args={"root": ".", "max_results": 2},
                description="x",
            )
        ],
        limits=PlanLimits(),
        status="proposed",
    )


def main_test() -> int:
    cfg = config.cfg
    saved = (cfg.api_key, cfg.input_api_key)

    approve_calls: list[str] = []
    reject_calls: list[str] = []
    execute_calls: list[str] = []
    tool_calls: list[str] = []
    sandbox_calls: list[str] = []
    registry_mutations: list[str] = []

    def track_approve(pid: str):
        approve_calls.append(pid)
        raise AssertionError("approve_plan must not run during this test path")

    def track_reject(pid: str, reason: str | None = None):
        reject_calls.append(pid)
        raise AssertionError("reject_plan must not run during this test path")

    def track_mark_executed(pid: str, result=None):
        execute_calls.append(pid)
        raise AssertionError("mark_executed must not run during this test path")

    async def track_run_tool(*args, **kwargs):
        tool_calls.append("run")
        raise AssertionError("tool execution must not run")

    async def track_sandbox(*args, **kwargs):
        sandbox_calls.append("sandbox")
        raise AssertionError("sandbox must not run")

    def track_reg(name: str):
        def inner(*a, **k):
            registry_mutations.append(name)
            raise AssertionError(f"registry.{name} must not run")

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

    cfg.api_key = "notif-master-test-key"
    cfg.input_api_key = "notif-input-test-key"
    h_master = {"X-API-Key": cfg.api_key}
    h_input = {"X-API-Key": cfg.input_api_key}

    try:
        with tempfile.TemporaryDirectory(prefix="mini_jarvis_notif_") as tmp:
            root = Path(tmp)
            _use_temp_storage(root)
            client = TestClient(main.app)
            jsonl_path = notifications.PENDING_APPROVALS_JSONL

            pr = client.post("/plans/propose", headers=h_input, json=_plan("notif_plan_a").model_dump())
            if pr.status_code != 200 or pr.json().get("status") != "pending_approval":
                return _fail(f"propose failed: {pr.status_code} {pr.text}")

            if approve_calls or reject_calls or execute_calls or tool_calls or sandbox_calls:
                return _fail("unexpected approve/reject/execute/tool/sandbox during propose")
            if registry_mutations:
                return _fail(f"unexpected registry calls: {registry_mutations}")

            if not jsonl_path.is_file():
                return _fail("pending_approvals.jsonl missing after propose")
            lines_a = [ln for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if len(lines_a) != 1:
                return _fail(f"expected 1 JSONL line after first propose, got {len(lines_a)}")
            rec_a = json.loads(lines_a[0])
            for key in (
                "notification_id",
                "plan_id",
                "agent",
                "summary",
                "risk",
                "action_required",
            ):
                if key not in rec_a:
                    return _fail(f"notification missing {key!r}")
            if rec_a.get("type") != "pending_approval":
                return _fail("wrong type")
            if rec_a.get("plan_id") != "notif_plan_a":
                return _fail("wrong plan_id")
            if rec_a.get("action_required") != "review_plan":
                return _fail("wrong action_required")
            if rec_a.get("can_approve") is not False or rec_a.get("can_execute") is not False:
                return _fail("can_approve / can_execute must be false")
            if rec_a.get("side_effect") != "none":
                return _fail("side_effect must be none")
            if "reviewed_plan_sha256" in rec_a or "approved_plan_sha256" in rec_a:
                return _fail("notification must not expose plan hashes")

            fm = client.post(
                "/plans/from-message",
                headers=h_input,
                json={
                    "message": "search repo for README.md",
                    "agent": "project_maintainer_agent",
                    "plan_id": "notif_plan_fm",
                },
            )
            if fm.status_code != 200 or fm.json().get("status") != "pending_approval":
                return _fail(f"from-message failed: {fm.status_code} {fm.text}")

            lines_b = [ln for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if len(lines_b) != 2:
                return _fail(f"expected 2 JSONL lines after from-message, got {len(lines_b)}")
            rec_fm = json.loads(lines_b[1])
            if rec_fm.get("plan_id") != "notif_plan_fm":
                return _fail("from-message notification plan_id mismatch")

            # Re-propose same id: append-only second line (file overwrite, JSONL grows)
            pr2 = client.post(
                "/plans/propose",
                headers=h_input,
                json=_plan("notif_plan_a", summary="second summary").model_dump(),
            )
            if pr2.status_code != 200:
                return _fail(f"second propose failed: {pr2.text}")
            lines_c = [ln for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if len(lines_c) != 3:
                return _fail(f"expected 3 JSONL lines after duplicate plan_id propose, got {len(lines_c)}")

            blob_before = jsonl_path.read_bytes()
            g1 = client.get("/notifications/pending-approvals", headers=h_input)
            if g1.status_code != 200:
                return _fail(f"input key GET notifications failed: {g1.status_code} {g1.text}")
            blob_after = jsonl_path.read_bytes()
            if blob_before != blob_after:
                return _fail("GET must not mutate notification file")
            body = g1.json()
            notes = body.get("notifications") or []
            if body.get("count") != len(notes) or len(notes) != 3:
                return _fail(f"GET count mismatch: {body!r}")

            ap = client.post("/plans/notif_plan_a/approve", headers=h_input, json={})
            if ap.status_code != 403:
                return _fail(f"input key must not approve, got {ap.status_code}")

            if approve_calls:
                return _fail("approve_plan should not be invoked for input 403")

            # Unknown path stays master-only (sanity: no broad /notifications prefix)
            if client.get("/notifications/other", headers=h_input).status_code != 403:
                return _fail("GET /notifications/other must be 403 for input key")

    finally:
        cfg.api_key, cfg.input_api_key = saved

    print("OK: pending approval notifications.")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
