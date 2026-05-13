#!/usr/bin/env python3
"""
Per-plan filesystem transition locks (data/plans/locks/<plan_id>.lockdir).

Fail-closed on contention; execute path must not run policy/tools when lock not held.
"""

from __future__ import annotations

import inspect
import re
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


def _minimal_plan(plan_id: str, *, tool: str = "list_project_files") -> Plan:
    return Plan(
        plan_id=plan_id,
        summary="lock test",
        agent="project_maintainer_agent",
        risk="level_0",  # type: ignore[arg-type]
        requires_approval=True,
        steps=[
            PlanStep(
                step_id="s1",
                tool=tool,
                args={"root": ".", "max_results": 2},
                description="x",
            )
        ],
        limits=PlanLimits(),
        status="proposed",
    )


def main_test() -> int:
    # --- static: HTTP execute uses async lock (no event-loop blocking time.sleep on contention) ---
    exec_src = inspect.getsource(main.plans_execute)
    if "async_plan_transition_lock" not in exec_src:
        return _fail("plans_execute must use async_plan_transition_lock")
    if re.search(r"(?<!async_)plan_transition_lock\s*\(", exec_src):
        return _fail("plans_execute must not call sync plan_transition_lock(...)")
    async_lock_src = inspect.getsource(approvals.async_plan_transition_lock)
    if "time.sleep" in async_lock_src:
        return _fail("async_plan_transition_lock must not use blocking time.sleep")
    if "asyncio.sleep" not in async_lock_src:
        return _fail("async_plan_transition_lock should await asyncio.sleep while polling")

    saved_timeout = approvals.PLAN_LOCK_DEFAULT_TIMEOUT
    approvals.PLAN_LOCK_DEFAULT_TIMEOUT = 0.12
    saved = main.cfg.api_key
    main.cfg.api_key = "lock-test-master-key"
    headers = {"X-API-Key": main.cfg.api_key}

    eval_calls: list[str] = []
    tool_calls: list[str] = []
    sandbox_calls: list[str] = []

    real_eval = main.evaluate_plan

    def counting_evaluate(plan, installed_tools=None, active_session=None):
        eval_calls.append("eval")
        return real_eval(plan, installed_tools=installed_tools, active_session=active_session)

    async def counting_run_tool(*a, **k):
        tool_calls.append("tool")
        return await orig_run(*a, **k)

    orig_run = main.run_installed_tool

    async def counting_sandbox(*a, **k):
        sandbox_calls.append("sandbox")
        return await orig_sandbox(*a, **k)

    orig_sandbox = sandbox.run

    main.evaluate_plan = counting_evaluate  # type: ignore[assignment]
    main.run_installed_tool = counting_run_tool  # type: ignore[assignment]
    tools.run_installed_tool = counting_run_tool  # type: ignore[assignment]
    sandbox.run = counting_sandbox  # type: ignore[assignment]
    tools.sandbox.run = counting_sandbox  # type: ignore[assignment]

    try:
        with tempfile.TemporaryDirectory(prefix="mini_jarvis_file_lock_") as tmp:
            root = Path(tmp)
            _use_temp_storage(root)
            client = TestClient(main.app)
            pid = "file_lock_plan_a"

            # --- approve / reject / mark_executed release locks ---
            client.post("/plans/propose", headers=headers, json=_minimal_plan(pid).model_dump())
            approvals.approve_plan(pid)
            lp = approvals._lock_path_for(pid)
            if lp.exists():
                return _fail(f"lock dir should not exist after approve: {lp}")

            pid2 = "file_lock_plan_rej"
            client.post("/plans/propose", headers=headers, json=_minimal_plan(pid2).model_dump())
            approvals.reject_plan(pid2, reason="n")
            if approvals._lock_path_for(pid2).exists():
                return _fail("lock dir after reject")

            pid3 = "file_lock_plan_ex"
            client.post("/plans/propose", headers=headers, json=_minimal_plan(pid3).model_dump())
            approvals.approve_plan(pid3)
            approvals.mark_executed(pid3, result={"ok": True})
            if approvals._lock_path_for(pid3).exists():
                return _fail("lock dir after mark_executed")

            # --- lock path confinement: invalid plan_id ---
            try:
                approvals._lock_path_for("bad/plan")
                return _fail("expected ValueError for bad plan_id")
            except ValueError:
                pass

            # --- approve with pre-existing lock → 409 ---
            pid4 = "file_lock_plan_contend"
            client.post("/plans/propose", headers=headers, json=_minimal_plan(pid4).model_dump())
            approvals._lock_path_for(pid4).mkdir(parents=True, exist_ok=True)
            ra = client.post(f"/plans/{pid4}/approve", headers=headers)
            approvals._lock_path_for(pid4).rmdir()
            if ra.status_code != 409 or ra.json().get("detail", {}).get("status") != "plan_transition_locked":
                return _fail(f"approve under lock expected 409 plan_transition_locked: {ra.status_code} {ra.text}")
            if not approvals._path_for(pid4, "pending").is_file():
                return _fail("pending must remain when approve blocked by lock")

            # clear lock contention; approve for later execute tests
            client.post(f"/plans/{pid4}/approve", headers=headers)

            # --- execute: lock held → 409, no policy/tools ---
            pid5 = "file_lock_exec_block"
            client.post("/plans/propose", headers=headers, json=_minimal_plan(pid5).model_dump())
            client.post(f"/plans/{pid5}/approve", headers=headers)
            eval_calls.clear()
            tool_calls.clear()
            sandbox_calls.clear()
            approvals._lock_path_for(pid5).mkdir(parents=True, exist_ok=True)
            exec_resp = client.post(f"/plans/{pid5}/execute", headers=headers)
            approvals._lock_path_for(pid5).rmdir()
            if exec_resp.status_code != 409:
                return _fail(f"execute under lock expected 409, got {exec_resp.status_code} {exec_resp.text}")
            det = exec_resp.json().get("detail") or {}
            if det.get("status") != "plan_transition_locked":
                return _fail(f"execute lock body wrong: {exec_resp.json()}")
            if eval_calls or tool_calls or sandbox_calls:
                return _fail("execute must not run policy/tools when lock not acquired")

            # --- execute success still works ---
            eval_calls.clear()
            tool_calls.clear()
            rex = client.post(f"/plans/{pid5}/execute", headers=headers)
            if rex.status_code != 200:
                return _fail(f"execute after lock release failed: {rex.status_code} {rex.text}")
            if not eval_calls:
                return _fail("policy should run on successful execute")

    finally:
        approvals.PLAN_LOCK_DEFAULT_TIMEOUT = saved_timeout
        main.cfg.api_key = saved
        main.evaluate_plan = real_eval  # type: ignore[assignment]
        main.run_installed_tool = orig_run  # type: ignore[assignment]
        tools.run_installed_tool = orig_run  # type: ignore[assignment]
        sandbox.run = orig_sandbox  # type: ignore[assignment]
        tools.sandbox.run = orig_sandbox  # type: ignore[assignment]

    print("OK: approval file locking.")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
