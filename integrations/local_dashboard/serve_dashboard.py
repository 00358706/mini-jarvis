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
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen


_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from automation_lab import generate as generate_automation_lab  # noqa: E402
from automation_lab_review import load_index, render_summary  # noqa: E402


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
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
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


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def _is_allowlisted(method: str, path: str) -> bool:
    m = (method or "").upper()
    p = (path or "").split("?", 1)[0]
    for allowed_method, rx in _ALLOWLIST:
        if m == allowed_method and rx.match(p):
            return True
    return False


def _safe_request_id(request_id: str) -> str:
    if not _REQUEST_ID_RE.fullmatch(request_id or ""):
        raise ValueError("Invalid automation lab request_id")
    return request_id


def _automation_run_dir(request_id: str) -> Path:
    rid = _safe_request_id(request_id)
    run_dir = (_REPO_ROOT / "data" / "automation_lab" / rid).resolve()
    root = (_REPO_ROOT / "data" / "automation_lab").resolve()
    if not str(run_dir).startswith(str(root)):
        raise ValueError("Invalid automation lab run path")
    return run_dir


def _read_index_for_request(request_id: str) -> tuple[dict, Path, Path]:
    run_dir = _automation_run_dir(request_id)
    index, index_path = load_index(run_dir)
    return index, index_path, run_dir


def _artifact_names(index: dict) -> set[str]:
    names: set[str] = set()
    for entry in index.get("artifacts", []):
        if isinstance(entry, dict) and isinstance(entry.get("filename"), str):
            names.add(entry["filename"])
    return names


def _safe_artifact_name(raw: str, index: dict) -> str:
    filename = unquote(raw or "")
    if not _ARTIFACT_NAME_RE.fullmatch(filename):
        raise ValueError("Invalid automation lab artifact filename")
    if "/" in filename or "\\" in filename or filename in {".", ".."}:
        raise ValueError("Invalid automation lab artifact filename")
    if filename not in _artifact_names(index):
        raise PermissionError("Artifact is not listed in INDEX.json")
    return filename


class Handler(BaseHTTPRequestHandler):
    server_version = "mini-jarvis-local-dashboard/0.1"

    def _send(self, status: int, body: bytes, *, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/automation-lab/"):
            self._automation_lab("GET")
            return
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
        if self.path.startswith("/api/automation-lab/"):
            self._automation_lab("POST")
            return
        if self.path.startswith("/api/"):
            self._proxy("POST")
            return
        self._send(404, b"not found", content_type="text/plain; charset=utf-8")

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 65536:
            raise ValueError("Request body is too large")
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _automation_lab(self, method: str) -> None:
        path = self.path.split("?", 1)[0]
        parts = path.strip("/").split("/")

        try:
            if method == "POST" and path == "/api/automation-lab/generate":
                payload = self._read_json_body()
                message = str(payload.get("message") or "").strip()
                if not message:
                    raise ValueError("message is required")
                use_fixture = bool(payload.get("use_fixture"))
                fixture_path = None
                if use_fixture:
                    fixture_path = str(
                        _REPO_ROOT / "fixtures" / "automation_lab" / "capabilities.json"
                    )
                result = generate_automation_lab(message, fixture_path=fixture_path)
                index, index_path, _run_dir = _read_index_for_request(result["request_id"])
                summary = render_summary(index, index_path)
                response = {
                    "result": result,
                    "index": index,
                    "review_summary": summary,
                    "authority": False,
                }
                self._send(200, _json_bytes(response), content_type="application/json; charset=utf-8")
                return

            if method == "GET" and len(parts) == 4 and parts[:2] == ["api", "automation-lab"]:
                request_id = parts[2]
                action = parts[3]
                index, index_path, _run_dir = _read_index_for_request(request_id)
                if action == "index":
                    self._send(
                        200,
                        _json_bytes(index),
                        content_type="application/json; charset=utf-8",
                    )
                    return
                if action == "summary":
                    summary = render_summary(index, index_path)
                    self._send(200, summary.encode("utf-8"), content_type="text/plain; charset=utf-8")
                    return

            if (
                method == "GET"
                and len(parts) == 5
                and parts[:2] == ["api", "automation-lab"]
                and parts[3] == "artifacts"
            ):
                request_id = parts[2]
                index, _index_path, run_dir = _read_index_for_request(request_id)
                filename = _safe_artifact_name(parts[4], index)
                artifact_path = (run_dir / filename).resolve()
                if artifact_path.parent != run_dir or not artifact_path.is_file():
                    raise PermissionError("Artifact path is not readable for this run")
                entry = next(
                    item
                    for item in index["artifacts"]
                    if isinstance(item, dict) and item.get("filename") == filename
                )
                response = {
                    "filename": filename,
                    "artifact": entry,
                    "content": artifact_path.read_text(encoding="utf-8", errors="replace"),
                    "authority": False,
                }
                self._send(200, _json_bytes(response), content_type="application/json; charset=utf-8")
                return

            self._send(
                404,
                _json_bytes({"error": "automation_lab_route_not_found"}),
                content_type="application/json; charset=utf-8",
            )
        except PermissionError as exc:
            self._send(
                403,
                _json_bytes({"error": "automation_lab_forbidden", "message": str(exc)}),
                content_type="application/json; charset=utf-8",
            )
        except FileNotFoundError as exc:
            self._send(
                404,
                _json_bytes({"error": "automation_lab_not_found", "message": str(exc)}),
                content_type="application/json; charset=utf-8",
            )
        except ValueError as exc:
            self._send(
                400,
                _json_bytes({"error": "automation_lab_bad_request", "message": str(exc)}),
                content_type="application/json; charset=utf-8",
            )

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

