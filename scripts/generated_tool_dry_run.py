"""
Review-only generated tool dry-run: read registry + static dispatch metadata, write evidence.

Does not import or execute candidate code, does not call sandbox, does not mutate registry.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
_GENERATED_REGISTRY_PATH = (
    REPO_ROOT / "data" / "registry" / "generated_installed_tools.json"
)
_TOOLS_PATH = REPO_ROOT / "tools.py"
INTERNAL_GENERATED_PREFIX = "internal://generated/"


def _read_generated_registry_raw() -> list[dict[str, Any]]:
    path = _GENERATED_REGISTRY_PATH
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def _find_raw_row(
    rows: list[dict[str, Any]], tool_name: str, version: str
) -> dict[str, Any] | None:
    for row in rows:
        if row.get("name") == tool_name and row.get("version") == version:
            return row
    return None


def _find_any_version(rows: list[dict[str, Any]], tool_name: str) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("name") == tool_name]


def _read_tool_dispatch_keys() -> set[str]:
    try:
        source = _TOOLS_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, UnicodeError, SyntaxError):
        return set()

    keys: set[str] = set()
    for node in ast.walk(tree):
        value: ast.AST | None = None
        target_names: list[str] = []
        if isinstance(node, ast.Assign):
            value = node.value
            for target in node.targets:
                if isinstance(target, ast.Name):
                    target_names.append(target.id)
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            if isinstance(node.target, ast.Name):
                target_names.append(node.target.id)
        if "_TOOL_FUNCS" not in target_names or not isinstance(value, ast.Dict):
            continue
        for key in value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
    return keys


def _write_evidence(out_dir: Path, payload: dict[str, Any], summary_lines: list[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "DRY_RUN_RESULT.json"
    summary_path = out_dir / "DRY_RUN_SUMMARY.md"
    tmp = result_path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(result_path)
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")


def run_dry_run(tool_name: str, version: str, out_dir: Path) -> int:
    notes: list[str] = []
    registry_status: str | None = None
    endpoint: str | None = None
    generated_metadata_detected = False
    callable_dispatch_present = False

    if not tool_name.startswith("generated_"):
        notes.append("Internal error: tool_name must start with generated_.")
        payload = _payload(
            tool_name=tool_name,
            version=version,
            registry_status=registry_status,
            endpoint=endpoint,
            generated_metadata_detected=False,
            callable_dispatch_present=False,
            overall_status="failed",
            notes="; ".join(notes),
        )
        _write_evidence(
            out_dir,
            payload,
            ["# Generated tool dry-run (failed)", "", *("- " + n for n in notes)],
        )
        return 1

    # Import registry after CLI validation; dispatch membership is inspected statically.
    sys.path.insert(0, str(REPO_ROOT))
    import registry  # noqa: PLC0415 — deliberate fresh registry after PS1 subprocess
    dispatch_keys = _read_tool_dispatch_keys()
    raw_rows = _read_generated_registry_raw()
    entry = registry.get(tool_name, version)
    raw_match = _find_raw_row(raw_rows, tool_name, version)
    same_name_rows = _find_any_version(raw_rows, tool_name)

    if entry is not None:
        registry_status = str(entry.status)
        endpoint = str(entry.endpoint)
        generated_metadata_detected = tool_name.startswith(
            "generated_"
        ) and endpoint.startswith(INTERNAL_GENERATED_PREFIX)
        callable_dispatch_present = tool_name in dispatch_keys
        if callable_dispatch_present:
            notes.append("Tool name is present in tools.py _TOOL_FUNCS (unexpected dispatch).")
        if entry.status != "installed":
            notes.append(f"Registry row status is '{entry.status}', expected 'installed'.")
        if not endpoint.startswith(INTERNAL_GENERATED_PREFIX):
            notes.append(
                f"Endpoint must start with {INTERNAL_GENERATED_PREFIX!r}, got {endpoint!r}."
            )
    else:
        registry_status = None
        endpoint = None
        generated_metadata_detected = False
        callable_dispatch_present = tool_name in dispatch_keys
        if callable_dispatch_present:
            notes.append("Tool name is present in tools.py _TOOL_FUNCS (unexpected dispatch).")

        if raw_match is not None:
            st = raw_match.get("status")
            if st != "installed":
                notes.append(
                    "A row exists in generated_installed_tools.json for this name+version "
                    f"but status is {st!r} (not loaded into registry as installed)."
                )
            else:
                notes.append(
                    "Row exists on disk for name+version with status installed but is not "
                    "present in registry (skipped at load, collision, or validation failure)."
                )
        elif same_name_rows:
            versions = sorted({str(r.get("version")) for r in same_name_rows})
            notes.append(
                f"Tool name found on disk with other version(s): {versions!r}; "
                f"requested {version!r}."
            )
        else:
            notes.append(
                "No matching tool in registry and no matching row in "
                "data/registry/generated_installed_tools.json."
            )

    overall_ok = (
        entry is not None
        and entry.status == "installed"
        and endpoint is not None
        and endpoint.startswith(INTERNAL_GENERATED_PREFIX)
        and not callable_dispatch_present
    )

    overall_status = "passed" if overall_ok else "failed"
    if overall_ok:
        notes.insert(0, "Dry-run validation passed: installed metadata only; no dispatch.")

    payload = _payload(
        tool_name=tool_name,
        version=version,
        registry_status=registry_status,
        endpoint=endpoint,
        generated_metadata_detected=generated_metadata_detected,
        callable_dispatch_present=callable_dispatch_present,
        overall_status=overall_status,
        notes="; ".join(notes),
    )

    summary_lines = [
        "# Generated tool dry-run",
        "",
        f"- **Tool:** `{tool_name}` @ `{version}`",
        f"- **Overall:** {overall_status}",
        f"- **Registry status (in-memory):** {registry_status!s}",
        f"- **Endpoint:** {endpoint!s}",
        "",
        "## Safety flags (this path)",
        "",
        "- `candidate_code_executed`: false",
        "- `sandbox_worker_invoked`: false",
        "- `tools_executed`: false",
        "- `real_service_calls`: false",
        "- `execution_allowed`: false",
        f"- `callable_dispatch_present`: {str(callable_dispatch_present).lower()}",
        "- `dry_run_only`: true",
        "",
        "## Notes",
        "",
        *(f"- {n}" for n in notes),
    ]
    _write_evidence(out_dir, payload, summary_lines)
    return 0 if overall_ok else 1


def _payload(
    *,
    tool_name: str,
    version: str,
    registry_status: str | None,
    endpoint: str | None,
    generated_metadata_detected: bool,
    callable_dispatch_present: bool,
    overall_status: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "schema_version": "generated-tool-dry-run.v1",
        "tool_name": tool_name,
        "version": version,
        "registry_status": registry_status,
        "endpoint": endpoint,
        "generated_metadata_detected": generated_metadata_detected,
        "callable_dispatch_present": callable_dispatch_present,
        "candidate_code_executed": False,
        "sandbox_worker_invoked": False,
        "tools_executed": False,
        "real_service_calls": False,
        "execution_allowed": False,
        "dry_run_only": True,
        "overall_status": overall_status,
        "notes": notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generated tool dry-run evidence writer.")
    parser.add_argument("--tool-name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="Output directory (must already exist).",
    )
    args = parser.parse_args()
    out_dir: Path = args.out_dir
    if not out_dir.is_dir():
        print(f"out-dir is not a directory: {out_dir}", file=sys.stderr)
        return 1
    return run_dry_run(args.tool_name, args.version, out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
