"""
config.py — Centralised configuration.

All tuneable values live here. Override via environment variables.
No value is hard-coded elsewhere in the codebase.

Usage:
    from config import cfg
    cfg.ollama_url
"""

from __future__ import annotations

import os


class _Config:
    # ── Network ───────────────────────────────────────────────────────────────
    # Bind to your Tailscale 100.x.x.x address in production.
    # Use 0.0.0.0 only during local smoke-testing.
    host: str = os.getenv("GATEWAY_HOST", "0.0.0.0")
    port: int = int(os.getenv("GATEWAY_PORT", "8000"))

    # ── Authentication ────────────────────────────────────────────────────────
    # Set a strong random secret here or via environment.
    # All requests must include:  X-API-Key: <value>
    api_key: str = os.getenv("GATEWAY_API_KEY", "change-me-before-use")

    # ── Local LLM (Ollama) ────────────────────────────────────────────────────
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    # Model used for the intent classifier only.
    # Must fit comfortably in 8 GB VRAM — llama3 8B or mistral 7B are good fits.
    classifier_model: str = os.getenv("CLASSIFIER_MODEL", "llama3")
    # Model used for LOCAL_LLM routing target.
    local_llm_model: str = os.getenv("LOCAL_LLM_MODEL", "llama3")
    # Hard cap: classifier must respond in this many tokens or fewer.
    classifier_max_tokens: int = int(os.getenv("CLASSIFIER_MAX_TOKENS", "5"))

    # ── Cloud LLM (OpenRouter) ────────────────────────────────────────────────
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_url: str = os.getenv(
        "OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions"
    )
    # "auto" lets OpenRouter pick the best model; pin to a specific model if
    # you want cost/latency predictability.
    cloud_model: str = os.getenv("CLOUD_MODEL", "openai/gpt-4o")

    # ── Media Automation ──────────────────────────────────────────────────────
    radarr_url: str = os.getenv("RADARR_URL", "http://localhost:7878")
    radarr_api_key: str = os.getenv("RADARR_API_KEY", "")
    sonarr_url: str = os.getenv("SONARR_URL", "http://localhost:8989")
    sonarr_api_key: str = os.getenv("SONARR_API_KEY", "")
    sabnzbd_url: str = os.getenv("SABNZBD_URL", "http://localhost:8090")
    sabnzbd_api_key: str = os.getenv("SABNZBD_API_KEY", "")

    # ── HTTP client timeouts (seconds) ────────────────────────────────────────
    ollama_timeout: float = float(os.getenv("OLLAMA_TIMEOUT", "30.0"))
    cloud_timeout: float = float(os.getenv("CLOUD_TIMEOUT", "60.0"))
    tool_timeout: float = float(os.getenv("TOOL_TIMEOUT", "15.0"))

    # ── Sandbox / policy ──────────────────────────────────────────────────────
    # Dynamic exec()-based sandbox (model-proposed code). Off by default.
    enable_sandbox_python_exec: bool = os.getenv(
        "ENABLE_SANDBOX_PYTHON_EXEC", ""
    ).lower() in (
        "1",
        "true",
        "yes",
    )
    # When True, cloud routing runs even if sensitive patterns match (not recommended).
    cloud_allow_sensitive: bool = os.getenv("CLOUD_ALLOW_SENSITIVE", "").lower() in (
        "1",
        "true",
        "yes",
    )


cfg = _Config()
