"""
routing.py — Routing backends for LOCAL_LLM and CLOUD_LLM targets.

Responsibility:
  - Accept a NormalisedEnvelope and route it to the correct backend.
  - LOCAL_LLM  → Ollama (conversational, temperature non-zero, full response)
  - CLOUD_LLM  → OpenRouter (complex reasoning, external knowledge)

This module does NOT handle LOCAL_TOOLS or DROP — those are handled
in dispatch.py before this module is reached.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from config import cfg
from models import NormalisedEnvelope

logger = logging.getLogger("gateway.routing")

# Conservative patterns — extend via config if needed.
_SENSITIVE_PATTERNS = (
    r"\b\d{3}-\d{2}-\d{4}\b",  # SSN-like
    r"\b(?:\d[ -]*?){13,19}\b",  # credit-card-like digit runs
    r"\bsk-[a-zA-Z0-9]{20,}\b",  # API key style (OpenAI)
    r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b",
    r"\bpassword\s*[:=]\s*\S+",
    r"\bBEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY\b",
)


def _contains_sensitive(text: str) -> bool:
    if not text:
        return False
    for pat in _SENSITIVE_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────


def _envelope_to_user_message(envelope: NormalisedEnvelope) -> str:
    """
    Convert the normalised envelope into a plain user message for an LLM.

    Non-text modalities pass metadata / context; raw bytes are never forwarded.
    """
    if envelope.modality == "text":
        return str(envelope.content)

    if envelope.modality == "event":
        return (
            f"A device event arrived from '{envelope.source_device}':\n"
            f"{envelope.content}\n\n"
            f"Summarise what happened and suggest an action."
        )

    if envelope.modality == "image":
        return (
            f"An image was received from '{envelope.source_device}'. "
            f"Image data is not forwarded to the text LLM. "
            f"Metadata: {envelope.metadata}"
        )

    if envelope.modality == "voice":
        return (
            f"A voice input arrived from '{envelope.source_device}'. "
            f"Audio data is not forwarded to the text LLM. "
            f"Metadata: {envelope.metadata}"
        )

    return f"[unhandled modality: {envelope.modality}]"


# ──────────────────────────────────────────────────────────────────────────────
# LOCAL_LLM — Ollama
# ──────────────────────────────────────────────────────────────────────────────


async def route_local_llm(envelope: NormalisedEnvelope) -> dict[str, Any]:
    """
    Send the envelope to the local Ollama model for conversational response.
    Uses local_llm_model (separate from classifier_model so each can be
    independently configured).
    """
    user_message = _envelope_to_user_message(envelope)

    payload = {
        "model": cfg.local_llm_model,
        "messages": [{"role": "user", "content": user_message}],
        "stream": False,
        "options": {"temperature": 0.7},  # non-zero for conversational output
    }

    logger.info(
        "routing.local_llm | model=%s source=%s",
        cfg.local_llm_model,
        envelope.source_device,
    )

    try:
        async with httpx.AsyncClient(timeout=cfg.ollama_timeout) as client:
            resp = await client.post(f"{cfg.ollama_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.error("routing.local_llm | Ollama call failed: %s", exc)
        return {"error": f"Local LLM unavailable: {exc}"}

    reply: str = data.get("message", {}).get("content", "")
    return {"reply": reply, "model": cfg.local_llm_model}


# ──────────────────────────────────────────────────────────────────────────────
# CLOUD_LLM — OpenRouter
# ──────────────────────────────────────────────────────────────────────────────


async def route_cloud_llm(envelope: NormalisedEnvelope) -> dict[str, Any]:
    """
    Send the envelope to OpenRouter for complex/external reasoning.

    Requires OPENROUTER_API_KEY to be set in config.
    """
    if not cfg.openrouter_api_key:
        logger.error("routing.cloud_llm | OPENROUTER_API_KEY not configured")
        return {"error": "Cloud LLM not configured (missing OPENROUTER_API_KEY)."}

    user_message = _envelope_to_user_message(envelope)

    if not cfg.cloud_allow_sensitive and _contains_sensitive(user_message):
        logger.warning("routing.cloud_llm | blocked: sensitive pattern in user message")
        return {
            "error": "Cloud routing blocked: potential sensitive data in request.",
            "blocked": True,
            "reply": "",
        }

    headers = {
        "Authorization": f"Bearer {cfg.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://homelab-gateway",  # OpenRouter best practice
        "X-Title": "Agentic Gateway",
    }
    payload = {
        "model": cfg.cloud_model,
        "messages": [{"role": "user", "content": user_message}],
    }

    logger.info(
        "routing.cloud_llm | model=%s source=%s",
        cfg.cloud_model,
        envelope.source_device,
    )

    try:
        async with httpx.AsyncClient(timeout=cfg.cloud_timeout) as client:
            resp = await client.post(cfg.openrouter_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.error("routing.cloud_llm | OpenRouter call failed: %s", exc)
        return {"error": f"Cloud LLM unavailable: {exc}"}

    reply: str = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    model_used: str = data.get("model", cfg.cloud_model)
    return {"reply": reply, "model": model_used}
