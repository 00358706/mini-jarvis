# CURRENT_STATE — mini-jarvis (checkpoint)

mini-jarvis is a **local-first Agentic Gateway OS** that exposes `/ingest` and a **plan/policy/approval** workflow: agents may propose plans, humans approve them, and only then the gateway executes **installed** tools via a sandboxed worker with an auditable filesystem trail.

## Current architecture summary
- **Gateway remains the authority**: validation, registry, policy, approvals, and execution live in gateway code.
- **Agents are folders**: `agents/<id>/` is configuration/context only; agents do not execute tools.
- **Execution boundary**: tools run via `sandbox.run()` → `sandbox_worker.py` (subprocess + timeout + restricted env).
- **Workspaces are readable state**: `data/workspaces/{active|completed|rejected}/<plan_id>/` mirrors plan lifecycle; files are not authority.
- **HTTP authentication**: `GATEWAY_API_KEY` is the **master** key (all protected routes). Optional **`GATEWAY_INPUT_API_KEY`**, **`GATEWAY_APPROVAL_API_KEY`**, and **`GATEWAY_ADMIN_API_KEY`** restrict clients by route class: input (ingest, `POST /plans/propose`, `POST /plans/from-message`, read-only GETs including **`GET /notifications/pending-approvals`**), plan approve/reject/execute, and registry tool lifecycle POSTs respectively. When a role key is set, lower-tier keys cannot call higher-tier routes (`401` unknown/missing key, `403` insufficient role). See `README.md` and `.env.example`.

## Implemented APIs
- **Ingest**
  - `POST /ingest` — normalises and classifies input. When the classifier routes to `LOCAL_TOOLS`, the gateway **does not** execute installed tools or invoke the sandbox on this path by default; the response indicates that a **pending plan** and explicit **approval** are required, and the audit log records `gate: ingest_tool_execution_disabled`. Use `/plans/from-message` (where supported), `POST /plans/propose`, then `POST /plans/{plan_id}/approve` and `POST /plans/{plan_id}/execute` for execution. Natural language in chat is not authorization.
- **Plan API**
  - `POST /plans/propose` — persists pending plans with a server-computed **`reviewed_plan_sha256`** over the canonical plan core (client-supplied digest fields are stripped and recomputed). Legacy on-disk plans without hashes are intentionally unsupported for approve/execute until re-proposed.
  - `GET /plans/pending`
  - `GET /plans/pending/{plan_id}` — includes **`reviewed_plan_sha256`** when present.
  - **`GET /notifications/pending-approvals`** — read-only listing of recent **informational** pending-approval notifications (append-only **`data/notifications/pending_approvals.jsonl`**; latest **200** by default). Notifications do **not** approve or execute (`can_approve` / `can_execute` are always false in records); operators still use explicit approve/execute POSTs with approval-capable keys and valid hashes.
  - `POST /plans/{plan_id}/approve` — requires **`reviewed_plan_sha256`** on the pending document and verifies it matches a fresh digest; writes **`approved_plan_sha256`**; does not execute.
  - `POST /plans/{plan_id}/reject`
  - `POST /plans/{plan_id}/execute` — requires **`approved_plan_sha256`**, verifies current plan core matches that digest **before** policy or tool/sandbox calls; returns **`409`** with `already_executed` if the plan is already under `executed/`; approval never implies execution.
- **Workspace review API (read-only)**
  - `GET /workspaces?state=active|completed|rejected`
  - `GET /workspaces/{state}/{task_id}`
  - `GET /workspaces/{state}/{task_id}/files/{filename}`
- **Frontend convenience**
  - `POST /plans/from-message` (deterministic, proposal-only)

## Automated authority-boundary tests (local, no real services)
- `python scripts/test_policy_approval_unit_tests.py` — `policy.evaluate_plan`, `/plans/propose` (including strict agent allowlist), approve/reject/execute separation, hash preconditions before execution, duplicate-execute `409`, `/plans/from-message` proposal-only, `/ingest` `LOCAL_TOOLS` gating (including that natural-language “approval” text is not authorization). Uses temp plan/workspace dirs and stubs `run_installed_tool` / sandbox paths.
- `python scripts/test_approval_state_locking.py` — plan content hash binding and fail-closed execute paths.
- `python scripts/test_ingest_local_tools_gated.py` — ingest `LOCAL_TOOLS` does not call `tools.execute`.
- `python scripts/test_approval_role_keys.py` — optional role-separated `X-API-Key` behavior (`GATEWAY_INPUT_API_KEY`, `GATEWAY_APPROVAL_API_KEY`, `GATEWAY_ADMIN_API_KEY`) vs master `GATEWAY_API_KEY`.
- `python scripts/test_pending_approval_notifications.py` — append-only pending-approval JSONL, read-only notifications GET, role gates, no registry/tool/sandbox side effects on propose/from-message.

## Installed tools (current)
- **Maintainer (read-only / proposal-only)**: `inspect_file`, `list_project_files`, `search_repo`, `propose_patch`
- **Media tools**: Radarr/Sonarr/SABnzbd tools (installed tools remain registry-defined; agent allowlists restrict what can be proposed)

## Current agents
- `media_agent`
- `project_maintainer_agent`

## Current Open WebUI wrappers
- `integrations/openwebui/mini_jarvis_plan_propose.py` (proposal-only)
- `integrations/openwebui/mini_jarvis_plan_review.py` (review + explicit approve/reject/execute with `--confirm`)

## Current local review dashboard (client-only)
- `integrations/local_dashboard/` — static HTML/JS demo UI that uses gateway endpoints only for plan review (no gateway changes) and narrow local automation lab review routes for generating proposal artifacts, listing recent runs from `INDEX.json`, reading `INDEX.json`, and reading indexed artifacts only.
- **Read-only data storage report:** `scripts/report_workspace_storage.ps1` prints top-level `data/` usage, workspace state sizes, largest directories (default 20), test-looking folder name hints, and age-based archive **hints** (stdout or `-Json`); it does **not** read file contents, write files, delete, compact, or change timestamps. See `docs/AUTHORITY_AND_EVIDENCE_MODEL.md`. **Not a change to gateway or workspace runtime behavior.**
- **Read-only archive-candidate report:** `scripts/report_workspace_archive_candidates.ps1` lists mergeable candidate folders (age and/or test-name signals) across workspaces, automation lab, tool builds, and dry-run dirs, optional `-IncludeActive` review-only rows, sorted oldest-first then by size; stdout or `-Json` only — **no** writes, deletes, moves, or compaction. See `docs/AUTHORITY_AND_EVIDENCE_MODEL.md`.

## Current automation lab (proposal-only)
- `scripts/automation_lab_propose.ps1` uses `automation_lab.py` to write indexed review artifacts under `data/automation_lab/<request_id>/`. Capability matching is **registry-informed** via read-only `registry.all_tools()` metadata through `automation_lab_registry_read.py` (no lifecycle mutations, no sandbox, no execution). `CAPABILITY_MATCHES.json` uses schema `automation-lab-capability-matches.v3` and records `registry_lookup`, `registry_matches`, deterministic/fixture layers, advisory `score` / `score_breakdown`, `recommended_outcome`, `recommendation_reason`, `precedence_applied`, `conflicts` (when evidence disagrees), `evidence_sources`, and `primary_outcome_source` (registry is preferred over static fixtures when the read-only registry shows a **strong installed** signal; fixture recommendations are preserved, not hidden). Optional static capability fixture lookup via `fixtures/automation_lab/capabilities.json` remains advisory demo/fallback and merges with registry candidates when matched. Optional local-model drafting via `local_model_adapter.py` remains advisory only. `scripts/automation_lab_review.ps1` reads `INDEX.json` and prints a compact review summary without modifying artifacts. `INDEX.json` is review evidence only and marks artifacts as non-authority. The lab does not change `/ingest`, add gateway endpoints, approve/authorize plans, execute tools, call the sandbox worker, install tools, call local models from review, or mutate the registry.
- `scripts/test_agent_tool_proposal_flow.ps1` exercises **proposal lane only**: an agent-style message runs `automation_lab_propose.ps1` with an explicit request id, asserts `tool_proposal` artifacts and read-only Navidrome boundary text, and confirms no tool build, candidate, install-review, dry-run, registry JSON, or guarded runtime changes — not a runnable integration path.

## Current tool build workspace (review-only, filesystem)
- `scripts/automation_lab_create_tool_build.ps1` creates `data/tool_builds/<request_id>/` **only** when `data/automation_lab/<request_id>/` already contains `INDEX.json`, `CAPABILITY_MATCHES.json`, and `TOOL_PROPOSAL.md`. It copies selected lab artifacts into `source_automation_lab/`, writes `BUILD_INDEX.json` (schema `tool-build-index.v1`, `authority: false`, `review_evidence_only: true`, boundary flags including `generated_code_present: false`, `install_allowed: false`, `execution_allowed: false`), planning stubs `IMPLEMENTATION_PLAN.md` and `BUILD_REVIEW.md`, and empty implementation placeholders `candidate/README.md` and `tests/README.md`. If the build directory already exists, the script exits with an error and does not overwrite. It does not run Python, the lab generator, the sandbox, tools, or registry mutation paths. Registry `status=installed` remains execution truth.

## Current tool candidate generation (review-only, filesystem)
- `scripts/automation_lab_generate_tool_candidate.ps1` accepts `-ToolBuildId` (matching `^[A-Za-z0-9_-]{8,80}$`) and, under `data/tool_builds/<id>/` only, reads `BUILD_INDEX.json` and `source_automation_lab/TOOL_PROPOSAL.md`. It refuses when `install_allowed` or `execution_allowed` is not strictly `false`, when required paths are missing, when output files already exist, or when the resolved path leaves `data/tool_builds/`. It writes deterministic template artifacts: `candidate/CANDIDATE_TOOL.py` (stub only: `NotImplementedError`, no network/subprocess/`open`/gateway imports, no `__name__` block), `candidate/TOOL_SCHEMA.json` (advisory `review_only` / `not_registry_installation` metadata), `candidate/CANDIDATE_NOTES.md`, `candidate/RISK_NOTES.md`, and `tests/TEST_PLAN.md` (future tests described only). It updates `BUILD_INDEX.json` with `generated_code_present: true`, `candidate_generation_completed: true`, `candidate_files`, and `tests_generated: false` while reasserting non-authority flags. No model, no Python execution of the candidate, no install, no registry mutation, no sandbox, no gateway changes, and no copy into `tools.py` or registry directories.

## Current generated-tool static test harness (review-only, filesystem)
- `scripts/automation_lab_test_tool_candidate.ps1` accepts `-ToolBuildId` (same id regex as above), operates only under `data/tool_builds/<id>/`, and refuses if `TEST_RESULTS.json` or `TEST_SUMMARY.md` already exists, required candidate files are missing, or `BUILD_INDEX.json` is not strictly safe for static review (`authority: false`, `review_evidence_only: true`, install/execution/registry/tools/sandbox flags false, `generated_code_present` / `candidate_generation_completed` true). It performs offline checks only (JSON parse of `TOOL_SCHEMA.json`, `review_only`/`advisory`, text scans on `CANDIDATE_TOOL.py` for forbidden patterns, candidate tree containment, `tools.py` unchanged, guarded runtime file hashes unchanged). It writes `TEST_RESULTS.json` (schema `generated-tool-test-results.v1`, `test_harness_kind: static_review`, `candidate_code_executed: false`, `overall_status: passed|failed`, per-check records) and `TEST_SUMMARY.md` (explicit non-execution disclaimer). On full pass it updates `BUILD_INDEX.json` with `test_harness_completed`, `static_validation_completed`, and paths to those artifacts; on check failure it still writes results with `overall_status: failed` and exits `2` without mutating `BUILD_INDEX`. On write failure it removes partial results and restores the backed-up `BUILD_INDEX.json`. No candidate import/execution, sandbox, registry mutation, gateway, or install.

## Current tool install review packaging (review-only, filesystem)
- `scripts/automation_lab_create_tool_install_review.ps1` accepts `-ToolBuildId` (same id regex), operates only under `data/tool_builds/<id>/`, and requires `BUILD_INDEX.json`, `source_automation_lab/TOOL_PROPOSAL.md`, full candidate file set, `tests/TEST_PLAN.md`, and passing `TEST_RESULTS.json` / `TEST_SUMMARY.md` from the static harness. It **fail-closed** unless `BUILD_INDEX.json` records a completed safe pipeline (`test_harness_completed`, `static_validation_completed`, `generated_code_present`, `candidate_generation_completed`, `candidate_code_executed: false`, non-authority flags) and `TEST_RESULTS.json` matches `generated-tool-test-results.v1` with `overall_status: passed` and `test_harness_kind: static_review` plus all safety booleans false. It refuses to overwrite `INSTALL_MANIFEST.json` / `INSTALL_REVIEW.md`. On success it writes `INSTALL_MANIFEST.json` (schema `tool-install-review-manifest.v1`, `install_performed: false`, `review_only: true`, `proposed_registry_entry_preview` advisory only, `required_future_steps`) and `INSTALL_REVIEW.md` (human checklist, explicit non-install / install-is-not-execution disclaimers), then updates `BUILD_INDEX.json` with `install_review_created` and paths. On I/O failure after backup it removes partial install-review files and restores `BUILD_INDEX.json` (exit `4`). This is **review packaging only** — no registry mutation, no install, no execution, no sandbox, no gateway, no copy into `tools.py`. Real registry install review and lifecycle remain a later branch.

## Current persistent generated registry metadata (manual install review)
- `data/registry/generated_installed_tools.json` is a JSON array of `ToolDefinition`-compatible rows (typically `status: installed`, `endpoint: internal://generated/<name>`). `registry.py` loads it **after** built-in seed: validates each row with Pydantic, only accepts `status == installed`, skips invalid or colliding keys with logging. This adds **metadata only** to the in-memory registry; **`tools.py` does not gain dispatch** for these names, so attempted execution still fails safely (`Unknown tool implementation`) until a future explicit wiring branch.
- `scripts/automation_lab_install_reviewed_tool.ps1` requires `-ConfirmReviewedInstall` with the exact phrase `INSTALL_REVIEWED_TOOL` (wrong/missing phrase exits before any mutation). It invokes `scripts/registry_append_reviewed_generated_tool.py`, which validates the full install-review package (`BUILD_INDEX.json`, `INSTALL_MANIFEST.json`, `INSTALL_REVIEW.md`, harness results, candidate paths), derives `generated_<sanitized_tool_build_id>` with version `v1`, appends atomically to the persistent JSON, verifies via a **fresh** Python subprocess that `registry.get` sees the entry, then writes `REGISTRY_INSTALL_RECORD.json` / `REGISTRY_INSTALL_SUMMARY.md` and updates `BUILD_INDEX.json` (`registry_install_review_completed`, `registry_modified: true`, `install_performed: true`, **`execution_allowed: false`**). On failure it restores the registry file and `BUILD_INDEX.json` and removes partial evidence. **Install is not execution approval**; normal plan/policy/approval/registry/schema/sandbox remains required for any future runnable tool.

## Current generated-tool dry-run (review-only, evidence)
- `scripts/automation_lab_generated_tool_dry_run.ps1` accepts `-ToolName` (must **case-sensitively** match `^generated_[a-z0-9_]+$`, i.e. lowercase segment only) and `-Version` (must match `^v\d+$` case-sensitively, e.g. `v1`). **Malformed or unsafe CLI** exits nonzero and **does not** create `data/generated_tool_dry_runs/<run_id>/`. **Safe validation failures** (e.g. tool not in registry, version mismatch, non-`installed` row on disk only, endpoint not under `internal://generated/`, or unexpected `_TOOL_FUNCS` entry) create a run directory, write `DRY_RUN_RESULT.json` (schema `generated-tool-dry-run.v1`) and `DRY_RUN_SUMMARY.md` with `overall_status: failed`, and exit nonzero. **Success** writes the same artifacts with `overall_status: passed` and exits `0`. The helper `scripts/generated_tool_dry_run.py` reads registry metadata and statically parses `tools.py` for `_TOOL_FUNCS` keys; it does **not** import `tools.py`, does **not** import or call sandbox, does **not** import or execute candidate code, does **not** mutate the registry, and does **not** add gateway routes. **Install and dry-run are not execution approval**; runnable generated tools remain future work and still require the normal plan/policy/approval/registry/schema/sandbox path once dispatch exists.

## Offline lifecycle example (Navidrome read-only — not runtime)
- `scripts/test_automation_lab_navidrome_readonly_generated_tool_lifecycle_example.ps1` is an **offline, evidence-only** walkthrough for capability id `navidrome_recently_added_albums` (read-only “recently added albums” intent). It writes temporary `data/automation_lab/<id>/` and `data/tool_builds/<id>/`, runs build → candidate generation → static harness → install review packaging → **manual-phrase** persistent registry metadata install → dry-run, asserts read-only boundary language in `TOOL_PROPOSAL.md` and `CANDIDATE_NOTES.md`, restores `data/registry/generated_installed_tools.json`, deletes the temp lab/build dirs and the new dry-run evidence dir, and verifies `tools.py` and other guarded runtime files are unchanged. **It does not call Navidrome**, does not execute candidate code, and does **not** mean a Navidrome tool is runnable in the gateway.

## Current design checkpoints
- `docs/AUTHORITY_AND_EVIDENCE_MODEL.md` — design-only framing for durable authority/config vs compact audit vs full evidence workspaces, retention principles, and triggers-not-authority; **not implemented in runtime code** on this branch.
- `docs/ACTION_EVIDENCE_SCHEMA.md` is a docs-only structured action evidence schema proposal for future action assurance; it is not implemented in runtime code.
- `docs/IO_ADAPTER_CONTRACT.md` is a docs-only I/O adapter contract for future trusted-network input/device work; it is not implemented in runtime code.
- `docs/EXECUTION_AUTHORIZATION.md` is a docs-only execution authorization contract for explicit human authorization of exact reviewed plans; it is not implemented in runtime code.
- `docs/ROUTINE_CONTRACT.md` is a docs-only routine contract for repeatable workflow definitions (target field schema, lifecycle states, trigger vs authority rules, evidence flags, and `missing_capability_behavior.generated_tool_execution_allowed: false`); it is not implemented in runtime code.
- `docs/CAPABILITY_REGISTRY_SCHEMA.md` is a docs-only capability registry metadata contract (advisory fields, lookup outcomes, duplicate/overlap rules, routine and tool-proposal relationships); it is not implemented in runtime code.
- `docs/TOOL_PROPOSAL_SCHEMA.md` is a docs-only tool proposal schema contract (review-only artifacts, capability lookup requirements, implementation and test plan fields, proposal outcomes); it is not implemented in runtime code.
- `docs/LOCAL_MODEL_ADAPTER_CONTRACT.md` is a docs-only local model adapter contract (llama.cpp/Ollama/OpenAI-compatible local runtime targets, adapter responsibilities, structured output, evidence, privacy, and non-authority rules); it is not implemented in runtime code.

## Current test scripts (PowerShell)
- `scripts/test_agent_tool_policy.ps1`
- `scripts/test_agent_tool_proposal_flow.ps1`
- `scripts/test_project_agent_policy.ps1`
- `scripts/test_inspect_file_tool.ps1`
- `scripts/test_propose_patch_tool.ps1`
- `scripts/test_project_readonly_tools.ps1`
- `scripts/test_workspace_storage_report.ps1`
- `scripts/test_workspace_archive_candidates.ps1`
- `scripts/test_plans_from_message.ps1`
- `scripts/test_external_ui_flow.ps1`
- `scripts/test_openwebui_action_wrapper.ps1`
- `scripts/test_openwebui_plan_review_wrapper.ps1`
- `scripts/test_automation_lab_proposal.ps1`
- `scripts/test_automation_lab_local_model_draft.ps1`
- `scripts/test_automation_lab_capability_fixtures.ps1`
- `scripts/test_automation_lab_review_artifact_index.ps1`
- `scripts/test_automation_lab_review_summary.ps1`
- `scripts/test_automation_lab_dashboard_view.ps1`
- `scripts/test_automation_lab_registry_capability_lookup.ps1`
- `scripts/test_automation_lab_capability_scoring.ps1`
- `scripts/test_automation_lab_tool_build_workspace.ps1`
- `scripts/test_automation_lab_tool_candidate_generation.ps1`
- `scripts/test_automation_lab_generated_tool_test_harness.ps1`
- `scripts/test_automation_lab_tool_install_review.ps1`
- `scripts/test_automation_lab_registry_install_review.ps1`
- `scripts/test_automation_lab_generated_tool_dry_run.ps1`
- `scripts/test_automation_lab_navidrome_readonly_generated_tool_lifecycle_example.ps1`
