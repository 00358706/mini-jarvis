#!/usr/bin/env python3
"""
Regression: POST /ingest with LOCAL_TOOLS must not execute tools or sandbox.

Also enforces that dispatch.py does not reference tools.execute on the ingest path.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient

import dispatch
import main
import sandbox
import tools
from models import ClassifierResult, NormalisedEnvelope


def _dispatch_source_must_not_invoke_tools_execute() -> int:
    root = Path(__file__).resolve().parents[1]
    text = (root / "dispatch.py").read_text(encoding="utf-8")
    if re.search(r"\btools_execute\b", text):
        print("dispatch.py must not reference tools_execute (ingest LOCAL_TOOLS is gated).")
        return 1
    if "from tools import" in text or "import tools" in text:
        print("dispatch.py must not import tools for execution on the ingest path.")
        return 1
    return 0


def main_test() -> int:
    if _dispatch_source_must_not_invoke_tools_execute():
        return 1

    calls: list[str] = []

    async def fail_tools_execute(*args, **kwargs):
        calls.append("tools.execute")
        raise AssertionError("POST /ingest must not call tools.execute for LOCAL_TOOLS")

    async def fail_sandbox_run(*args, **kwargs):
        calls.append("sandbox.run")
        raise AssertionError("POST /ingest must not call sandbox.run for LOCAL_TOOLS")

    tools.execute = fail_tools_execute  # type: ignore[assignment]
    sandbox.run = fail_sandbox_run  # type: ignore[assignment]
    tools.sandbox.run = fail_sandbox_run  # type: ignore[assignment]

    async def stub_classify(envelope: NormalisedEnvelope) -> ClassifierResult:
        return ClassifierResult(
            target="LOCAL_TOOLS",
            raw_output="LOCAL_TOOLS",
            confidence=1.0,
            classifier_backend="test",
        )

    dispatch.classify = stub_classify  # type: ignore[assignment]

    client = TestClient(main.app)
    response = client.post(
        "/ingest",
        headers={"X-API-Key": main.cfg.api_key},
        json={
            "modality": "text",
            "content": "add movie inception",
            "source_device": "test_client",
        },
    )

    if response.status_code != 200:
        print(response.text)
        return 1

    body = response.json()
    result = body.get("result") or {}
    if result.get("routed_to") != "LOCAL_TOOLS":
        print(f"Unexpected routed_to: {result!r}")
        return 1
    if result.get("lane") != "plan_proposal_required":
        print(f"Unexpected lane: {result!r}")
        return 1
    for key, expected in (
        ("tool_executed", False),
        ("sandbox_worker_invoked", False),
        ("approval_required", True),
    ):
        if result.get(key) is not expected:
            print(f"Expected result[{key!r}] == {expected}, got {result.get(key)!r}")
            return 1
    if not (result.get("message") or "").strip():
        print("Expected non-empty guidance message in result.")
        return 1

    if calls:
        print(f"Unexpected execution call(s): {calls}")
        return 1

    logs = client.get("/logs", headers={"X-API-Key": main.cfg.api_key}, params={"limit": 30})
    if logs.status_code != 200:
        print(logs.text)
        return 1
    payload = logs.json()
    entries = payload.get("entries") or []
    gated = [
        e
        for e in entries
        if (e.get("metadata") or {}).get("gate") == "ingest_tool_execution_disabled"
    ]
    if not gated:
        print("Expected audit entry with metadata.gate == ingest_tool_execution_disabled")
        return 1
    last = gated[-1]
    meta = last.get("metadata") or {}
    if last.get("route") != "LOCAL_TOOLS":
        print(f"Unexpected audit route: {last!r}")
        return 1
    if meta.get("tool_executed") is not False:
        print("Audit metadata.tool_executed must be false.")
        return 1
    if meta.get("sandbox_worker_invoked") is not False:
        print("Audit metadata.sandbox_worker_invoked must be false.")
        return 1
    if meta.get("approval_required") is not True:
        print("Audit metadata.approval_required must be true.")
        return 1

    print("OK: /ingest LOCAL_TOOLS is gated (no tools.execute / sandbox.run).")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
