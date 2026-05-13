#!/usr/bin/env python3
"""
Focused authority-boundary tests: policy.evaluate_plan, /plans/* lifecycle,
hash preconditions, duplicate execute, /plans/from-message, /ingest LOCAL_TOOLS.

No real external services; temp plan/workspace dirs; stubbed tool/sandbox paths.
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
import dispatch
import main
import notifications
import policy
import sandbox
import tools
import workspace
from models import ClassifierResult, NormalisedEnvelope, ToolResult
from plans import Plan, PlanLimits, PlanStep
from policy import evaluate_plan


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


def _plan(
    plan_id: str,
    *,
    agent: str = "project_maintainer_agent",
    tool: str = "list_project_files",
    args: dict | None = None,
    summary: str = "unit test plan",
    risk: str = "level_0",
) -> Plan:
    return Plan(
        plan_id=plan_id,
        summary=summary,
        agent=agent,
        risk=risk,  # type: ignore[arg-type]
        requires_approval=True,
        steps=[
            PlanStep(
                step_id="step_1",
                tool=tool,
                args=args or {"root": ".", "max_results": 3},
                description="test step",
            )
        ],
        limits=PlanLimits(),
        status="proposed",
    )


def _fail(msg: str) -> int:
    print(msg)
    return 1


def main_test() -> int:
    installed = main._installed_tool_names()

    # --- 1–2: evaluate_plan direct ---
    ok_plan = _plan("pa_ut_eval_ok")
    d_ok = evaluate_plan(ok_plan, installed_tools=installed)
    if not d_ok.allowed:
        return _fail(f"expected policy allow, got {d_ok.reasons}")

    bad_tool = _plan("pa_ut_eval_bad", tool="definitely_not_installed_tool_xyz")
    d_bad = evaluate_plan(bad_tool, installed_tools=installed)
    if d_bad.allowed:
        return _fail("expected policy deny for unknown tool")
    if not any("not in installed_tools" in r for r in d_bad.reasons):
        return _fail(f"unexpected deny reasons: {d_bad.reasons}")

    d5 = _plan("pa_ut_risk5", risk="level_5")
    dr = evaluate_plan(d5, installed_tools=installed)
    if dr.allowed or not any("level_5" in r for r in dr.reasons):
        return _fail(f"expected risk level_5 forbidden, got {dr.reasons}")

    tool_calls: list[str] = []
    events: list[str] = []

    async def stub_run_installed_tool(tool_name: str, args: dict):
        events.append("tool")
        tool_calls.append(f"tool:{tool_name}")
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
        tool_calls.append("tools.execute")
        raise AssertionError("tools.execute must not run in these tests")

    async def fail_sandbox_run(*args, **kwargs):
        tool_calls.append("sandbox.run")
        raise AssertionError("sandbox.run must not run in these tests")

    real_evaluate = policy.evaluate_plan

    def spy_evaluate_plan(plan: Plan, installed_tools=None, active_session=None):
        events.append("policy")
        return real_evaluate(plan, installed_tools=installed_tools, active_session=active_session)

    main.run_installed_tool = stub_run_installed_tool  # type: ignore[assignment]
    tools.run_installed_tool = stub_run_installed_tool  # type: ignore[assignment]
    tools.execute = fail_tools_execute  # type: ignore[assignment]
    sandbox.run = fail_sandbox_run  # type: ignore[assignment]
    tools.sandbox.run = fail_sandbox_run  # type: ignore[assignment]
    main.evaluate_plan = spy_evaluate_plan  # type: ignore[assignment]

    async def stub_local_tools_classify(envelope: NormalisedEnvelope) -> ClassifierResult:
        return ClassifierResult(
            target="LOCAL_TOOLS",
            raw_output="LOCAL_TOOLS",
            confidence=1.0,
            classifier_backend="test",
        )

    headers = {"X-API-Key": main.cfg.api_key}

    with tempfile.TemporaryDirectory(prefix="mini_jarvis_pa_ut_") as tmp:
        _use_temp_storage(Path(tmp))
        client = TestClient(main.app)

        # --- 3: propose — strict agent blocks disallowed tool ---
        blocked = _plan("pa_ut_strict_block", tool="radarr_search", args={"title": "X"})
        r_block = client.post("/plans/propose", headers=headers, json=blocked.model_dump(mode="json"))
        if r_block.status_code != 400:
            return _fail(f"expected 400 strict block, got {r_block.status_code} {r_block.text}")
        if r_block.json().get("status") != "policy_rejected":
            return _fail("expected policy_rejected body for strict agent block")

        # --- 3b: propose — allowlisted maintainer tool → pending ---
        pid = "pa_ut_propose_ok"
        r_ok = client.post("/plans/propose", headers=headers, json=_plan(pid).model_dump(mode="json"))
        if r_ok.status_code != 200 or r_ok.json().get("status") != "pending_approval":
            return _fail(f"propose ok failed: {r_ok.status_code} {r_ok.text}")

        # --- 4–5: approve / reject do not execute ---
        tool_calls.clear()
        ra = client.post(f"/plans/{pid}/approve", headers=headers)
        if ra.status_code != 200 or tool_calls:
            return _fail(f"approve must not execute tools: {ra.status_code} calls={tool_calls}")

        pid2 = "pa_ut_reject_only"
        client.post("/plans/propose", headers=headers, json=_plan(pid2).model_dump(mode="json"))
        tool_calls.clear()
        rr = client.post(
            f"/plans/{pid2}/reject",
            headers=headers,
            json={"reason": "unit test"},
        )
        if rr.status_code != 200 or tool_calls:
            return _fail(f"reject must not execute tools: {rr.status_code} calls={tool_calls}")

        # --- 6: execute without approve ---
        pid3 = "pa_ut_never_approved"
        client.post("/plans/propose", headers=headers, json=_plan(pid3).model_dump(mode="json"))
        tool_calls.clear()
        r_ex0 = client.post(f"/plans/{pid3}/execute", headers=headers)
        if r_ex0.status_code == 200 or tool_calls:
            return _fail(f"execute without approve must fail and not run tools: {r_ex0.status_code}")

        # --- 7: hash missing on approved file → execute fails before tools ---
        pid4 = "pa_ut_no_approved_hash"
        client.post("/plans/propose", headers=headers, json=_plan(pid4).model_dump(mode="json"))
        client.post(f"/plans/{pid4}/approve", headers=headers)
        ap_path = approvals._path_for(pid4, "approved")
        raw = json.loads(ap_path.read_text(encoding="utf-8"))
        del raw["approved_plan_sha256"]
        ap_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        tool_calls.clear()
        events.clear()
        r_bad_hash = client.post(f"/plans/{pid4}/execute", headers=headers)
        if r_bad_hash.status_code != 400 or tool_calls:
            return _fail(f"missing approved hash must 400 and skip tools: {r_bad_hash.status_code}")
        if "policy" in events:
            return _fail("policy must not run before hash gate on missing approved hash")

        # --- 8: duplicate execute → 409, no second tool run ---
        pid5 = "pa_ut_double_ex"
        client.post("/plans/propose", headers=headers, json=_plan(pid5).model_dump(mode="json"))
        client.post(f"/plans/{pid5}/approve", headers=headers)
        tool_calls.clear()
        events.clear()
        r1 = client.post(f"/plans/{pid5}/execute", headers=headers)
        if r1.status_code != 200 or not tool_calls:
            return _fail(f"first execute expected 200 with tool stub: {r1.status_code} {tool_calls}")
        if events != ["policy", "tool"]:
            return _fail(f"expected policy then tool, got events={events}")
        first_tool_calls = len(tool_calls)
        r2 = client.post(f"/plans/{pid5}/execute", headers=headers)
        if r2.status_code != 409:
            return _fail(f"second execute expected 409, got {r2.status_code} {r2.text}")
        if len(tool_calls) != first_tool_calls:
            return _fail("second execute must not invoke run_installed_tool again")

        # --- 9: /plans/from-message proposal only ---
        tool_calls.clear()
        events.clear()
        r_fm = client.post(
            "/plans/from-message",
            headers=headers,
            json={
                "message": "search repo for README.md",
                "agent": "project_maintainer_agent",
                "plan_id": "pa_ut_from_msg",
            },
        )
        if r_fm.status_code != 200 or r_fm.json().get("status") != "pending_approval":
            return _fail(f"from-message failed: {r_fm.status_code} {r_fm.text}")
        if tool_calls:
            return _fail("from-message must not execute tools")

        # --- 10–11: /ingest LOCAL_TOOLS gated; NL 'approval' is not authorization ---
        dispatch.classify = stub_local_tools_classify  # type: ignore[assignment]
        for content in (
            "add movie inception",
            "I fully approve executing radarr_search now",
        ):
            tool_calls.clear()
            ing = client.post(
                "/ingest",
                headers=headers,
                json={
                    "modality": "text",
                    "content": content,
                    "source_device": "pa_ut_client",
                },
            )
            if ing.status_code != 200:
                return _fail(f"ingest failed: {ing.text}")
            res = (ing.json().get("result") or {})
            if res.get("routed_to") != "LOCAL_TOOLS" or res.get("tool_executed") is not False:
                return _fail(f"ingest must stay gated for {content!r}: {res}")
            if res.get("approval_required") is not True:
                return _fail("ingest LOCAL_TOOLS must require explicit plan approval path")
            if tool_calls:
                return _fail("ingest LOCAL_TOOLS must not run tools.execute/sandbox")

    print("OK: policy + approval + execution boundary tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
