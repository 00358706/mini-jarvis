#!/usr/bin/env python3
"""
Append a reviewed generated-tool row to data/registry/generated_installed_tools.json.

Does not execute tools, sandbox, candidate code, or gateway. Does not invoke the tool runner entrypoint.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models import ToolDefinition  # noqa: E402

CONFIRM_PHRASE = "INSTALL_REVIEWED_TOOL"
GENERATED_REL = Path("data/registry/generated_installed_tools.json")
VERSION = "v1"


def _read_json(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8-sig")
    return json.loads(raw)


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _generated_registry_path(repo_root: Path) -> Path:
    return repo_root / GENERATED_REL


def deterministic_tool_name(tool_build_id: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", tool_build_id.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        raise ValueError("tool_build_id sanitizes to empty")
    name = f"generated_{sanitized}"
    if len(name) > 120:
        name = name[:120].rstrip("_")
    if not name.startswith("generated_"):
        raise ValueError("invalid generated tool name")
    return name


def _gate_bool(obj: Any, field: str, expected: bool) -> str | None:
    if obj is None:
        return f"missing object for {field}"
    actual = getattr(obj, field, None) if not isinstance(obj, dict) else obj.get(field)
    if actual is not expected:
        return f"{field} must be {expected} (got {actual})"
    return None


def validate_build_index(bi: dict[str, Any]) -> str | None:
    checks = [
        ("authority", False),
        ("review_evidence_only", True),
        ("generated_code_present", True),
        ("candidate_generation_completed", True),
        ("test_harness_completed", True),
        ("static_validation_completed", True),
        ("install_review_created", True),
        ("candidate_code_executed", False),
        ("install_allowed", False),
        ("execution_allowed", False),
        ("registry_modified", False),
        ("tools_executed", False),
        ("sandbox_worker_invoked", False),
    ]
    for field, expected in checks:
        err = _gate_bool(bi, field, expected)
        if err:
            return f"BUILD_INDEX.json: {err}"
    return None


def validate_install_manifest(m: dict[str, Any]) -> str | None:
    if m.get("schema_version") != "tool-install-review-manifest.v1":
        return "INSTALL_MANIFEST.json: bad schema_version"
    checks = [
        ("review_only", True),
        ("authority", False),
        ("install_performed", False),
        ("install_allowed", False),
        ("execution_allowed", False),
        ("registry_modified", False),
        ("tools_executed", False),
        ("sandbox_worker_invoked", False),
        ("candidate_code_executed", False),
    ]
    for field, expected in checks:
        err = _gate_bool(m, field, expected)
        if err:
            return f"INSTALL_MANIFEST.json: {err}"
    return None


def validate_test_results(tr: dict[str, Any]) -> str | None:
    if tr.get("schema_version") != "generated-tool-test-results.v1":
        return "TEST_RESULTS.json: bad schema_version"
    if tr.get("overall_status") != "passed":
        return "TEST_RESULTS.json: overall_status must be passed"
    if tr.get("test_harness_kind") != "static_review":
        return "TEST_RESULTS.json: test_harness_kind must be static_review"
    for field in (
        "candidate_code_executed",
        "sandbox_worker_invoked",
        "registry_modified",
        "tools_executed",
        "install_allowed",
        "execution_allowed",
        "real_service_calls",
    ):
        err = _gate_bool(tr, field, False)
        if err:
            return f"TEST_RESULTS.json: {err}"
    return None


def build_registry_input_schema(tool_schema: dict[str, Any]) -> dict[str, Any]:
    """
    Map candidate TOOL_SCHEMA.json to registry input_schema dict-of-field-specs.
    Falls back to a minimal non-required placeholder.
    """
    proposed = tool_schema.get("proposed_inputs")
    if isinstance(proposed, dict):
        props = proposed.get("properties")
        required_list = proposed.get("required") or []
        if isinstance(props, dict) and props:
            out: dict[str, Any] = {}
            for fname, spec in props.items():
                if not isinstance(fname, str) or not fname.strip():
                    continue
                if not isinstance(spec, dict):
                    continue
                t = spec.get("type", "string")
                if t not in ("string", "integer", "number", "boolean", "array"):
                    t = "string"
                req = bool(spec.get("required")) or fname in required_list
                out[fname] = {"type": t, "required": req}
            if out:
                return out
    return {"_review_note": {"type": "string", "required": False}}


def registry_has_entry_subprocess(repo_root: Path, name: str, version: str) -> bool:
    code = (
        "import registry as r; "
        f"e = r.get({name!r}, {version!r}); "
        "import sys; sys.exit(0 if e is not None else 1)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root),
        check=False,
    )
    return proc.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--tool-build-id", required=True)
    parser.add_argument("--confirm-install-review", required=True)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    tool_build_id = args.tool_build_id.strip()
    if args.confirm_install_review != CONFIRM_PHRASE:
        print("Invalid or missing confirmation phrase.", file=sys.stderr)
        return 1

    if not re.match(r"^[A-Za-z0-9_-]{8,80}$", tool_build_id):
        print("Invalid tool_build_id.", file=sys.stderr)
        return 1

    builds = repo_root / "data" / "tool_builds" / tool_build_id
    if not builds.is_dir():
        print("Tool build workspace not found.", file=sys.stderr)
        return 1
    resolved = builds.resolve()
    tb_root = (repo_root / "data" / "tool_builds").resolve()
    try:
        resolved.relative_to(tb_root)
    except ValueError:
        print("Path traversal rejected.", file=sys.stderr)
        return 1

    record_path = builds / "REGISTRY_INSTALL_RECORD.json"
    summary_path = builds / "REGISTRY_INSTALL_SUMMARY.md"
    if record_path.exists() or summary_path.exists():
        print("Install evidence already exists; refusing.", file=sys.stderr)
        return 1

    required = [
        "BUILD_INDEX.json",
        "INSTALL_MANIFEST.json",
        "INSTALL_REVIEW.md",
        "TEST_RESULTS.json",
        "TEST_SUMMARY.md",
        "source_automation_lab/TOOL_PROPOSAL.md",
        "candidate/CANDIDATE_TOOL.py",
        "candidate/TOOL_SCHEMA.json",
    ]
    for rel in required:
        if not (builds / rel).is_file():
            print(f"Missing required file: {rel}", file=sys.stderr)
            return 1

    bi = _read_json(builds / "BUILD_INDEX.json")
    err = validate_build_index(bi)
    if err:
        print(err, file=sys.stderr)
        return 1

    manifest = _read_json(builds / "INSTALL_MANIFEST.json")
    err = validate_install_manifest(manifest)
    if err:
        print(err, file=sys.stderr)
        return 1

    tr = _read_json(builds / "TEST_RESULTS.json")
    err = validate_test_results(tr)
    if err:
        print(err, file=sys.stderr)
        return 1

    try:
        tool_name = deterministic_tool_name(tool_build_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    gen_path = _generated_registry_path(repo_root)
    backup_registry = gen_path.read_text(encoding="utf-8-sig") if gen_path.is_file() else "[]"
    backup_index = (builds / "BUILD_INDEX.json").read_text(encoding="utf-8-sig")

    tool_schema = _read_json(builds / "candidate" / "TOOL_SCHEMA.json")
    input_schema = build_registry_input_schema(tool_schema)

    try:
        ToolDefinition.model_validate(
            {
                "name": tool_name,
                "endpoint": f"internal://generated/{tool_name}",
                "input_schema": input_schema,
                "permissions": ["review:generated"],
                "version": VERSION,
                "description": (
                    f"Reviewed generated tool metadata for build {tool_build_id}. "
                    "No execution dispatch; not candidate code."
                ),
                "status": "installed",
            }
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ToolDefinition validation failed: {exc}", file=sys.stderr)
        return 1

    new_entry: dict[str, Any] = {
        "name": tool_name,
        "endpoint": f"internal://generated/{tool_name}",
        "input_schema": input_schema,
        "permissions": ["review:generated"],
        "version": VERSION,
        "description": (
            f"Reviewed generated tool metadata for build {tool_build_id}. "
            "No execution dispatch; not candidate code."
        ),
        "status": "installed",
    }

    try:
        data = json.loads(backup_registry)
        if not isinstance(data, list):
            raise ValueError("generated_installed_tools.json must be a JSON array")
        for row in data:
            if not isinstance(row, dict):
                continue
            if row.get("name") == tool_name and row.get("version") == VERSION:
                print("Duplicate generated tool in registry file.", file=sys.stderr)
                return 1

        if registry_has_entry_subprocess(repo_root, tool_name, VERSION):
            print("Tool name/version already present in registry (fresh import).", file=sys.stderr)
            return 1

        data.append(new_entry)
        _atomic_write_json(gen_path, data)

        if not registry_has_entry_subprocess(repo_root, tool_name, VERSION):
            raise RuntimeError("Post-write verification failed: tool not visible to fresh import.")

        created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record = {
            "schema_version": "registry-install-record.v1",
            "tool_build_id": tool_build_id,
            "created_at": created,
            "explicit_confirmation": True,
            "confirmation_phrase_used": "acknowledged",
            "registry_modified": True,
            "registry_entry": new_entry,
            "source_manifest": "INSTALL_MANIFEST.json",
            "install_review": "INSTALL_REVIEW.md",
            "execution_performed": False,
            "sandbox_worker_invoked": False,
            "tools_executed": False,
            "plan_approved": False,
            "execution_allowed_by_install": False,
            "notes": (
                "Persistent generated-registry metadata only. "
                "Install is not execution approval. "
                "Execution requires generated-tool dry-run and normal plan/policy/approval/registry/schema/sandbox path."
            ),
        }
        record_path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        summary_lines = [
            "# Registry install summary (metadata only)",
            "",
            f"- **Tool build:** `{tool_build_id}`",
            f"- **Registry tool:** `{tool_name}` version `{VERSION}`",
            "- **Persistent store:** `data/registry/generated_installed_tools.json`",
            "- **Confirmation:** explicit admin phrase acknowledged (not echoed here).",
            "- **Execution:** not performed. **Sandbox:** not invoked. **Tools executed:** false.",
            "- **Install is not execution approval.** Dry-run / wiring remains later.",
            "",
            "See `REGISTRY_INSTALL_RECORD.json` for machine-readable evidence.",
        ]
        summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

        bi["registry_install_review_completed"] = True
        bi["registry_install_record_path"] = "REGISTRY_INSTALL_RECORD.json"
        bi["registry_install_summary_path"] = "REGISTRY_INSTALL_SUMMARY.md"
        bi["registry_modified"] = True
        bi["install_performed"] = True
        bi["execution_allowed"] = False
        bi["tools_executed"] = False
        bi["sandbox_worker_invoked"] = False
        bi["authority"] = False
        bi["review_evidence_only"] = True

        (builds / "BUILD_INDEX.json").write_text(
            json.dumps(bi, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        try:
            gen_path.write_text(backup_registry, encoding="utf-8")
        except OSError:
            pass
        try:
            (builds / "BUILD_INDEX.json").write_text(backup_index, encoding="utf-8")
        except OSError:
            pass
        for p in (record_path, summary_path):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        raise

    print(f"OK: appended {tool_name}:{VERSION} to generated registry and wrote install evidence.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"registry_append_reviewed_generated_tool failed: {exc}", file=sys.stderr)
        raise SystemExit(4)
