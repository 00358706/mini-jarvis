"""
multimodal.py — Preprocess non-text modalities into routing text.

Phase 4 stub: deterministic, local-safe transforms only. No external APIs.
Replace STT / vision backends here when available; the gateway contract is
unchanged: return {\"text\": str, \"metadata\": dict}.
"""

from __future__ import annotations

import json
from typing import Any


async def preprocess(modality: str, content: Any) -> dict[str, Any]:
    """
    Convert multimodal content to text for classification and routing.

    - voice/image: placeholder description (raw media never forwarded to LLMs).
    - event: JSON-serialised summary for keyword / classifier input.
    """
    if modality == "event" and isinstance(content, dict):
        action = str(content.get("action", "")).strip()
        parts = [f"device_event action={action!r}"]
        for k, v in sorted(content.items()):
            if k != "action":
                parts.append(f"{k}={v!r}")
        text = " | ".join(parts)
        return {"text": text, "metadata": {"event_keys": list(content.keys())}}

    if modality == "voice":
        # Stub: length hint only — integrate Whisper/local STT later.
        raw = content if isinstance(content, str) else ""
        return {
            "text": f"[voice_stub len={len(raw)}]",
            "metadata": {"preprocess": "voice_stub"},
        }

    if modality == "image":
        raw = content if isinstance(content, str) else ""
        return {
            "text": f"[image_stub len={len(raw)}]",
            "metadata": {"preprocess": "image_stub"},
        }

    # Fallback
    try:
        text = json.dumps(content)[:2000]
    except (TypeError, ValueError):
        text = str(content)[:2000]
    return {"text": text, "metadata": {"preprocess": "fallback"}}
