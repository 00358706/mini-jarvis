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
- `scripts/automation_lab_create_tool_build.ps1` creates `data/tool_builds/<request_id>/` **only** when `data/automation_lab/<request_id>/` already contains `INDEX.json`, `CAPABILITY_MATCHES.json`, and `TOOL_PROPOSAL.md`. It copies selected lab artifacts into `source_automation_lab/`, writes `BUILD_INDEX.json` (schema `tool-build-index.v1`, `authority: false`, `review_evidence_only: true`, boundary flags including `generated_code_present: false`, `install_allowed: false`, `execution_allowed: false`), planning stubs `IMPLEMENTATION_PLAN.md` and `BUILD_REVIEW.md`, and empty implementation placeholders `candidate/README.md` and `tests/README.md`. If the build directory already exists, the script exits with an error and does not overwrite. It does not run Python, the lab generator, the sandbox, tools, or registry mutation paths. Generated tool source belongs to a later `tool-candidate-generation` step; registry `status=installed` remains execution truth.

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
