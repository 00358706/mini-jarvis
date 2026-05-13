"""
sandbox.py — Isolated tool execution environment.

Execution contract (Phase 4):
  gateway (dispatch/tools) → sandbox.run() → subprocess (sandbox_worker.py)
  → run_tool_by_name() → tools_http (httpx) to registered backends

Isolation (current tier — extend with OS sandbox / seccomp as needed):
  - Tool code runs in a child Python process with its own interpreter.
  - Working directory is a fresh temporary directory per invocation (not the package tree).
  - Child environment is an explicit allowlist (no full environ.copy()); PATH is always set.
  - Subprocess wall-clock timeout with explicit kill on expiry so the worker cannot hang past the cap.
  - Dynamic `exec()` of model-supplied code is **disabled by default**; see
    config.ENABLE_SANDBOX_PYTHON_EXEC.

The model NEVER imports or calls this directly.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import cfg
import tools_http


# Deferred import to avoid circular imports at module load.
def _tool_result_model():
    from models import ToolResult

    return ToolResult


# ──────────────────────────────────────────────────────────────────────────────
# Result schema
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class SandboxResult:
    success: bool
    output: Any = None
    error: str | None = None
    execution_time_ms: float = 0.0
    exit_code: int = 0


# ──────────────────────────────────────────────────────────────────────────────
# Restricted Python execution
# ──────────────────────────────────────────────────────────────────────────────

# These builtins are available inside sandboxed code.
# Everything else is explicitly denied.
_ALLOWED_BUILTINS = {
    "abs",
    "all",
    "any",
    "bin",
    "bool",
    "chr",
    "dict",
    "dir",
    "divmod",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "hasattr",
    "hash",
    "hex",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "oct",
    "ord",
    "pow",
    "print",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "slice",
    "sorted",
    "str",
    "sum",
    "tuple",
    "type",
    "zip",
}

_SANDBOX_WRAPPER_TEMPLATE = """\
import sys, json, builtins

_allowed_names = ALLOWED_PLACEHOLDER
_safe = {n: getattr(builtins, n) for n in _allowed_names if hasattr(builtins, n)}
_safe['__builtins__'] = _safe
_safe['__name__'] = '__sandbox__'

_safe['args'] = ARGS_PLACEHOLDER
_safe['result'] = None

try:
    exec(compile(CODE_PLACEHOLDER, '<sandbox>', 'exec'), _safe)
    output = _safe.get('result')
    print(json.dumps({"success": True, "output": output}))
except Exception as e:
    print(json.dumps({"success": False, "error": str(e)}))
"""


def execute_python(
    code: str, args: dict[str, Any], timeout_seconds: float = 10.0
) -> SandboxResult:
    """
    Execute arbitrary Python code in a restricted subprocess.

    **Disabled by default** (gateway policy: no dynamic code execution on the
    hot path). Set ENABLE_SANDBOX_PYTHON_EXEC=true only in controlled dev
    environments.
    """
    if not getattr(cfg, "enable_sandbox_python_exec", False):
        return SandboxResult(
            success=False,
            error="Dynamic Python execution is disabled (set ENABLE_SANDBOX_PYTHON_EXEC=1 to enable).",
        )

    wrapper = (
        _SANDBOX_WRAPPER_TEMPLATE.replace(
            "ALLOWED_PLACEHOLDER", repr(list(_ALLOWED_BUILTINS))
        )
        .replace("ARGS_PLACEHOLDER", repr(args))
        .replace("CODE_PLACEHOLDER", repr(textwrap.dedent(code)))
    )

    start = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", wrapper],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env={},  # empty environment — no PATH, no HOME, nothing inherited
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(
            success=False,
            error=f"Execution timed out after {timeout_seconds}s",
            execution_time_ms=(time.monotonic() - start) * 1000,
        )

    elapsed_ms = (time.monotonic() - start) * 1000

    if proc.returncode != 0:
        return SandboxResult(
            success=False,
            error=proc.stderr.strip() or f"Non-zero exit code: {proc.returncode}",
            execution_time_ms=elapsed_ms,
            exit_code=proc.returncode,
        )

    try:
        parsed = json.loads(proc.stdout.strip())
        return SandboxResult(
            success=parsed.get("success", False),
            output=parsed.get("output"),
            error=parsed.get("error"),
            execution_time_ms=elapsed_ms,
            exit_code=proc.returncode,
        )
    except json.JSONDecodeError:
        return SandboxResult(
            success=False,
            error=f"Sandbox produced non-JSON output: {proc.stdout[:200]}",
            execution_time_ms=elapsed_ms,
        )


def validate_tool_proposal(code: str, test_cases: list[dict]) -> SandboxResult:
    """
    Run a proposed tool implementation against test cases before approval.

    Each test case is: {"args": {...}, "expect": <any>}
    All must pass for the proposal to be considered valid.

    This is called by the approval pipeline — not by the model directly.
    """
    passed = 0
    failures = []

    for i, case in enumerate(test_cases):
        result = execute_python(code, case.get("args", {}))
        if not result.success:
            failures.append(f"Case {i}: execution error — {result.error}")
            continue
        expected = case.get("expect")
        if expected is not None and result.output != expected:
            failures.append(f"Case {i}: expected {expected!r}, got {result.output!r}")
        else:
            passed += 1

    if failures:
        return SandboxResult(
            success=False,
            error="\n".join(failures),
            output={"passed": passed, "total": len(test_cases)},
        )

    return SandboxResult(
        success=True,
        output={"passed": passed, "total": len(test_cases)},
    )


def execute_http_tool(
    endpoint: str, payload: dict, timeout_seconds: float = 15.0
) -> SandboxResult:
    """
    Call a registered HTTP tool endpoint.
    Used for tools like Radarr/Sonarr that live behind their own services.
    The model never calls this — only dispatch.py does, after registry check.
    """
    start = time.monotonic()
    try:
        output, http_status = tools_http.sync_post_json_raise(
            endpoint, payload, timeout_seconds=timeout_seconds
        )
        return SandboxResult(
            success=True,
            output=output,
            execution_time_ms=(time.monotonic() - start) * 1000,
            exit_code=http_status,
        )
    except Exception as exc:
        return SandboxResult(
            success=False,
            error=str(exc),
            execution_time_ms=(time.monotonic() - start) * 1000,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Primary async API — subprocess-isolated tool execution
# ──────────────────────────────────────────────────────────────────────────────


# Keys passed in stdin (`_child_env`) and applied in the worker before importing
# tools — keeps subprocess `env=` to PATH (+ Windows spawn vars) only.
SANDBOX_TOOL_ENV_INJECT_KEYS: frozenset[str] = frozenset(
    {
        "RADARR_URL",
        "RADARR_API_KEY",
        "SONARR_URL",
        "SONARR_API_KEY",
        "SABNZBD_URL",
        "SABNZBD_API_KEY",
        "TOOL_TIMEOUT",
    }
)

# Absolute ceiling for subprocess wall time (seconds).
_SANDBOX_SUBPROCESS_HARD_MAX = 300.0
# After kill(), drain pipes briefly so the process can exit cleanly.
_POST_KILL_DRAIN_SEC = 5.0


def _sandbox_subprocess_env() -> dict[str, str]:
    """
    Subprocess `env` allowlist: **PATH only** on POSIX.

    On Windows, SYSTEMROOT/WINDIR are added so `python.exe` can load system DLLs;
    they are not general user secrets. No `os.environ.copy()` — gateway secrets
    (GATEWAY_API_KEY, OPENROUTER_*, etc.) are never placed in this dict.

    Media/tool configuration is passed separately via stdin `_child_env` and
    applied inside `sandbox_worker.py` before `tools` is imported.
    """
    env: dict[str, str] = {"PATH": os.environ.get("PATH", "")}
    if os.name == "nt":
        for key in ("SYSTEMROOT", "WINDIR"):
            val = os.environ.get(key)
            if val:
                env[key] = val
    return env


def _child_env_payload_for_worker() -> dict[str, str]:
    """Subset of parent env for tools (injected in worker process, not in Popen env)."""
    out: dict[str, str] = {}
    for key in SANDBOX_TOOL_ENV_INJECT_KEYS:
        if key in os.environ and os.environ[key] != "":
            out[key] = os.environ[key]
    return out


def _annotate_tool_execution(
    result: Any,
    *,
    elapsed_sec: float,
    executed_in_sandbox_worker: bool,
    sandbox_timeout: bool,
) -> Any:
    """Attach wall-clock duration and sandbox metadata to a ToolResult."""
    elapsed_ms = round(float(elapsed_sec) * 1000.0, 3)
    se = getattr(result, "sandbox_elapsed", None)
    if se is None:
        se = elapsed_sec
    return result.model_copy(
        update={
            "execution_duration_ms": elapsed_ms,
            "executed_in_sandbox_worker": executed_in_sandbox_worker,
            "sandbox_timeout": sandbox_timeout,
            "sandbox_elapsed": se,
        }
    )


def _run_tool_subprocess(tool_name: str, args: dict[str, Any], timeout: float):
    """Synchronous subprocess boundary; called via asyncio.to_thread."""
    ToolResult = _tool_result_model()
    worker = Path(__file__).resolve().parent / "sandbox_worker.py"
    payload = json.dumps(
        {
            "name": tool_name,
            "args": args,
            "_child_env": _child_env_payload_for_worker(),
        }
    )
    start = time.monotonic()
    cap = max(0.1, min(float(timeout), _SANDBOX_SUBPROCESS_HARD_MAX))
    env = _sandbox_subprocess_env()

    with tempfile.TemporaryDirectory(prefix="gateway_sandbox_") as tmpdir:
        proc = subprocess.Popen(
            [sys.executable, str(worker)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=tmpdir,
            env=env,
        )
        try:
            stdout, stderr = proc.communicate(input=payload, timeout=cap)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                stdout, stderr = proc.communicate(timeout=_POST_KILL_DRAIN_SEC)
            except subprocess.TimeoutExpired:
                stdout, stderr = (stdout or ""), (stderr or "")
            elapsed = time.monotonic() - start
            return _annotate_tool_execution(
                ToolResult(
                    tool_name=tool_name,
                    success=False,
                    error=f"Sandbox subprocess timed out after {cap}s",
                    sandbox_elapsed=elapsed,
                ),
                elapsed_sec=elapsed,
                executed_in_sandbox_worker=False,
                sandbox_timeout=True,
            )

        elapsed = time.monotonic() - start
        if proc.returncode != 0:
            err = (stderr or stdout or "").strip() or f"exit {proc.returncode}"
            return _annotate_tool_execution(
                ToolResult(
                    tool_name=tool_name,
                    success=False,
                    error=f"Sandbox worker failed: {err[:500]}",
                    sandbox_elapsed=elapsed,
                ),
                elapsed_sec=elapsed,
                executed_in_sandbox_worker=False,
                sandbox_timeout=False,
            )

        try:
            data = json.loads((stdout or "").strip())
            parsed = ToolResult.model_validate(data)
            return _annotate_tool_execution(
                parsed,
                elapsed_sec=elapsed,
                executed_in_sandbox_worker=True,
                sandbox_timeout=False,
            )
        except Exception as exc:
            return _annotate_tool_execution(
                ToolResult(
                    tool_name=tool_name,
                    success=False,
                    error=f"Invalid sandbox output: {exc!s} | {(stdout or '')[:200]!r}",
                    sandbox_elapsed=elapsed,
                ),
                elapsed_sec=elapsed,
                executed_in_sandbox_worker=False,
                sandbox_timeout=False,
            )


async def run(
    *,
    tool_name: str,
    args: dict[str, Any],
    timeout_seconds: float | None = None,
):
    """
    Run a registered tool inside an isolated subprocess.

    Args:
        tool_name: Installed registry tool name (e.g. radarr_search).
        args: Validated arguments only.
        timeout_seconds: Override default tool timeout from config.
    """
    timeout = float(
        timeout_seconds if timeout_seconds is not None else cfg.tool_timeout
    )
    return await asyncio.to_thread(_run_tool_subprocess, tool_name, args, timeout)
