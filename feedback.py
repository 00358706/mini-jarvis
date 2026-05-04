"""
feedback.py — Optional learning / adapter hook (Phase 4 stub).

The hot path uses classification.classify (Ollama, temperature=0). Adapter
classification stays disabled unless you implement adapter_classify() to
return a (RoutingTarget, confidence) tuple from local telemetry.
"""

from __future__ import annotations

from typing import Any

from models import RoutingTarget


def adapter_classify(text: str) -> tuple[RoutingTarget, float] | None:
    """Return None to use the primary Ollama classifier."""
    _ = text
    return None


async def record(**kwargs: Any) -> None:
    """Persist routing feedback for future training (no-op stub)."""
    _ = kwargs
