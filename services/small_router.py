"""
Small advisory agent router for short prompts.

This module can ask the tiny qwen3-router model to choose an agent, but its
output is never authority. Oversized prompts or llama.cpp context-limit errors
become a safe manual-agent fallback and never trigger execution.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from config import cfg

logger = logging.getLogger("gateway.small_router")

_CONTEXT_ERROR_MARKERS: tuple[str, ...] = (
    "context",
    "n_ctx",
    "too many tokens",
    "maximum context",
    "exceed context",
    "exceeds context",
    "requested tokens",
)

_SYSTEM_PROMPT = """\
You are a tiny advisory router for Mini-Jarvis.
Choose exactly one route id from the supplied list, or manual_agent_required.
Return only compact JSON with keys: route, confidence, reason.
You cannot approve, execute, install tools, or set policy. Your output is advisory only.
"""

ModelCall = Callable[[list[dict[str, str]], int], Awaitable[str]]


def estimate_input_tokens(text: str) -> int:
    """
    Conservative tokenizer-free estimate for llama.cpp context budgeting.

    Use both whitespace and byte-length estimates and take the larger value.
    This intentionally overestimates common English text to avoid sending prompts
    that approach qwen3-router's small actual context.
    """
    if not text:
        return 0
    byte_estimate = (len(text.encode("utf-8")) + 2) // 3
    word_estimate = len(text.split())
    return max(byte_estimate, word_estimate)


def _manual_fallback(reason: str, *, estimated_input_tokens: int, model_called: bool) -> dict[str, Any]:
    return {
        "selected_route": "manual_agent_required",
        "selected_agent": "manual_agent_required",
        "reason": reason,
        "authority": False,
        "model_called": model_called,
        "tool_executed": False,
        "approval_granted": False,
        "estimated_input_tokens": estimated_input_tokens,
    }


def _context_budget_exceeded(estimated_input_tokens: int) -> bool:
    if estimated_input_tokens > cfg.small_router_safe_input_tokens:
        return True
    return (
        estimated_input_tokens + cfg.small_router_max_output_tokens
        > cfg.small_router_max_context
    )


def _looks_like_context_error(exc: BaseException) -> bool:
    parts = [str(exc)]
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            parts.append(response.text)
        except Exception:
            pass
    text = " ".join(parts).lower()
    return "context" in text or any(marker in text for marker in _CONTEXT_ERROR_MARKERS)


def _build_messages(message: str, candidate_routes: list[str]) -> list[dict[str, str]]:
    routes = ", ".join(candidate_routes) if candidate_routes else "manual_agent_required"
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"candidate_routes: {routes}\n"
                f"message:\n{message}\n\n"
                "Select one candidate route id, or manual_agent_required."
            ),
        },
    ]


async def _call_llama_cpp(messages: list[dict[str, str]], max_tokens: int) -> str:
    import httpx

    payload = {
        "model": cfg.small_router_model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {}
    if cfg.small_router_api_key:
        headers["Authorization"] = f"Bearer {cfg.small_router_api_key}"
    async with httpx.AsyncClient(timeout=cfg.small_router_timeout) as client:
        response = await client.post(
            f"{cfg.small_router_base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
    return str(data.get("choices", [{}])[0].get("message", {}).get("content", ""))


def _extract_agent(raw: str, candidate_agents: list[str]) -> str:
    cleaned = (raw or "").strip().strip('`"\'.,:;')
    if cleaned in candidate_agents:
        return cleaned
    for agent in candidate_agents:
        if agent in cleaned:
            return agent
    try:
        payload = json.loads(raw)
        selected = payload.get("selected_agent") if isinstance(payload, dict) else None
        if isinstance(selected, str) and selected in candidate_agents:
            return selected
    except Exception:
        pass
    return "manual_agent_required"


def _extract_route_json(raw: str) -> tuple[str, float, str] | None:
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    route = payload.get("route") or payload.get("selected_route") or payload.get("selected_agent")
    confidence = payload.get("confidence", 0)
    reason = payload.get("reason", "")
    if not isinstance(route, str):
        return None
    try:
        confidence_f = float(confidence)
    except (TypeError, ValueError):
        return None
    if not isinstance(reason, str):
        reason = ""
    return route.strip(), confidence_f, reason.strip()[:300]


async def select_route(
    *,
    message: str,
    candidate_routes: list[str],
    route_to_agent: dict[str, str],
    manual_agent: str | None = None,
    model_call: ModelCall | None = None,
) -> dict[str, Any]:
    """
    Select a supported route advisory-only.

    The router sees only route ids and the user message (no tool schemas or
    secrets). It cannot authorize execution: every return has ``authority``
    false and no approval/execution flags. Unsafe or unusable outputs fall back
    to ``manual_agent_required``.
    """
    message = message or ""
    routes = [r for r in candidate_routes if isinstance(r, str) and r.strip()]

    if manual_agent:
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

    messages = _build_messages(message, routes)
    prompt_text = "\n".join(part["content"] for part in messages)
    estimated = estimate_input_tokens(prompt_text)
    if _context_budget_exceeded(estimated):
        return _manual_fallback(
            "router_context_budget_exceeded",
            estimated_input_tokens=estimated,
            model_called=False,
        )

    call = model_call or _call_llama_cpp
    try:
        raw = await call(messages, cfg.small_router_max_output_tokens)
    except Exception as exc:
        if _looks_like_context_error(exc):
            return _manual_fallback(
                "router_context_budget_exceeded",
                estimated_input_tokens=estimated,
                model_called=True,
            )
        logger.warning("small_router | model unavailable converted to fallback: %s", exc)
        return _manual_fallback("router_unavailable", estimated_input_tokens=estimated, model_called=True)

    parsed = _extract_route_json(raw)
    if parsed is None:
        fallback = _manual_fallback("router_invalid_json", estimated_input_tokens=estimated, model_called=True)
        fallback["raw_output"] = raw
        return fallback

    route, confidence, router_reason = parsed
    if confidence < cfg.small_router_min_confidence:
        fallback = _manual_fallback("router_low_confidence", estimated_input_tokens=estimated, model_called=True)
        fallback.update({"selected_route": route, "confidence": confidence, "router_reason": router_reason})
        return fallback
    if route == "manual_agent_required":
        fallback = _manual_fallback("manual_agent_required", estimated_input_tokens=estimated, model_called=True)
        fallback.update({"confidence": confidence, "router_reason": router_reason})
        return fallback
    if route not in routes:
        fallback = _manual_fallback("router_unknown_route", estimated_input_tokens=estimated, model_called=True)
        fallback.update({"selected_route": route, "confidence": confidence, "router_reason": router_reason})
        return fallback
    selected_agent = route_to_agent.get(route)
    if not selected_agent:
        fallback = _manual_fallback("router_route_has_no_supported_agent", estimated_input_tokens=estimated, model_called=True)
        fallback.update({"selected_route": route, "confidence": confidence, "router_reason": router_reason})
        return fallback

    return {
        "selected_route": route,
        "selected_agent": selected_agent,
        "reason": "router_selected",
        "router_reason": router_reason,
        "confidence": confidence,
        "authority": False,
        "model_called": True,
        "tool_executed": False,
        "approval_granted": False,
        "estimated_input_tokens": estimated,
    }


async def select_agent(
    *,
    message: str,
    candidate_agents: list[str],
    manual_agent: str | None = None,
    model_call: ModelCall | None = None,
) -> dict[str, Any]:
    """
    Select an agent advisory-only.

    If ``manual_agent`` is supplied, the tiny router is bypassed. Otherwise, the
    prompt is budget-checked before the model call. Oversized input or context
    errors return ``manual_agent_required`` with ``authority: False``.
    """
    message = message or ""
    candidates = [a for a in candidate_agents if isinstance(a, str) and a.strip()]

    if manual_agent:
        return {
            "selected_agent": manual_agent,
            "reason": "manual_agent_selected",
            "authority": False,
            "model_called": False,
            "tiny_router_bypassed": True,
            "tool_executed": False,
            "approval_granted": False,
            "estimated_input_tokens": 0,
        }

    messages = _build_messages(message, candidates)
    prompt_text = "\n".join(part["content"] for part in messages)
    estimated = estimate_input_tokens(prompt_text)
    if _context_budget_exceeded(estimated):
        logger.info(
            "small_router | context budget exceeded estimated=%s safe=%s max=%s output=%s",
            estimated,
            cfg.small_router_safe_input_tokens,
            cfg.small_router_max_context,
            cfg.small_router_max_output_tokens,
        )
        return _manual_fallback(
            "router_context_budget_exceeded",
            estimated_input_tokens=estimated,
            model_called=False,
        )

    call = model_call or _call_llama_cpp
    try:
        raw = await call(messages, cfg.small_router_max_output_tokens)
    except Exception as exc:
        if _looks_like_context_error(exc):
            logger.warning("small_router | llama.cpp context error converted to fallback: %s", exc)
            return _manual_fallback(
                "router_context_budget_exceeded",
                estimated_input_tokens=estimated,
                model_called=True,
            )
        logger.warning("small_router | model unavailable converted to fallback: %s", exc)
        return _manual_fallback(
            "router_unavailable",
            estimated_input_tokens=estimated,
            model_called=True,
        )

    selected = _extract_agent(raw, candidates)
    return {
        "selected_agent": selected,
        "reason": "router_selected" if selected != "manual_agent_required" else "manual_agent_required",
        "authority": False,
        "model_called": True,
        "tool_executed": False,
        "approval_granted": False,
        "estimated_input_tokens": estimated,
        "raw_output": raw,
    }
