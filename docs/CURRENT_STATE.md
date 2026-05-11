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
- `integrations/local_dashboard/` — static HTML/JS demo UI that uses gateway endpoints only (no gateway changes).

## Current automation lab (proposal-only)
- `scripts/automation_lab_propose.ps1` uses `automation_lab.py` to write review artifacts under `data/automation_lab/<request_id>/`; optional local-model drafting via `local_model_adapter.py` is explicitly enabled, advisory only, and records model request/response/validation evidence. The lab does not change `/ingest`, add endpoints, approve/authorize plans, execute tools, call the sandbox worker, or mutate the registry.

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

