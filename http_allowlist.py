"""
http_allowlist.py — Tool-layer HTTP destination policy.

Before HTTP calls from built-in tools, verify the full request URL is under the
approved base URL from configuration (e.g. RADARR_URL). Tool code should perform
HTTP I/O only through :mod:`tools_http` so static guards can detect stray clients.
This does not replace OS-level network isolation; it limits accidental or buggy
calls to wrong hosts.
"""

from __future__ import annotations

from urllib.parse import urlsplit


def validate_http_destination(request_url: str, approved_base_url: str) -> str | None:
    """
    Return None if ``request_url`` is allowed for a tool tied to ``approved_base_url``.

    Same-origin (scheme, host, port) must match. If the base URL includes a
    non-root path, the request path must be that path or a subpath.

    On failure, return a generic error string suitable for ToolResult (no raw URL echo).
    """
    try:
        req = urlsplit(request_url.strip())
        base = urlsplit(approved_base_url.strip())
    except Exception:
        return "HTTP request blocked: invalid URL configuration."

    if not req.scheme or not req.netloc:
        return "HTTP request blocked: invalid request URL."

    if not base.scheme or not base.netloc:
        return "HTTP request blocked: invalid configured service URL."

    def _origin(
        scheme: str, hostname: str | None, port: int | None
    ) -> tuple[str, str, int] | None:
        if not hostname:
            return None
        sch = (scheme or "").lower()
        host = hostname.lower()
        prt = port
        if prt is None:
            prt = 443 if sch == "https" else 80
        return (sch, host, prt)

    o_req = _origin(req.scheme, req.hostname, req.port)
    o_base = _origin(base.scheme, base.hostname, base.port)
    if o_req is None or o_base is None:
        return "HTTP request blocked: invalid host in URL."

    if o_req != o_base:
        return "HTTP request blocked: destination does not match the configured service base URL."

    base_path = base.path or "/"
    if not base_path.startswith("/"):
        base_path = "/" + base_path
    base_path_norm = base_path.rstrip("/") or "/"

    req_path = req.path or "/"
    if not req_path.startswith("/"):
        req_path = "/" + req_path

    if base_path_norm == "/":
        return None
    if req_path == base_path_norm or req_path.startswith(base_path_norm + "/"):
        return None
    return "HTTP request blocked: path is not under the configured service base URL."
