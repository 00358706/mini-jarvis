"""
agent_loader.py — Read human-readable agent folder metadata only.

Loads text and optional structured YAML into an AgentConfig. Does not exec
YAML as code or import Python modules from agent dirs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plans import validate_storage_id

logger = logging.getLogger("gateway.agent_loader")

# ──────────────────────────────────────────────────────────────────────────────
# Root
# ──────────────────────────────────────────────────────────────────────────────

_AGENTS_ROOT = Path(__file__).resolve().parent / "agents"

# ──────────────────────────────────────────────────────────────────────────────
# File helpers
# ──────────────────────────────────────────────────────────────────────────────


def _read_if_exists(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _try_yaml_dict(raw: str) -> tuple[dict[str, Any] | None, bool]:
    """
    If PyYAML is available, ``safe_load`` and return ``(dict|None, True)``.
    On ImportError return ``(None, False)``.
    """
    if not raw.strip():
        return None, False
    try:
        import yaml  # type: ignore[import-untyped]

        loaded = yaml.safe_load(raw)
    except ImportError:
        return None, False
    except Exception as exc:
        logger.warning("agent_loader | YAML parse failed: %s", exc)
        return None, True

    if isinstance(loaded, dict):
        return loaded, True
    return None, True


def _fallback_agent_regex(raw: str) -> dict[str, Any]:
    """Tiny regex extractors for repo agent.yaml when PyYAML is not installed."""

    def _find(key: str) -> str | None:
        pattern = rf"(?m)^{re.escape(key)}:\s*(.+)\s*$"
        m = re.search(pattern, raw)
        if m:
            return m.group(1).strip().strip('"')
        return None

    out: dict[str, Any] = {}

    bid = _find("id")
    if bid:
        out["id"] = bid

    dn = _find("display_name")
    if dn:
        out["display_name"] = dn

    ver = _find("version")
    if ver:
        out["version"] = ver.strip('"')

    pup = re.search(r"(?ms)^purpose:\s*>\s*\n((?:^  .*$\n)+)", raw)
    if pup:
        body = pup.group(1)
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        out["purpose"] = " ".join(lines)

    pmap = re.search(r"(?ms)^paths:\s*\n((?:^  [\w]+:\s*.+$\n?)+)", raw)
    if pmap:
        paths: dict[str, str] = {}
        for ln in pmap.group(1).splitlines():
            mm = re.match(r"^\s+([\w]+):\s*(.+)\s*$", ln)
            if mm:
                paths[mm.group(1)] = mm.group(2).strip().strip('"')
        out["paths"] = paths

    tblk = re.search(r"(?ms)^tags:\s*\n((?:^  -\s+.+$\n?)+)", raw)
    if tblk:
        tags = re.findall(r"(?m)^\s*-\s*(.+)$", tblk.group(1))
        out["tags"] = [t.strip().strip('"') for t in tags if t.strip()]

    return out


def _planned_tool_names_from_text(tools_yaml: str) -> list[str]:
    pattern = r"(?m)^\s*-\s+name:\s*(\S+)\s*$"
    return re.findall(pattern, tools_yaml)


def _normalize_purpose(purpose_v: Any) -> str | None:
    if purpose_v is None:
        return None
    if isinstance(purpose_v, str):
        return purpose_v.strip()
    return str(purpose_v).strip()


# ──────────────────────────────────────────────────────────────────────────────
# AgentConfig
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class AgentConfig:
    """Declarative filesystem context for one agent persona (not a service)."""

    agent_id: str
    base_path: Path
    display_name: str | None = None
    version: str | None = None
    purpose: str | None = None
    tags: list[str] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)
    prompt_md: str = ""
    tools_yaml: str = ""
    policy_yaml: str = ""
    examples_md: str = ""
    parsed_with_yaml_library: bool = False
    agent_yaml_data: dict[str, Any] = field(default_factory=dict)
    tools_yaml_data: dict[str, Any] = field(default_factory=dict)
    policy_yaml_data: dict[str, Any] = field(default_factory=dict)
    planned_tool_names_fallback: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def list_agents() -> list[str]:
    """Sorted agent ids: subdirectories of agents/ containing agent.yaml."""
    if not _AGENTS_ROOT.is_dir():
        return []
    out: list[str] = []
    for p in _AGENTS_ROOT.iterdir():
        if p.is_dir() and (p / "agent.yaml").is_file():
            out.append(p.name)
    return sorted(out)


def load_agent(agent_id: str) -> AgentConfig:
    """
    Load ``agents/<agent_id>/`` metadata files.

    When PyYAML is installed, ``agent.yaml``, ``tools.yaml``, and ``policy.yaml``
    are parsed into ``*_yaml_data``. Otherwise structured fields rely on regex
    fallbacks plus ``planned_tool_names_fallback`` from ``tools.yaml`` text.
    """
    agent_id = validate_storage_id(agent_id, field_name="agent")
    base = _AGENTS_ROOT / agent_id
    if not base.is_dir():
        raise FileNotFoundError(f"Unknown agent {agent_id!r} ({base})")

    raw_agent = _read_if_exists(base / "agent.yaml")
    tools_text = _read_if_exists(base / "tools.yaml")
    policy_text = _read_if_exists(base / "policy.yaml")

    parsed_lib_any = False
    ay_parsed, ay_lib = _try_yaml_dict(raw_agent)
    if ay_lib:
        parsed_lib_any = True
    if ay_parsed is None:
        ay_parsed = _fallback_agent_regex(raw_agent)

    tt_dict, tt_lib = _try_yaml_dict(tools_text)
    if tt_lib:
        parsed_lib_any = True
    if tt_dict is None:
        tt_dict = {}

    pol_dict, pol_lib = _try_yaml_dict(policy_text)
    if pol_lib:
        parsed_lib_any = True
    if pol_dict is None:
        pol_dict = {}

    aid = str(ay_parsed.get("id") or agent_id)

    paths_blk = ay_parsed.get("paths")
    if isinstance(paths_blk, dict):
        paths_clean = {str(k): str(v) for k, v in paths_blk.items()}
    else:
        paths_clean = {}

    tags_blk = ay_parsed.get("tags")
    if isinstance(tags_blk, list):
        tags_list = [str(t) for t in tags_blk]
    else:
        tags_list = []

    display = ay_parsed.get("display_name")
    purpose_v = ay_parsed.get("purpose")
    version_v = ay_parsed.get("version")

    prompt_rel = paths_clean.get("prompt", "prompt.md")
    examples_rel = paths_clean.get("examples", "examples.md")

    agent_data = dict(ay_parsed) if ay_parsed else {}

    return AgentConfig(
        agent_id=aid,
        base_path=base,
        display_name=str(display) if display is not None else None,
        version=str(version_v).strip('"') if version_v is not None else None,
        purpose=_normalize_purpose(purpose_v),
        tags=tags_list,
        paths=paths_clean,
        prompt_md=_read_if_exists(base / prompt_rel),
        tools_yaml=tools_text,
        policy_yaml=policy_text,
        examples_md=_read_if_exists(base / examples_rel),
        parsed_with_yaml_library=parsed_lib_any,
        agent_yaml_data=agent_data,
        tools_yaml_data=dict(tt_dict),
        policy_yaml_data=dict(pol_dict),
        planned_tool_names_fallback=_planned_tool_names_from_text(tools_text),
    )


def get_agent_tool_policy(agent_id: str) -> dict[str, Any] | None:
    """
    Return agent tool policy from tools.yaml, or None if unavailable.

    Supports allowed_tools:
      allowed_tools:
        - name: radarr_search
        - radarr_add
    and enforcement:
      enforcement:
        mode: strict
    """
    try:
        cfg = load_agent(agent_id)
    except (FileNotFoundError, ValueError):
        return None

    data = cfg.tools_yaml_data if isinstance(cfg.tools_yaml_data, dict) else {}
    out: set[str] = set()
    raw_allowed = data.get("allowed_tools")
    if isinstance(raw_allowed, list):
        for item in raw_allowed:
            if isinstance(item, str):
                name = item.strip()
                if name:
                    out.add(name)
            elif isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    out.add(name.strip())

    mode = "advisory"
    enforcement = data.get("enforcement")
    if isinstance(enforcement, dict):
        m = enforcement.get("mode")
        if isinstance(m, str) and m.strip():
            mode = m.strip().lower()

    return {"mode": mode, "allowed_tools": out}
