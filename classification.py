"""
classification.py — LLM-based intent classifier.

Responsibility:
  - Accept a NormalisedEnvelope.
  - Call the local Ollama model (temperature=0).
  - Strip and validate the response to one of the four allowed routing tokens.
  - Never return freeform output or raise past the caller.

Design constraints:
  - Deterministic: temperature=0 always.
  - Constrained: num_predict caps output at classifier_max_tokens.
  - Fail-safe: any unexpected token falls back to DROP.
  - Replaceable: swap out _call_ollama() for any other classifier backend.
"""

from __future__ import annotations

import logging

import httpx

from config import cfg
from models import (
    ALLOWED_ROUTING_TOKENS,
    ClassifierResult,
    NormalisedEnvelope,
    RoutingTarget,
)

logger = logging.getLogger("gateway.classifier")

# ──────────────────────────────────────────────────────────────────────────────
# Classifier prompt
# ──────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a strict intent router. Your only job is to classify the user's input \
into exactly one of these four routing targets:

  LOCAL_TOOLS  — deterministic actions: media automation (Radarr/Sonarr/SABnzbd),
                 file system operations, service control, local API calls.
  LOCAL_LLM    — simple reasoning, Q&A, or summarisation that can be handled
                 by a small on-device language model.
  CLOUD_LLM    — complex reasoning, coding, external knowledge, large context.
  DROP         — empty, malformed, unsafe, or nonsensical input.

Rules:
- Output ONLY one of the four tokens above. No punctuation, no explanation.
- If you are unsure, output DROP.
- If the input is a device/sensor event, prefer LOCAL_TOOLS or DROP.
"""


def _build_user_message(envelope: NormalisedEnvelope) -> str:
    """
    Convert the envelope into a compact classifier input.
    We only expose what the classifier needs; no raw bytes.
    """
    if envelope.text_content:
        content_repr = envelope.text_content[:500]
    elif envelope.modality == "text":
        content_repr = str(envelope.content)[:500]  # cap to avoid prompt stuffing
    elif envelope.modality == "event":
        content_repr = str(envelope.content)[:300]
    elif envelope.modality == "voice":
        content_repr = "[voice audio — transcription pending]"
    elif envelope.modality == "image":
        # Don't send raw base64 to the classifier; describe the fact of an image.
        content_repr = "[image input]"
    else:
        content_repr = "[unknown content]"

    return (
        f"modality: {envelope.modality}\n"
        f"source: {envelope.source_device}\n"
        f"content: {content_repr}\n\n"
        f"Route this input."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Ollama call
# ──────────────────────────────────────────────────────────────────────────────


async def _call_ollama(user_message: str) -> str:
    """
    Send a chat completion request to Ollama.
    Returns the raw text from the model (may be dirty — caller cleans it).
    Raises httpx.HTTPError on network/HTTP failures.
    """
    payload = {
        "model": cfg.classifier_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "options": {
            "temperature": 0,
            "num_predict": cfg.classifier_max_tokens,
        },
    }

    async with httpx.AsyncClient(timeout=cfg.ollama_timeout) as client:
        response = await client.post(
            f"{cfg.ollama_url}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    # Ollama's /api/chat response shape:
    #   {"message": {"role": "assistant", "content": "<text>"}, ...}
    return data["message"]["content"]


# ──────────────────────────────────────────────────────────────────────────────
# Public interface
# ──────────────────────────────────────────────────────────────────────────────


async def classify(envelope: NormalisedEnvelope) -> ClassifierResult:
    """
    Classify an envelope and return a ClassifierResult with a validated target.

    Never raises — any error produces a DROP result so the pipeline can
    continue with a safe default.
    """
    user_message = _build_user_message(envelope)

    try:
        raw = await _call_ollama(user_message)
    except Exception as exc:
        logger.warning("Classifier call failed (%s); defaulting to DROP", exc)
        return ClassifierResult(target="DROP", raw_output=f"[error] {exc}")

    token = _extract_token(raw)

    logger.info(
        "classify | raw=%r → target=%s | modality=%s source=%s",
        raw.strip(),
        token,
        envelope.modality,
        envelope.source_device,
    )

    return ClassifierResult(target=token, raw_output=raw)


def _extract_token(raw: str) -> RoutingTarget:
    """
    Strip whitespace/punctuation from the model output and validate it
    against the allowed token set.

    Falls back to DROP on any mismatch — never returns an arbitrary string.
    """
    candidate = raw.strip().rstrip(".,!:;").upper()

    if candidate in ALLOWED_ROUTING_TOKENS:
        return candidate  # type: ignore[return-value]

    # Handle common model verbosity, e.g. "The answer is LOCAL_TOOLS."
    for token in ALLOWED_ROUTING_TOKENS:
        if token in candidate:
            return token  # type: ignore[return-value]

    logger.warning("Unrecognised classifier output %r — falling back to DROP", raw)
    return "DROP"
