#!/usr/bin/env python3
"""Static checks for local dashboard chatbar behavior."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "integrations" / "local_dashboard" / "app.js"
HTML = ROOT / "integrations" / "local_dashboard" / "index.html"


def _fail(msg: str) -> int:
    print(msg)
    return 1


def main() -> int:
    app = APP.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    if '<section class="card chatbar-card"' not in html:
        return _fail("proposal control must be styled as the prominent chatbar card")
    if 'id="proposalForm" class="chatbar-form"' not in html:
        return _fail("proposal controls must live in the chatbar form")
    if '<button id="btnPropose" type="submit">Propose plan</button>' not in html:
        return _fail("chatbar submit button must only propose a plan")
    if '<option value="" selected>Automatic' not in html:
        return _fail("agent selector must default to Automatic")
    if 'option value="media_agent"' not in html:
        return _fail("manual media_agent override must remain available")
    if 'if (selectedAgent)' not in app or 'body.agent = selectedAgent' not in app:
        return _fail("dashboard should omit agent when Automatic is selected")
    if '$("message").addEventListener("keydown"' not in app:
        return _fail("message textarea must handle Enter")
    if 'event.key === "Enter" && !event.shiftKey' not in app:
        return _fail("Enter without Shift must be the proposal shortcut")
    if 'onPropose();' not in app:
        return _fail("Enter shortcut must call propose")

    forbidden = ["onApprove", "onExecute", "/approve", "/execute"]

    if '$("proposalForm").addEventListener("submit"' not in app:
        return _fail("chatbar form submit must be handled explicitly")
    submit_block = app.split('$("proposalForm").addEventListener("submit"', 1)[1].split('$("message").addEventListener("keydown"', 1)[0]
    if "event.preventDefault();" not in submit_block or "onPropose();" not in submit_block:
        return _fail("chatbar form submit must prevent default and propose only")
    submit_hits = [token for token in forbidden if token in submit_block]
    if submit_hits:
        return _fail(f"chatbar form submit must not approve or execute: {submit_hits}")

    keydown_block = app.split('$("message").addEventListener("keydown"', 1)[1].split('$("btnShowActive")', 1)[0]
    hits = [token for token in forbidden if token in keydown_block]
    if hits:
        return _fail(f"Enter key block must not approve or execute: {hits}")

    print("OK: dashboard chatbar Enter proposes only and Automatic is default.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
