#!/usr/bin/env python3
"""Focused tests for services.small_router context-budget fallback."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import cfg
from services.small_router import select_agent, select_route


def _fail(msg: str) -> int:
    print(msg)
    return 1


async def _run() -> int:
    original_safe = cfg.small_router_safe_input_tokens
    original_context = cfg.small_router_max_context
    original_output = cfg.small_router_max_output_tokens
    original_min_confidence = cfg.small_router_min_confidence
    cfg.small_router_safe_input_tokens = 1200
    cfg.small_router_max_context = 2048
    cfg.small_router_max_output_tokens = 128
    cfg.small_router_min_confidence = 0.60
    try:
        calls: list[dict[str, Any]] = []

        async def ok_call(messages: list[dict[str, str]], max_tokens: int) -> str:
            calls.append({"messages": messages, "max_tokens": max_tokens})
            return "project_maintainer_agent"

        short = await select_agent(
            message="List project files.",
            candidate_agents=["project_maintainer_agent", "media_agent"],
            model_call=ok_call,
        )
        if short.get("selected_agent") != "project_maintainer_agent":
            return _fail(f"short prompt selected wrong agent: {short}")
        if short.get("model_called") is not True or len(calls) != 1:
            return _fail(f"short prompt should call model exactly once: {short} calls={len(calls)}")
        if calls[0].get("max_tokens") != 128:
            return _fail(f"short prompt did not enforce SMALL_ROUTER_MAX_OUTPUT_TOKENS: {calls[0]}")
        if short.get("authority") is not False:
            return _fail(f"router output must remain authority=false: {short}")

        async def must_not_call(messages: list[dict[str, str]], max_tokens: int) -> str:
            raise AssertionError("oversized prompt should not call model")

        oversized = await select_agent(
            message="x" * 5000,
            candidate_agents=["project_maintainer_agent", "media_agent"],
            model_call=must_not_call,
        )
        if oversized.get("selected_agent") != "manual_agent_required":
            return _fail(f"oversized prompt should require manual agent: {oversized}")
        if oversized.get("reason") != "router_context_budget_exceeded":
            return _fail(f"oversized prompt wrong reason: {oversized}")
        if oversized.get("model_called") is not False:
            return _fail(f"oversized prompt should not call model: {oversized}")
        if oversized.get("authority") is not False:
            return _fail(f"oversized fallback must remain authority=false: {oversized}")

        error_calls = 0

        async def context_error_call(messages: list[dict[str, str]], max_tokens: int) -> str:
            nonlocal error_calls
            error_calls += 1
            raise RuntimeError("llama.cpp: requested tokens exceed context window")

        context_err = await select_agent(
            message="List project files.",
            candidate_agents=["project_maintainer_agent", "media_agent"],
            model_call=context_error_call,
        )
        if error_calls != 1:
            return _fail(f"context error should not be retried repeatedly: calls={error_calls}")
        if context_err.get("selected_agent") != "manual_agent_required":
            return _fail(f"context error should require manual agent: {context_err}")
        if context_err.get("reason") != "router_context_budget_exceeded":
            return _fail(f"context error wrong reason: {context_err}")
        if context_err.get("model_called") is not True:
            return _fail(f"context error fallback should record one model call: {context_err}")
        if context_err.get("tool_executed") is not False or context_err.get("approval_granted") is not False:
            return _fail(f"context error fallback must not execute/approve: {context_err}")

        async def unexpected_authority_call(messages: list[dict[str, str]], max_tokens: int) -> str:
            return '{"selected_agent":"media_agent","authority":true,"execute":true}'

        advisory = await select_agent(
            message="Search movie Blade Runner.",
            candidate_agents=["project_maintainer_agent", "media_agent"],
            model_call=unexpected_authority_call,
        )
        if advisory.get("authority") is not False:
            return _fail(f"router output still cannot authorize execution: {advisory}")
        if advisory.get("tool_executed") is not False or advisory.get("approval_granted") is not False:
            return _fail(f"router output must not execute/approve: {advisory}")

        manual_calls = 0

        async def manual_should_not_call(messages: list[dict[str, str]], max_tokens: int) -> str:
            nonlocal manual_calls
            manual_calls += 1
            return "media_agent"

        manual = await select_agent(
            message="Search movie Alien.",
            candidate_agents=["project_maintainer_agent", "media_agent"],
            manual_agent="media_agent",
            model_call=manual_should_not_call,
        )
        if manual_calls != 0:
            return _fail("manual agent selection should bypass tiny router")
        if manual.get("selected_agent") != "media_agent" or manual.get("reason") != "manual_agent_selected":
            return _fail(f"manual agent selection wrong response: {manual}")
        if manual.get("model_called") is not False or manual.get("authority") is not False:
            return _fail(f"manual agent selection must bypass model and remain advisory: {manual}")

        route_calls = 0

        async def route_call(messages: list[dict[str, str]], max_tokens: int) -> str:
            nonlocal route_calls
            route_calls += 1
            prompt = "\n".join(m.get("content", "") for m in messages)
            if "candidate_routes" not in prompt:
                raise AssertionError("router prompt should expose route ids, not full tool schemas")
            return '{"route":"media","confidence":0.91,"reason":"movie request"}'

        routed = await select_route(
            message="add movie Arrival",
            candidate_routes=["project_maintenance", "media"],
            route_to_agent={"project_maintenance": "project_maintainer_agent", "media": "media_agent"},
            model_call=route_call,
        )
        if route_calls != 1 or routed.get("selected_agent") != "media_agent":
            return _fail(f"automatic route did not select media_agent: {routed} calls={route_calls}")
        if routed.get("selected_route") != "media" or routed.get("authority") is not False:
            return _fail(f"route output must remain advisory: {routed}")

        async def invalid_json_call(messages: list[dict[str, str]], max_tokens: int) -> str:
            return "media"

        invalid_json = await select_route(
            message="add movie Arrival",
            candidate_routes=["project_maintenance", "media"],
            route_to_agent={"project_maintenance": "project_maintainer_agent", "media": "media_agent"},
            model_call=invalid_json_call,
        )
        if invalid_json.get("selected_agent") != "manual_agent_required" or invalid_json.get("reason") != "router_invalid_json":
            return _fail(f"invalid JSON must fall back safely: {invalid_json}")

        async def low_confidence_call(messages: list[dict[str, str]], max_tokens: int) -> str:
            return '{"route":"media","confidence":0.20,"reason":"not sure"}'

        low_confidence = await select_route(
            message="add movie Arrival",
            candidate_routes=["project_maintenance", "media"],
            route_to_agent={"project_maintenance": "project_maintainer_agent", "media": "media_agent"},
            model_call=low_confidence_call,
        )
        if low_confidence.get("selected_agent") != "manual_agent_required" or low_confidence.get("reason") != "router_low_confidence":
            return _fail(f"low confidence must fall back safely: {low_confidence}")

        async def authority_route_call(messages: list[dict[str, str]], max_tokens: int) -> str:
            return '{"route":"media","confidence":0.99,"reason":"ok","authority":true,"execute":true}'

        authority_route = await select_route(
            message="add movie Arrival",
            candidate_routes=["project_maintenance", "media"],
            route_to_agent={"project_maintenance": "project_maintainer_agent", "media": "media_agent"},
            model_call=authority_route_call,
        )
        if authority_route.get("authority") is not False:
            return _fail(f"route output cannot authorize execution: {authority_route}")
        if authority_route.get("tool_executed") is not False or authority_route.get("approval_granted") is not False:
            return _fail(f"route output must not execute/approve: {authority_route}")

        print("OK: small router context-budget fallback.")
        return 0
    finally:
        cfg.small_router_safe_input_tokens = original_safe
        cfg.small_router_max_context = original_context
        cfg.small_router_max_output_tokens = original_output
        cfg.small_router_min_confidence = original_min_confidence


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
