"""
API-key role classification for gateway routes.

Unknown or future paths are MASTER_ONLY (fail closed: only master key passes auth).
"""

from __future__ import annotations

import re

from config import cfg


def classify_api_key(provided: str) -> str | None:
    """
    Return 'master', 'input', 'approval', 'admin', or None if missing / unrecognized.
    """
    p = (provided or "").strip()
    if not p:
        return None
    if p == cfg.api_key:
        return "master"
    if cfg.input_api_key and p == cfg.input_api_key:
        return "input"
    if cfg.approval_api_key and p == cfg.approval_api_key:
        return "approval"
    if cfg.admin_api_key and p == cfg.admin_api_key:
        return "admin"
    return None


def route_api_role(method: str, path: str) -> str:
    """
    Classify protected routes for API-key role checks.
    Returns: INPUT_POST | READ_REVIEW | APPROVAL_ACTION | ADMIN_ACTION | MASTER_ONLY

    Unknown or future paths are MASTER_ONLY (fail closed: only master key passes auth).
    """
    if method == "POST" and path == "/ingest":
        return "INPUT_POST"
    if method == "POST" and path == "/plans/propose":
        return "INPUT_POST"
    if method == "POST" and path == "/plans/from-message":
        return "INPUT_POST"
    if method == "POST" and re.match(r"^/plans/[^/]+/(approve|reject|execute)$", path):
        return "APPROVAL_ACTION"
    if method == "GET" and path == "/plans/pending":
        return "READ_REVIEW"
    if method == "GET" and re.match(r"^/plans/pending/[^/]+$", path):
        return "READ_REVIEW"
    if method == "GET" and path == "/notifications/pending-approvals":
        return "READ_REVIEW"
    if method == "GET" and path == "/workspaces":
        return "READ_REVIEW"
    if method == "GET" and re.match(
        r"^/workspaces/(active|completed|rejected)/[^/]+$", path
    ):
        return "READ_REVIEW"
    if method == "GET" and re.match(
        r"^/workspaces/(active|completed|rejected)/[^/]+/files/[^/]+$", path
    ):
        return "READ_REVIEW"
    if method == "GET" and re.match(
        r"^/workspaces/(active|completed|rejected)/[^/]+/compact$", path
    ):
        return "READ_REVIEW"
    if method == "GET" and path in ("/logs", "/events", "/tools"):
        return "READ_REVIEW"
    if method == "GET" and re.match(r"^/tools/[^/]+/[^/]+$", path):
        return "READ_REVIEW"
    if method == "POST" and path in (
        "/tools/propose",
        "/tools/approve",
        "/tools/install",
        "/tools/reject",
    ):
        return "ADMIN_ACTION"
    return "MASTER_ONLY"


def key_allows_route(*, route_role: str, key_kind: str) -> bool:
    if key_kind == "master":
        return True
    if route_role == "INPUT_POST":
        return key_kind == "input" and bool(cfg.input_api_key)
    if route_role == "READ_REVIEW":
        if key_kind == "input" and cfg.input_api_key:
            return True
        if key_kind == "approval" and cfg.approval_api_key:
            return True
        if key_kind == "admin" and cfg.admin_api_key:
            return True
        return False
    if route_role == "APPROVAL_ACTION":
        return key_kind == "master" or (
            key_kind == "approval" and bool(cfg.approval_api_key)
        )
    if route_role == "ADMIN_ACTION":
        return key_kind == "master" or (key_kind == "admin" and bool(cfg.admin_api_key))
    if route_role == "MASTER_ONLY":
        return False
    return False
