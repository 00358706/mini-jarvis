"""
serve_dashboard.py

Local static server + transparent proxy for the local_dashboard.

Why this exists:
- Browsers enforce CORS. The gateway intentionally does not advertise a browser CORS policy.
- This server keeps the UI client-only while allowing the browser to talk to the gateway
  through same-origin requests.

Security properties:
- No new gateway authority. The gateway remains the enforcement point.
- This server does not store API keys. The UI sends X-API-Key per request.
- This server does not call tools or sandbox. It only forwards HTTP.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


_HERE = Path(__file__).resolve().parent


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _content_type(path: Path) -> str:
    if path.name.endswith(".html"):
        return "text/html; charset=utf-8"
    if path.name.endswith(".js"):
        return "text/javascript; charset=utf-8"
    if path.name.endswith(".css"):
        return "text/css; charset=utf-8"
    if path.name.endswith(".json"):
        return "application/json; charset=utf-8"
    if path.name.endswith(".md"):
        return "text/markdown; charset=utf-8"
    return "application/octet-stream"


def _safe_target_base_url(raw: str | None) -> str:
    if not raw:
        raise ValueError("Missing X-Target-Base-Url")
    u = raw.strip()
    parsed = urlparse(u)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Invalid X-Target-Base-Url scheme")
    if not parsed.netloc:
        raise ValueError("Invalid X-Target-Base-Url host")
    return u.rstrip("/")


_PLAN_ID_RE = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
_ALLOWLIST: list[tuple[str, re.Pattern[str]]] = [
    ("GET", re.compile(r"^/health$")),
    ("POST", re.compile(r"^/plans/from-message$")),
    ("GET", re.compile(r"^/plans/pending$")),
    ("GET", re.compile(rf"^/workspaces/active/{_PLAN_ID_RE}/compact$")),
    ("GET", re.compile(rf"^/workspaces/completed/{_PLAN_ID_RE}/compact$")),
    ("GET", re.compile(rf"^/workspaces/completed/{_PLAN_ID_RE}/files/RESULT\.md$")),
    ("POST", re.compile(rf"^/plans/{_PLAN_ID_RE}/approve$")),
    ("POST", re.compile(rf"^/plans/{_PLAN_ID_RE}/reject$")),
    ("POST", re.compile(rf"^/plans/{_PLAN_ID_RE}/execute$")),
]


def _is_allowlisted(method: str, path: str) -> bool:
    m = (method or "").upper()
    p = (path or "").split("?", 1)[0]
    for allowed_method, rx in _ALLOWLIST:
        if m == allowed_method and rx.match(p):
            return True
    return False


class Handler(BaseHTTPRequestHandler):
    server_version = "mini-jarvis-local-dashboard/0.1"

    def _send(self, status: int, body: bytes, *, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            self._proxy("GET")
            return

        path = self.path.split("?", 1)[0]
        if path == "/" or not path:
            path = "/index.html"

        file_path = (_HERE / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(_HERE.resolve())):
            self._send(404, b"not found", content_type="text/plain; charset=utf-8")
            return
        if not file_path.exists() or not file_path.is_file():
            self._send(404, b"not found", content_type="text/plain; charset=utf-8")
            return

        body = _read_bytes(file_path)
        self._send(200, body, content_type=_content_type(file_path))

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            self._proxy("POST")
            return
        self._send(404, b"not found", content_type="text/plain; charset=utf-8")

    def _proxy(self, method: str) -> None:
        try:
            base_url = _safe_target_base_url(self.headers.get("X-Target-Base-Url"))
        except ValueError as exc:
            payload = json.dumps({"error": str(exc)}).encode("utf-8")
            self._send(400, payload, content_type="application/json; charset=utf-8")
            return

        upstream_path = self.path[len("/api") :]
        upstream_path_only = upstream_path.split("?", 1)[0]
        if not _is_allowlisted(method, upstream_path_only):
            payload = json.dumps(
                {
                    "error": "proxy_forbidden",
                    "message": "This local dashboard proxy only allows a small, explicit allowlist of gateway endpoints.",
                    "method": (method or "").upper(),
                    "path": upstream_path_only,
                }
            ).encode("utf-8")
            self._send(403, payload, content_type="application/json; charset=utf-8")
            return

        upstream_url = urljoin(base_url + "/", upstream_path.lstrip("/"))

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else None

        headers = {
            "Content-Type": self.headers.get("Content-Type") or "application/json",
        }
        api_key = self.headers.get("X-API-Key")
        if api_key:
            headers["X-API-Key"] = api_key

        req = Request(upstream_url, method=method, data=body, headers=headers)
        try:
            with urlopen(req, timeout=30) as resp:  # nosec - local gateway expected
                raw = resp.read()
                ct = resp.headers.get("Content-Type") or "application/json; charset=utf-8"
                self._send(resp.status, raw, content_type=ct)
        except HTTPError as exc:
            raw = exc.read() if exc.fp else b""
            ct = exc.headers.get("Content-Type") if exc.headers else None
            self._send(
                exc.code,
                raw or b"{}",
                content_type=ct or "application/json; charset=utf-8",
            )
        except URLError as exc:
            payload = json.dumps({"error": f"upstream_error: {exc}"}).encode("utf-8")
            self._send(502, payload, content_type="application/json; charset=utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--listen", default="127.0.0.1", help="Listen interface (default: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=5173, help="Listen port (default: 5173)")
    args = ap.parse_args(argv)

    httpd = ThreadingHTTPServer((args.listen, args.port), Handler)
    print(f"Serving local_dashboard on http://{args.listen}:{args.port}/")
    print("Proxying API requests from /api/* to gateway base URL from X-Target-Base-Url.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))

