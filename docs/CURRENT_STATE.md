# CURRENT_STATE — mini-jarvis (checkpoint)

mini-jarvis is a **local-first Agentic Gateway OS** that exposes `/ingest` and a **plan/policy/approval** workflow: agents may propose plans, humans approve them, and only then the gateway executes **installed** tools via a sandboxed worker with an auditable filesystem trail.

## Current architecture summary
- **Gateway remains the authority**: validation, registry, policy, approvals, and execution live in gateway code.
- **Agents are folders**: `agents/<id>/` is configuration/context only; agents do not execute tools.
- **Execution boundary**: tools run via `sandbox.run()` → `sandbox_worker.py` (subprocess + timeout + restricted env).
- **Workspaces are readable state**: `data/workspaces/{active|completed|rejected}/<plan_id>/` mirrors plan lifecycle; files are not authority.

## Implemented APIs
- **Ingest**
  - `POST /ingest`
- **Plan API**
  - `POST /plans/propose`
  - `GET /plans/pending`
  - `GET /plans/pending/{plan_id}`
  - `POST /plans/{plan_id}/approve`
  - `POST /plans/{plan_id}/reject`
  - `POST /plans/{plan_id}/execute`
- **Workspace review API (read-only)**
  - `GET /workspaces?state=active|completed|rejected`
  - `GET /workspaces/{state}/{task_id}`
  - `GET /workspaces/{state}/{task_id}/files/{filename}`
- **Frontend convenience**
  - `POST /plans/from-message` (deterministic, proposal-only)

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

## Current automation lab (proposal-only)
- `scripts/automation_lab_propose.ps1` uses `automation_lab.py` to write indexed review artifacts under `data/automation_lab/<request_id>/`. Capability matching is **registry-informed** via read-only `registry.all_tools()` metadata through `automation_lab_registry_read.py` (no lifecycle mutations, no sandbox, no execution). `CAPABILITY_MATCHES.json` uses schema `automation-lab-capability-matches.v3` and records `registry_lookup`, `registry_matches`, deterministic/fixture layers, advisory `score` / `score_breakdown`, `recommended_outcome`, `recommendation_reason`, `precedence_applied`, `conflicts` (when evidence disagrees), `evidence_sources`, and `primary_outcome_source` (registry is preferred over static fixtures when the read-only registry shows a **strong installed** signal; fixture recommendations are preserved, not hidden). Optional static capability fixture lookup via `fixtures/automation_lab/capabilities.json` remains advisory demo/fallback and merges with registry candidates when matched. Optional local-model drafting via `local_model_adapter.py` remains advisory only. `scripts/automation_lab_review.ps1` reads `INDEX.json` and prints a compact review summary without modifying artifacts. `INDEX.json` is review evidence only and marks artifacts as non-authority. The lab does not change `/ingest`, add gateway endpoints, approve/authorize plans, execute tools, call the sandbox worker, install tools, call local models from review, or mutate the registry.

## Current tool build workspace (review-only, filesystem)
- `scripts/automation_lab_create_tool_build.ps1` creates `data/tool_builds/<request_id>/` **only** when `data/automation_lab/<request_id>/` already contains `INDEX.json`, `CAPABILITY_MATCHES.json`, and `TOOL_PROPOSAL.md`. It copies selected lab artifacts into `source_automation_lab/`, writes `BUILD_INDEX.json` (schema `tool-build-index.v1`, `authority: false`, `review_evidence_only: true`, boundary flags including `generated_code_present: false`, `install_allowed: false`, `execution_allowed: false`), planning stubs `IMPLEMENTATION_PLAN.md` and `BUILD_REVIEW.md`, and empty implementation placeholders `candidate/README.md` and `tests/README.md`. If the build directory already exists, the script exits with an error and does not overwrite. It does not run Python, the lab generator, the sandbox, tools, or registry mutation paths. Registry `status=installed` remains execution truth.

## Current tool candidate generation (review-only, filesystem)
- `scripts/automation_lab_generate_tool_candidate.ps1` accepts `-ToolBuildId` (matching `^[A-Za-z0-9_-]{8,80}$`) and, under `data/tool_builds/<id>/` only, reads `BUILD_INDEX.json` and `source_automation_lab/TOOL_PROPOSAL.md`. It refuses when `install_allowed` or `execution_allowed` is not strictly `false`, when required paths are missing, when output files already exist, or when the resolved path leaves `data/tool_builds/`. It writes deterministic template artifacts: `candidate/CANDIDATE_TOOL.py` (stub only: `NotImplementedError`, no network/subprocess/`open`/gateway imports, no `__name__` block), `candidate/TOOL_SCHEMA.json` (advisory `review_only` / `not_registry_installation` metadata), `candidate/CANDIDATE_NOTES.md`, `candidate/RISK_NOTES.md`, and `tests/TEST_PLAN.md` (future tests described only). It updates `BUILD_INDEX.json` with `generated_code_present: true`, `candidate_generation_completed: true`, `candidate_files`, and `tests_generated: false` while reasserting non-authority flags. No model, no Python execution of the candidate, no install, no registry mutation, no sandbox, no gateway changes, and no copy into `tools.py` or registry directories.

## Current generated-tool static test harness (review-only, filesystem)
- `scripts/automation_lab_test_tool_candidate.ps1` accepts `-ToolBuildId` (same id regex as above), operates only under `data/tool_builds/<id>/`, and refuses if `TEST_RESULTS.json` or `TEST_SUMMARY.md` already exists, required candidate files are missing, or `BUILD_INDEX.json` is not strictly safe for static review (`authority: false`, `review_evidence_only: true`, install/execution/registry/tools/sandbox flags false, `generated_code_present` / `candidate_generation_completed` true). It performs offline checks only (JSON parse of `TOOL_SCHEMA.json`, `review_only`/`advisory`, text scans on `CANDIDATE_TOOL.py` for forbidden patterns, candidate tree containment, `tools.py` unchanged, guarded runtime file hashes unchanged). It writes `TEST_RESULTS.json` (schema `generated-tool-test-results.v1`, `test_harness_kind: static_review`, `candidate_code_executed: false`, `overall_status: passed|failed`, per-check records) and `TEST_SUMMARY.md` (explicit non-execution disclaimer). On full pass it updates `BUILD_INDEX.json` with `test_harness_completed`, `static_validation_completed`, and paths to those artifacts; on check failure it still writes results with `overall_status: failed` and exits `2` without mutating `BUILD_INDEX`. On write failure it removes partial results and restores the backed-up `BUILD_INDEX.json`. No candidate import/execution, sandbox, registry mutation, gateway, or install.

## Current tool install review packaging (review-only, filesystem)
- `scripts/automation_lab_create_tool_install_review.ps1` accepts `-ToolBuildId` (same id regex), operates only under `data/tool_builds/<id>/`, and requires `BUILD_INDEX.json`, `source_automation_lab/TOOL_PROPOSAL.md`, full candidate file set, `tests/TEST_PLAN.md`, and passing `TEST_RESULTS.json` / `TEST_SUMMARY.md` from the static harness. It **fail-closed** unless `BUILD_INDEX.json` records a completed safe pipeline (`test_harness_completed`, `static_validation_completed`, `generated_code_present`, `candidate_generation_completed`, `candidate_code_executed: false`, non-authority flags) and `TEST_RESULTS.json` matches `generated-tool-test-results.v1` with `overall_status: passed` and `test_harness_kind: static_review` plus all safety booleans false. It refuses to overwrite `INSTALL_MANIFEST.json` / `INSTALL_REVIEW.md`. On success it writes `INSTALL_MANIFEST.json` (schema `tool-install-review-manifest.v1`, `install_performed: false`, `review_only: true`, `proposed_registry_entry_preview` advisory only, `required_future_steps`) and `INSTALL_REVIEW.md` (human checklist, explicit non-install / install-is-not-execution disclaimers), then updates `BUILD_INDEX.json` with `install_review_created` and paths. On I/O failure after backup it removes partial install-review files and restores `BUILD_INDEX.json` (exit `4`). This is **review packaging only** — no registry mutation, no install, no execution, no sandbox, no gateway, no copy into `tools.py`. Real registry install review and lifecycle remain a later branch.

## Current persistent generated registry metadata (manual install review)
- `data/registry/generated_installed_tools.json` is a JSON array of `ToolDefinition`-compatible rows (typically `status: installed`, `endpoint: internal://generated/<name>`). `registry.py` loads it **after** built-in seed: validates each row with Pydantic, only accepts `status == installed`, skips invalid or colliding keys with logging. This adds **metadata only** to the in-memory registry; **`tools.py` does not gain dispatch** for these names, so attempted execution still fails safely (`Unknown tool implementation`) until a future **generated-tool dry-run** / wiring branch.
- `scripts/automation_lab_install_reviewed_tool.ps1` requires `-ConfirmReviewedInstall` with the exact phrase `INSTALL_REVIEWED_TOOL` (wrong/missing phrase exits before any mutation). It invokes `scripts/registry_append_reviewed_generated_tool.py`, which validates the full install-review package (`BUILD_INDEX.json`, `INSTALL_MANIFEST.json`, `INSTALL_REVIEW.md`, harness results, candidate paths), derives `generated_<sanitized_tool_build_id>` with version `v1`, appends atomically to the persistent JSON, verifies via a **fresh** Python subprocess that `registry.get` sees the entry, then writes `REGISTRY_INSTALL_RECORD.json` / `REGISTRY_INSTALL_SUMMARY.md` and updates `BUILD_INDEX.json` (`registry_install_review_completed`, `registry_modified: true`, `install_performed: true`, **`execution_allowed: false`**). On failure it restores the registry file and `BUILD_INDEX.json` and removes partial evidence. **Install is not execution approval**; normal plan/policy/approval/registry/schema/sandbox remains required for any future runnable tool.

## Current design checkpoints
- `docs/ACTION_EVIDENCE_SCHEMA.md` is a docs-only structured action evidence schema proposal for future action assurance; it is not implemented in runtime code.
- `docs/IO_ADAPTER_CONTRACT.md` is a docs-only I/O adapter contract for future trusted-network input/device work; it is not implemented in runtime code.
- `docs/EXECUTION_AUTHORIZATION.md` is a docs-only execution authorization contract for explicit human authorization of exact reviewed plans; it is not implemented in runtime code.
- `docs/ROUTINE_CONTRACT.md` is a docs-only routine contract for repeatable workflow definitions (target field schema, lifecycle states, trigger vs authority rules, evidence flags, and `missing_capability_behavior.generated_tool_execution_allowed: false`); it is not implemented in runtime code.
- `docs/CAPABILITY_REGISTRY_SCHEMA.md` is a docs-only capability registry metadata contract (advisory fields, lookup outcomes, duplicate/overlap rules, routine and tool-proposal relationships); it is not implemented in runtime code.
- `docs/TOOL_PROPOSAL_SCHEMA.md` is a docs-only tool proposal schema contract (review-only artifacts, capability lookup requirements, implementation and test plan fields, proposal outcomes); it is not implemented in runtime code.
- `docs/LOCAL_MODEL_ADAPTER_CONTRACT.md` is a docs-only local model adapter contract (llama.cpp/Ollama/OpenAI-compatible local runtime targets, adapter responsibilities, structured output, evidence, privacy, and non-authority rules); it is not implemented in runtime code.

## Current test scripts (PowerShell)
- `scripts/test_agent_tool_policy.ps1`
- `scripts/test_project_agent_policy.ps1`
- `scripts/test_inspect_file_tool.ps1`
- `scripts/test_propose_patch_tool.ps1`
- `scripts/test_project_readonly_tools.ps1`
- `scripts/test_workspace_review_endpoints.ps1`
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
