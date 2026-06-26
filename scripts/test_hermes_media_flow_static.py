#!/usr/bin/env python3
"""Static safety checks for the Hermes Mini-Jarvis media-flow wrapper.

These checks intentionally avoid live network calls. The wrapper is allowed to
call Mini-Jarvis gateway endpoints only; approval and execution must remain
separate and explicitly confirmed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "integrations" / "hermes" / "mini_jarvis_media_flow.py"
README = REPO_ROOT / "integrations" / "hermes" / "README.md"


def _read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"missing expected file: {path.relative_to(REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def _endpoint_literals(tree: ast.AST) -> set[str]:
    endpoint_pattern = re.compile(r"/(?:plans|workspaces)/[^\s'\"]*")
    endpoints: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for match in endpoint_pattern.finditer(node.value):
                endpoints.add(match.group(0))
        elif isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                elif isinstance(value, ast.FormattedValue):
                    parts.append("{...}")
            joined = "".join(parts)
            for match in endpoint_pattern.finditer(joined):
                endpoints.add(match.group(0))
    endpoints.discard("/plans/")
    endpoints.discard("/workspaces/")
    return endpoints


def test_script_exists_and_parses() -> None:
    source = _read(SCRIPT)
    ast.parse(source)
    assert "def main(" in source
    assert "MINI_JARVIS_BASE_URL" in source
    assert "MINI_JARVIS_API_KEY" in source


def test_script_uses_only_mini_jarvis_gateway_endpoints() -> None:
    source = _read(SCRIPT)
    tree = ast.parse(source)
    endpoints = _endpoint_literals(tree)
    allowed_prefixes = (
        "/plans/from-message",
        "/plans/pending",
        "/plans/{...}/approve",
        "/plans/{...}/execute",
        "/workspaces/{...}/{...}/compact",
        "/workspaces/{...}/{...}",
    )
    assert endpoints, "expected explicit Mini-Jarvis endpoint literals"
    unexpected = sorted(
        endpoint for endpoint in endpoints if not endpoint.startswith(allowed_prefixes)
    )
    assert not unexpected, f"unexpected endpoint literal(s): {unexpected}"

    forbidden_direct_service_markers = (
        "RADARR_",
        "SONARR_",
        "SABNZBD_",
        "PROWLARR_",
        ":7878",
        ":8989",
        ":8090",
        "/api/v3",
        "/sabnzbd/api",
    )
    offenders = [marker for marker in forbidden_direct_service_markers if marker in source]
    assert not offenders, f"direct media-service marker(s) found: {offenders}"


def test_approval_and_execution_are_separate_and_confirmed() -> None:
    source = _read(SCRIPT)
    assert "approve" in source
    assert "execute" in source
    assert "--confirm" in source
    assert "Refusing to approve without --confirm" in source
    assert "Refusing to execute without --confirm" in source
    assert "Approved. No execution was started." in source
    assert "Do not combine approve and execute" in source
    assert "approve_execute" not in source
    assert "approve-and-execute" not in source


def test_readme_documents_authority_boundary() -> None:
    text = _read(README)
    required = (
        "Hermes calls Mini-Jarvis endpoints only",
        "Natural-language chat is not authorization",
        "Approval and execution are separate",
        "--confirm",
        "No combined approve+execute command",
    )
    missing = [phrase for phrase in required if phrase not in text]
    assert not missing, f"README missing required phrase(s): {missing}"


def main() -> int:
    tests = (
        test_script_exists_and_parses,
        test_script_uses_only_mini_jarvis_gateway_endpoints,
        test_approval_and_execution_are_separate_and_confirmed,
        test_readme_documents_authority_boundary,
    )
    for test in tests:
        test()
    print("OK: Hermes media-flow static safety checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
