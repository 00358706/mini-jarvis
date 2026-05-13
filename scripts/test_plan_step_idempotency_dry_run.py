#!/usr/bin/env python3
"""
Plan step StepSafety: defaults, validation, deterministic builder metadata,
persistence, compact workspace passthrough, and execute ignoring dry_run.

No real external services; stubs tool execution where needed.
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
from pydantic import ValidationError

import approvals
import main
import notifications
import sandbox
import tools
import workspace
from models import ToolResult
from plans import Plan, PlanLimits, PlanStep, StepSafety, plan_from_dict, plan_to_dict
from services.plan_builder import build_plan_from_message


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


def _read_only_expect(s: StepSafety) -> bool:
    return (
        s.dry_run is False
        and s.idempotent is True
        and s.idempotency_scope == "read-only"
        and s.rollback_notes == "No state mutation expected."
        and s.compensation_implemented is False
        and s.idempotency_key is None
        and s.compensation is None
    )


def main_test() -> int:
    raw = {
        "plan_id": "ps_min",
        "summary": "s",
        "agent": "project_maintainer_agent",
        "risk": "level_0",
        "requires_approval": True,
        "steps": [{"step_id": "step_1", "tool": "list_project_files", "args": {}}],
        "limits": {},
        "status": "proposed",
    }
    p = plan_from_dict(raw)
    if not isinstance(p.steps[0].safety, StepSafety):
        return _fail("expected default StepSafety on step")
    dflt = p.steps[0].safety
    if dflt.dry_run or dflt.idempotent or dflt.compensation_implemented:
        return _fail(f"unexpected non-default safety flags: {dflt.model_dump()}")

    try:
        StepSafety(compensation_implemented=True, compensation="")
        return _fail("expected ValidationError for empty compensation")
    except ValidationError:
        pass
    try:
        StepSafety(compensation_implemented=True, compensation="   ")
        return _fail("expected ValidationError for whitespace-only compensation")
    except ValidationError:
        pass
    ok_s = StepSafety(compensation_implemented=True, compensation="manual revert steps documented")
    if not ok_s.compensation:
        return _fail("valid compensation with flag should parse")

    installed = main._installed_tool_names()
    r_m = build_plan_from_message(
        message="list project files",
        agent="project_maintainer_agent",
        plan_id="ps_maint",
        installed_tool_names=installed,
    )
    if not hasattr(r_m, "plan"):
        return _fail(f"maintainer build unexpected: {r_m!r}")
    st0 = r_m.plan.steps[0]
    if st0.tool != "list_project_files" or not _read_only_expect(st0.safety):
        return _fail(f"maintainer step safety wrong: {st0.safety.model_dump()}")

    media_installed = set(installed) | {"radarr_search"}
    r_media = build_plan_from_message(
        message="search for movie TestFilm",
        agent="media_agent",
        plan_id="ps_media",
        installed_tool_names=media_installed,
    )
    if not hasattr(r_media, "plan"):
        return _fail(f"media build unexpected: {r_media!r}")
    if r_media.plan.steps[0].tool != "radarr_search":
        return _fail("expected radarr_search for media movie pattern")
    if not _read_only_expect(r_media.plan.steps[0].safety):
        return _fail(f"media step safety wrong: {r_media.plan.steps[0].safety.model_dump()}")

    with tempfile.TemporaryDirectory(prefix="mini_jarvis_ps_safety_") as tmp:
        root = Path(tmp)
        _use_temp_storage(root)
        tid = "ps_ws_task"
        workspace.create_workspace(tid, request_text="t")
        workspace.write_plan(tid, r_m.plan)
        plan_path = workspace._active_root(tid) / "PLAN.json"
        disk = json.loads(plan_path.read_text(encoding="utf-8"))
        steps_disk = disk.get("steps")
        if not isinstance(steps_disk, list) or not steps_disk:
            return _fail("PLAN.json missing steps")
        s0 = steps_disk[0].get("safety")
        if not isinstance(s0, dict) or s0.get("idempotency_scope") != "read-only":
            return _fail(f"PLAN.json safety missing or wrong: {s0!r}")

    orig_run = main.run_installed_tool
    orig_tools_run = tools.run_installed_tool
    orig_tools_execute = tools.execute
    orig_sb = sandbox.run
    orig_tools_sb = tools.sandbox.run

    tool_calls: list[str] = []

    async def stub_run_installed_tool(tool_name: str, args: dict):
        tool_calls.append(f"{tool_name}")
        return ToolResult(
            tool_name=tool_name,
            success=True,
            data={},
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

    headers = {"X-API-Key": main.cfg.api_key}

    try:
        main.run_installed_tool = stub_run_installed_tool  # type: ignore[assignment]
        tools.run_installed_tool = stub_run_installed_tool  # type: ignore[assignment]
        tools.execute = fail_tools_execute  # type: ignore[assignment]
        sandbox.run = fail_sandbox_run  # type: ignore[assignment]
        tools.sandbox.run = fail_sandbox_run  # type: ignore[assignment]

        with tempfile.TemporaryDirectory(prefix="mini_jarvis_ps_exec_") as tmp2:
            root2 = Path(tmp2)
            _use_temp_storage(root2)
            client = TestClient(main.app)

            pid = "ps_dry_run_exec"
            plan = Plan(
                plan_id=pid,
                summary="dry run flag must not skip execution",
                agent="project_maintainer_agent",
                risk="level_0",
                requires_approval=True,
                steps=[
                    PlanStep(
                        step_id="step_1",
                        tool="list_project_files",
                        args={"root": ".", "max_results": 2},
                        description="test",
                        safety=StepSafety(
                            dry_run=True,
                            idempotent=True,
                            idempotency_scope="read-only",
                            rollback_notes="evidence only",
                            compensation_implemented=False,
                        ),
                    )
                ],
                limits=PlanLimits(),
                status="proposed",
            )
            r_prop = client.post("/plans/propose", headers=headers, json=plan_to_dict(plan))
            if r_prop.status_code != 200:
                return _fail(f"propose failed: {r_prop.status_code} {r_prop.text}")
            pending_path = approvals._path_for(pid, "pending")
            pending_raw = json.loads(pending_path.read_text(encoding="utf-8"))
            ps = pending_raw.get("steps", [{}])[0].get("safety", {})
            if ps.get("dry_run") is not True:
                return _fail("pending plan JSON should preserve dry_run=true on step")

            r_apr = client.post(f"/plans/{pid}/approve", headers=headers)
            if r_apr.status_code != 200:
                return _fail(f"approve failed: {r_apr.status_code} {r_apr.text}")

            tool_calls.clear()
            r_ex = client.post(f"/plans/{pid}/execute", headers=headers)
            if r_ex.status_code != 200:
                return _fail(f"execute failed: {r_ex.status_code} {r_ex.text}")
            if tool_calls != ["list_project_files"]:
                return _fail(f"dry_run metadata must not skip tool run; calls={tool_calls}")

            cr = client.get("/workspaces/active/nonexistent_plan_xyz/compact", headers=headers)
            if cr.status_code != 404:
                return _fail(f"expected 404 for missing workspace compact, got {cr.status_code}")

            cc = client.get(f"/workspaces/completed/{pid}/compact", headers=headers)
            if cc.status_code != 200:
                return _fail(f"compact failed: {cc.status_code} {cc.text}")
            cj = cc.json()
            csteps = cj.get("steps")
            if not isinstance(csteps, list) or not csteps:
                return _fail("compact steps missing")
            cs = csteps[0].get("safety")
            if not isinstance(cs, dict) or cs.get("dry_run") is not True:
                return _fail(f"compact should echo step safety: {cs!r}")

    finally:
        main.run_installed_tool = orig_run  # type: ignore[assignment]
        tools.run_installed_tool = orig_tools_run  # type: ignore[assignment]
        tools.execute = orig_tools_execute  # type: ignore[assignment]
        sandbox.run = orig_sb  # type: ignore[assignment]
        tools.sandbox.run = orig_tools_sb  # type: ignore[assignment]

    print("OK: plan step StepSafety contracts.")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
