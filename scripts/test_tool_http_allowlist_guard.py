#!/usr/bin/env python3
"""
Static guard: tool execution surface must not import or call raw HTTP clients.

Approved: tools_http.py (central httpx). Not a network sandbox — reduces accidental
bypass of http_allowlist-style checks by scattering clients across tools.py.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Tool execution surface only (see docs). Not gateway routing, adapters, or scripts.
_SCAN_REL_PATHS = ("tools.py", "sandbox.py", "sandbox_worker.py")


def _iter_scan_files() -> list[Path]:
    out: list[Path] = []
    for rel in _SCAN_REL_PATHS:
        p = _REPO_ROOT / rel
        if p.is_file():
            out.append(p)
    tools_pkg = _REPO_ROOT / "tools"
    if tools_pkg.is_dir():
        for py in sorted(tools_pkg.rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            if "data" in py.relative_to(_REPO_ROOT).parts:
                continue
            out.append(py)
    return out


# (label, regex) — applied to each non-comment line; see tools_http.py for allowed httpx.
_LINE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("import requests", re.compile(r"^\s*import\s+requests\b")),
    ("from requests import", re.compile(r"^\s*from\s+requests\s+import\b")),
    ("import httpx", re.compile(r"^\s*import\s+httpx\b")),
    ("from httpx import", re.compile(r"^\s*from\s+httpx\s+import\b")),
    ("import aiohttp", re.compile(r"^\s*import\s+aiohttp\b")),
    ("from aiohttp import", re.compile(r"^\s*from\s+aiohttp\s+import\b")),
    ("import urllib.request", re.compile(r"^\s*import\s+urllib\.request\b")),
    ("from urllib import request", re.compile(r"^\s*from\s+urllib\s+import\s+request\b")),
    (
        "from urllib.request import",
        re.compile(r"^\s*from\s+urllib\.request\s+import\b"),
    ),
    (
        "urllib.request HTTP symbols",
        re.compile(
            r"\burllib\.request\.(urlopen|Request|urlretrieve|build_opener|install_opener|OpenerDirector)\b"
        ),
    ),
    ("requests HTTP verb helper", re.compile(r"\brequests\.(get|post|put|delete|patch|request)\b")),
    ("httpx HTTP verb helper", re.compile(r"\bhttpx\.(get|post|put|delete|patch|request)\b")),
    ("httpx client types", re.compile(r"\bhttpx\.(AsyncClient|Client)\b")),
    ("aiohttp.ClientSession", re.compile(r"\baiohttp\.ClientSession\b")),
]


def _is_comment_only_line(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def _verify_pattern_samples() -> str | None:
    """Sanity-check regexes: urllib.request imports blocked; urllib.parse allowed."""
    from_req = next(p for lab, p in _LINE_PATTERNS if lab == "from urllib.request import")
    from_pkg = next(p for lab, p in _LINE_PATTERNS if lab == "from urllib import request")

    bad = "from urllib.request import urlopen"
    if not from_req.search(bad):
        return f"self-check: expected pattern to match {bad!r}"

    ok_parse = "from urllib.parse import urlsplit"
    if from_req.search(ok_parse):
        return f"self-check: must not match {ok_parse!r}"

    ok_import_parse = "import urllib.parse"
    if from_req.search(ok_import_parse):
        return f"self-check: must not match {ok_import_parse!r}"

    if not from_pkg.search("from urllib import request"):
        return "self-check: from urllib import request should match"
    if from_pkg.search(ok_parse):
        return f"self-check: from urllib import request must not match {ok_parse!r}"

    qual = next(p for lab, p in _LINE_PATTERNS if lab == "urllib.request HTTP symbols")
    if not qual.search("x = urllib.request.urlopen(u)"):
        return "self-check: qualified urllib.request.urlopen should match"
    if qual.search("urllib.parse.urlsplit(u)"):
        return "self-check: must not match urllib.parse.urlsplit"

    return None


def main() -> int:
    err = _verify_pattern_samples()
    if err:
        print(err)
        return 1

    helper = _REPO_ROOT / "tools_http.py"
    if not helper.is_file():
        print(f"{helper}: missing tools_http.py (required approved helper)")
        return 1
    helper_text = helper.read_text(encoding="utf-8")
    if not re.search(r"^\s*import\s+httpx\b", helper_text, re.MULTILINE):
        print(f"{helper}: expected ``import httpx`` in approved helper")
        return 1

    violations: list[str] = []
    for path in _iter_scan_files():
        rel = path.relative_to(_REPO_ROOT)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            violations.append(f"{rel}:1: read error: {exc}")
            continue
        for lineno, line in enumerate(lines, start=1):
            if _is_comment_only_line(line):
                continue
            for label, pat in _LINE_PATTERNS:
                if pat.search(line):
                    violations.append(f"{rel}:{lineno}: {label} | {line.strip()}")

    if violations:
        print("Banned HTTP client usage on tool execution surface:\n")
        for v in violations:
            print(v)
        return 1

    print("OK: tool HTTP allowlist guard (scanned: {})".format(", ".join(str(p.relative_to(_REPO_ROOT)) for p in _iter_scan_files())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
