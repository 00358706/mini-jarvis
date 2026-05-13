# mini-jarvis (Agentic Gateway)

A small **local-first control plane** for safe agentic workflows. It has a gateway for multimodal **input and routing**, a plan/policy/approval path for reviewed work, proposal-only authoring lanes for future capabilities, and a sandboxed execution boundary for installed tools. It targets a homelab stack (Radarr, Sonarr, SABnzbd) plus local project-maintenance workflows with structured responses and an audit trail.

---

## Current phase

Mini-Jarvis is currently an **execution-isolated gateway** with a **plan/policy/approval layer**, **agents as configuration only**, and a proposal-only **Automation Lab** for capability authoring. The gateway owns validation, registry checks, policy, approval state, and execution; `agents/` holds human-readable workflow configuration and does not run tools or touch the network.

Implemented pieces include:
- `POST /ingest` as the multimodal **input surface** and classifier router (including a gated `LOCAL_TOOLS` hint that does **not** execute tools by default).
- `/plans/*` for proposal, review, explicit approval, and explicit execution of installed tools.
- Readable plan workspaces under `data/workspaces/` as evidence only.
- Automation Lab proposal artifacts under `data/automation_lab/<request_id>/`.
- Registry-informed, read-only capability lookup and deterministic scoring for review.
- Tool build workspaces and review-only candidate generation under `data/tool_builds/<request_id>/`, including hardening that rejects unsafe build indexes and rolls back partial candidate output.

`dispatch.process()` gates `LOCAL_TOOLS` on ingest: it returns a plan-required response and audit metadata instead of calling `tools.execute`.

---

## API authentication (role keys)

All protected routes require a valid `X-API-Key` except `GET /health`. **`GATEWAY_API_KEY`** is the **master** key and works for every classified route. Optional **`GATEWAY_INPUT_API_KEY`**, **`GATEWAY_APPROVAL_API_KEY`**, and **`GATEWAY_ADMIN_API_KEY`** narrow what each key may call; when a role key is set, it cannot perform higher-authority actions (**`403`**). HTTP paths that are **not** explicitly allowlisted for role keys are treated as **master-only** (unknown or future routes stay fail-closed).

| Key env | Purpose |
|---------|---------|
| **`GATEWAY_API_KEY`** | **Master** — valid for every protected route (local default and backwards compatibility). |
| **`GATEWAY_INPUT_API_KEY`** (optional) | **Input / proposal** — `POST /ingest`, `POST /plans/propose`, `POST /plans/from-message`; plus the same **read-only** GETs as the approval tier (plans, workspaces, logs, events, tools, **`GET /notifications/pending-approvals`**). Does **not** allow plan approve/reject/execute or registry admin POSTs. |
| **`GATEWAY_APPROVAL_API_KEY`** (optional) | **Plan authority** — `POST /plans/{id}/approve`, `reject`, `execute`, plus **read-only** GETs (`/plans/pending`, `/notifications/pending-approvals`, workspaces, logs, events, tools). Does **not** allow `POST /plans/propose` or registry admin POSTs. |
| **`GATEWAY_ADMIN_API_KEY`** (optional) | **Registry lifecycle** — `POST /tools/propose`, `approve`, `install`, `reject`, plus the same read-only GETs as above. **Approval key never counts as admin.** |

If an optional role key is **unset**, behavior falls back to **master-only** for that tier (same as before role keys existed). If **set**, only **that key** or the **master** key may perform that tier’s actions; a recognized but wrong-tier key receives **`403`** with `route_role` in the JSON body. Unknown or missing keys → **`401`**.

### Pending approval notifications (informational only)

When a plan is saved as **pending approval** (`POST /plans/propose` or `POST /plans/from-message` with `requires_approval` and policy allowed), the gateway appends one JSON line to **`data/notifications/pending_approvals.jsonl`** (local append-only log; not a deduplicated inbox — the same `plan_id` re-proposed appends another line). Payloads are **visibility only**: `can_approve` and `can_execute` are always **`false`** in the notification record; they do **not** grant authority. **Approval** still requires **`POST /plans/{plan_id}/approve`** with an approval-capable key and a valid pending **`reviewed_plan_sha256`** (see **`GET /plans/pending/{plan_id}`**). **Execution** still requires **`POST /plans/{plan_id}/execute`** with an approval-capable key and a valid **`approved_plan_sha256`**. **`GET /notifications/pending-approvals`** returns the latest records (default cap **200**), is read-only, and does not call approve, reject, execute, webhooks, or the registry. The file is gitignored (see `.gitignore`); only the directory placeholder may be tracked.

## Control-plane lanes / chatbar mental model

`/ingest` remains the primary multimodal **input envelope** surface (text, voice, image, event). It classifies into routing targets but must not treat classifier output as execution permission for installed tools.

A future chatbar, channel, or event surface should route internally to explicit lanes:
- Existing capability/runtime request.
- Plan proposal.
- Automation Lab proposal.
- Routine trigger later.
- Review request.

Automation Lab remains proposal/review-only. It must not execute tools, install tools, mutate the registry, call the sandbox worker, or bypass gateway policy and approval.

---

## Runtime pipeline (`POST /ingest`)

End-to-end flow:

```
POST /ingest
     │
     ▼
┌─────────────┐
│  ingestion  │  normalise() — modality-specific validation, NormalisedEnvelope
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│ classification  │  Ollama, temperature 0, strict routing token allowlist
└──────┬──────────┘
       │  RoutingTarget
       ▼
┌─────────────────────────────────────────────────────────────┐
│                        dispatch.process                      │
│  (audit ingest → classify → route branch → audit → response) │
└──────┬────────────────────────────────────────────────────────┘
       │
       ├── LOCAL_TOOLS → gated response (plan_proposal_required);
       │                   no tools.execute, no sandbox on this path
       │
       ├── LOCAL_LLM / CLOUD_LLM → LLM routing branches
       │
       └── DROP → safe refusal
```

**Approved execution** of installed tools uses `POST /plans/{plan_id}/execute` after policy checks and explicit human approval — registry lookup, schema validation, `sandbox.run()`, and `sandbox_worker` apply there, not on `/ingest` for `LOCAL_TOOLS`.

Other routing targets (`LOCAL_LLM`, `CLOUD_LLM`, `DROP`) skip tool execution; they still go through `dispatch` and are audited where applicable. A future policy-gated read-only runtime lane on ingest is out of scope until explicitly designed.

---

## Automation Lab / capability authoring lane

Automation Lab is the proposal/review lane for capability gaps and candidate authoring:

```text
chatbar/dashboard request
-> automation_lab.py
-> deterministic classification
-> read-only registry capability lookup via automation_lab_registry_read.py
-> optional fixture lookup
-> deterministic capability scoring via automation_lab_capability_scoring.py
-> CAPABILITY_MATCHES.json v3
-> TOOL/ROUTINE/AGENT proposal artifact
-> INDEX.json
-> review CLI/dashboard
-> no execution/install
```

Review artifacts live under `data/automation_lab/<request_id>/`. Tool build workspaces live under `data/tool_builds/<request_id>/` and may contain review-only candidate drafts. These files are evidence for humans; they are not registry entries, approvals, authorizations, or execution permission.

---

## `agents/` — configuration only

The `agents/` tree (e.g. `agents/media_agent/` with `agent.yaml`, `tools.yaml`, `policy.yaml`, `prompt.md`, `examples.md`, `local_data/`) is **workflow-oriented documentation and policy for a future planner**. It does **not** execute tools, import gateway code, or substitute for the registry. The gateway remains the authority for what may run; the sandbox remains the only path for tool execution.

---

## Filesystem workspaces

- `data/workspaces/active/` while plans are proposed/approved.
- `data/workspaces/rejected/` when plans are rejected.
- `data/workspaces/completed/` after plan execution finishes.
- `AGENT.md` and `CONTEXT.md` may be written for readable planning context.
- `ROUTE.json` may be written with route metadata; it is observational only and does not authorize execution.
- Executed approved plans may write `EXECUTION_LOG.jsonl` and `RESULT.md`; execution reports `executed_success` or `executed_with_errors`.
- Agents can opt into strict proposal constraints with `enforcement.mode: strict` in `tools.yaml`; this limits what that agent may propose.
- Registry remains the source of truth for installed tools, and sandbox execution remains the only side-effect path after approval.
- `workspace.py` manages readable files only.
- `plans.py` validates `PLAN.json`.
- `policy.py` writes and represents deterministic decisions.
- `approvals.py` tracks approval state.
- The sandbox worker remains the only side-effect execution path.
- Model output is proposal, not authority.

---

## `sandbox_worker.py` — execution boundary

Tool implementations live in `tools.py`, but the **parent gateway process does not call them directly** for the hot path. `sandbox.run()` starts `sandbox_worker.py` as a **separate Python process** with a fresh working directory, allowlisted environment, and wall-clock timeout. The worker reads a JSON payload from stdin and calls `run_tool_by_name()` so real network and side effects occur **only** inside that child process (subject to timeouts and future hardening).

---

## `http_allowlist.py` and `tools_http.py`

Built-in tools reach Radarr, Sonarr, and SABnzbd through **`tools_http.py`** (central **`httpx`**). Before each request, **`validate_http_destination()`** in `http_allowlist.py` checks the full URL against the **configured base URL** (same scheme, host, port, and path prefix). That blocks accidental requests to arbitrary hosts; it is **not** a substitute for OS-level network isolation. A static test (`scripts/test_tool_http_allowlist_guard.py`) fails if `tools.py` / `sandbox.py` / `sandbox_worker.py` import raw HTTP clients directly. Future work may move registry `http_allowlist` enforcement into `tools_http`; this branch does not claim that yet.

---

## `CURSOR_RULES.md`

If you use Cursor with project-scoped rules, keep a **`CURSOR_RULES.md`** at the repository root as the **canonical place for editor/agent conventions** (safety boundaries, file ownership, review expectations). It does not affect runtime; it aligns human and agent contributors with how this repo is meant to evolve. Add the file when your workflow needs it.

---

## Repository layout

| Module | Role |
|--------|------|
| `main.py` | Composes `FastAPI` app: logging, lifespan, auth middleware, global exception handler, **`GET /health`**, `include_router` for `routers/*` |
| `routers/` | HTTP route handlers (`ingest`, `plans`, `notifications`, `workspaces`, `logs`, `tools`) — refactor-only; same paths and semantics as before split |
| `services/auth_roles.py` | `classify_api_key`, `route_api_role`, `key_allows_route` for middleware |
| `services/workspace_mirror.py` | Plan proposal workspace mirror helpers (readable evidence files) |
| `ingestion.py` | Normalise ingest payloads |
| `classification.py` | Intent → `RoutingTarget` |
| `dispatch.py` | Orchestrate classify → route → execute → failure notes → audit |
| `routing.py` | Local / cloud LLM backends |
| `registry.py` | Tool definitions and lifecycle |
| `tools.py` | Intent parsing, registry + schema gate, `sandbox.run()` |
| `sandbox.py` | Subprocess isolation for tools |
| `sandbox_worker.py` | Child entrypoint for one tool invocation |
| `tools_http.py` | Central `httpx` client for tool execution and `execute_http_tool` |
| `http_allowlist.py` | Per-request URL policy for tool HTTP calls |
| `audit.py` | Structured audit log |
| `config.py` | Environment-backed settings |
| `plans.py` | Defines structured plan models; no execution |
| `policy.py` | Evaluates proposed plans against policy; no execution |
| `approvals.py` | Stores plan JSON under `data/plans/`; per-plan transition locks under `data/plans/locks/<plan_id>.lockdir` |
| `agent_loader.py` | Reads agent folder metadata from `agents/<id>/`; no code execution from agent dirs |
| `workspace.py` | Manages task workspace files under `data/workspaces/`; filesystem only |
| `automation_lab.py` | Writes proposal-only Automation Lab artifacts; no execution/install |
| `automation_lab_review.py` | Read-only review summary helper for Automation Lab `INDEX.json` |
| `automation_lab_registry_read.py` | Read-only registry capability evidence for Automation Lab |
| `automation_lab_capability_scoring.py` | Deterministic advisory capability scoring and conflict reporting |
| `local_model_adapter.py` | Optional local-model drafting helper; advisory only and disabled unless requested |
| `scripts/automation_lab_create_tool_build.ps1` | Creates review-only tool build workspaces under `data/tool_builds/` |
| `scripts/automation_lab_generate_tool_candidate.ps1` | Emits review-only candidate drafts under an existing tool build workspace |
| `scripts/test_automation_lab_tool_candidate_generation.ps1` | Static/filesystem safety coverage for candidate generation |

Also see `docs/AI_OS_HIERARCHY.md` for the conceptual stack: human → gateway → agent context → planner → policy → registry → approval/session → sandbox → tools → audit.

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env — at minimum set GATEWAY_API_KEY; set Ollama and media keys as needed.
python main.py
# or: uvicorn main:app --host 0.0.0.0 --port 8000
```

## Python environment

Recommended: use the project venv (`.venv`) so the gateway, smoke tests, and optional integration scripts use the same interpreter/dependencies.

- Setup venv:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_venv.ps1
```

- Activate:

```powershell
.\.venv\Scripts\Activate.ps1
```

- Run gateway:

```powershell
python main.py
```

- Run all smoke tests (gateway must already be running):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_all_tests.ps1
```

See `docs/ENVIRONMENT.md`.

Bind address: set `GATEWAY_HOST` (for example a Tailscale IP) so the gateway does not listen more broadly than you intend.

---

## Endpoint inventory

Current `main.py` routes:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | unauthenticated health/status |
| `POST` | `/ingest` | normalise, classify, route, and return a gateway response |
| `POST` | `/plans/propose` | policy-check and store pending plan with server `reviewed_plan_sha256`; strips client hash fields; no execution |
| `POST` | `/plans/from-message` | deterministic plan builder (`services/plan_builder.py`) → `POST /plans/propose`; supports `project_maintainer_agent` and `media_agent`; **400** `missing_capability` when no installed tool matches; no approval or execution |
| `GET` | `/plans/pending` | list pending plan ids |
| `GET` | `/plans/pending/{plan_id}` | read one pending plan (includes `reviewed_plan_sha256` when present) |
| `GET` | `/notifications/pending-approvals` | read-only: latest pending-approval **informational** notifications (append-only JSONL source); not an approval or execution surface |
| `POST` | `/plans/{plan_id}/approve` | verify pending hash, set `approved_plan_sha256`, move to approved; no execution |
| `POST` | `/plans/{plan_id}/reject` | move pending plan to rejected |
| `POST` | `/plans/{plan_id}/execute` | verify approved content hash, then policy + registry/schema/sandbox; `409` if already executed |
| `GET` | `/workspaces?state=active\|completed\|rejected` | list read-only workspace summaries |
| `GET` | `/workspaces/{state}/{task_id}` | read one workspace summary |
| `GET` | `/workspaces/{state}/{task_id}/files/{filename}` | read one known workspace artifact |
| `GET` | `/logs` | list audit entries |
| `GET` | `/events` | list audit entries where `kind == "event"` |
| `GET` | `/tools` | list registry entries in all lifecycle states |
| `GET` | `/tools/{name}/{version}` | inspect one registry entry |
| `POST` | `/tools/propose` | create a proposed registry entry |
| `POST` | `/tools/approve` | move proposed tool to approved |
| `POST` | `/tools/install` | move approved tool to installed |
| `POST` | `/tools/reject` | reject a proposed tool |

---

## Environment variables (from `.env.example`)

| Variable | Purpose |
|----------|---------|
| `GATEWAY_HOST` | Bind address; default `0.0.0.0` |
| `GATEWAY_PORT` | Listen port; default `8000` |
| `GATEWAY_API_KEY` | Master `X-API-Key` for all routes; use strong random value in production |
| `GATEWAY_INPUT_API_KEY` | (Optional) Input/proposal-only client key — see **API authentication** above |
| `GATEWAY_APPROVAL_API_KEY` | (Optional) Plan approve/reject/execute + listed read-only GETs |
| `GATEWAY_ADMIN_API_KEY` | (Optional) Registry tool lifecycle POSTs + same read-only GETs |
| `OLLAMA_URL` | Ollama base URL |
| `CLASSIFIER_MODEL` | Model for intent classification |
| `LOCAL_LLM_MODEL` | Model for `LOCAL_LLM` responses |
| `CLASSIFIER_MAX_TOKENS` | Max tokens for classifier output |
| `OPENROUTER_API_KEY` | API key for `CLOUD_LLM` |
| `CLOUD_MODEL` | OpenRouter model slug |
| `RADARR_URL` / `RADARR_API_KEY` | Radarr |
| `SONARR_URL` / `SONARR_API_KEY` | Sonarr |
| `SABNZBD_URL` / `SABNZBD_API_KEY` | SABnzbd |
| `OLLAMA_TIMEOUT` / `CLOUD_TIMEOUT` / `TOOL_TIMEOUT` | HTTP timeouts in seconds |

Comment-only placeholders in `.env.example` are optional/future: `CLOUD_ALLOW_SENSITIVE`, `ENABLE_SANDBOX_PYTHON_EXEC`.

---

## Basic smoke tests

Replace `your-secret-key` with `GATEWAY_API_KEY` from `.env`.

**1. Health check** (no auth):

```bash
curl http://localhost:8000/health
```

**2. Ingest — tool-intent hint** (when the classifier routes to `LOCAL_TOOLS`, for example Radarr-like text, the gateway returns a **gated** response: `lane: plan_proposal_required`, no tool execution, no sandbox; use `/plans/*` for execution):

```bash
curl -X POST http://localhost:8000/ingest \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secret-key" \
     -d "{\"modality\":\"text\",\"content\":\"add movie inception\",\"source_device\":\"curl\"}"
```

**3. Logs endpoint**:

```bash
curl -H "X-API-Key: your-secret-key" "http://localhost:8000/logs?limit=50"
```

**4. Tools endpoint** (registry listing):

```bash
curl -H "X-API-Key: your-secret-key" http://localhost:8000/tools
```

### Plan API smoke test

- Start the gateway first with `python main.py`.
- Run `powershell -ExecutionPolicy Bypass -File .\scripts\test_plan_api.ps1`.
- `powershell -ExecutionPolicy Bypass -File .\scripts\test_external_ui_flow.ps1` simulates a safe external UI/client flow through proposal, review, explicit approval, explicit execution, and completed result review.
- On Linux/macOS, `scripts/test_plans_from_message.sh` mirrors the `/plans/from-message` PowerShell smoke test.
- `python scripts/test_tool_http_allowlist_guard.py` fails if tool execution modules import raw HTTP clients (`requests`, `httpx`, etc.) outside `tools_http.py`.
- `python scripts/test_router_split_regression.py` checks OpenAPI paths and auth-role mapping after the `routers/` split (no live traffic).
- `python scripts/test_ingest_local_tools_gated.py` fails if `/ingest` with `LOCAL_TOOLS` calls `tools.execute` or `sandbox.run`, or if `dispatch.py` reintroduces a direct `tools_execute` reference.
- `python scripts/test_approval_state_locking.py` locks plan content hashes on propose/approve, fail-closed execute on mismatch or missing hash, duplicate-execute `409`, and rejects legacy pending without `reviewed_plan_sha256`.
- `python scripts/test_approval_file_locking.py` asserts per-plan transition locks (`data/plans/locks/<plan_id>.lockdir`) and **409** `plan_transition_locked` on approve/reject/execute contention.
- `python scripts/test_policy_approval_unit_tests.py` exercises `evaluate_plan`, `/plans/*` boundaries, ingest gating, and policy-before-execute ordering (stubbed tools).
- `python scripts/test_approval_role_keys.py` checks optional `GATEWAY_*_API_KEY` role separation vs master `GATEWAY_API_KEY`.
- `python scripts/test_plan_builder_generalization.py` exercises generalized `/plans/from-message` (maintainer + media + missing capability + roles) without tool/sandbox/registry side effects.
- The script calls `/health`, `/plans/pending`, `/plans/propose`, `/plans/pending/{plan_id}`, and `/plans/{plan_id}/reject`.
- It checks that a plan can be policy-checked, saved as pending, read back, rejected, and removed from pending.
- It does not execute tools or call the sandbox.
- `project_maintainer_agent` can be tested via `powershell -ExecutionPolicy Bypass -File .\scripts\test_project_agent_policy.ps1`.
- `inspect_file` is a read-only maintainer tool (`file:read`) for small repository files.
- `inspect_file` is repository-confined and executes through the sandbox worker path.
- `list_project_files` is a read-only maintainer tool (`file:list`) that lists repository files without reading contents.
- `search_repo` is a read-only maintainer tool (`file:search`) that does literal text search over repository text files.
- `propose_patch` is a proposal-only maintainer tool (`file:proposal`).
- `propose_patch` does not apply changes; human review/approval is still required.
- If an agent references a tool that is not installed in the registry, policy/registry validation must fail safely before execution.

### `POST /plans/from-message` (frontend convenience)
Convenience endpoint for Open WebUI or other local frontends to **create a proposed plan from a user message**.
It uses **`services/plan_builder.py`** (deterministic, rule-based): allowlisted agents only, registry **installed** tool names as capability truth (no invented tools). It does **not** approve plans, execute tools, call the sandbox, or mutate the registry.

- **Supported agents:** `project_maintainer_agent` (repository list/search/inspect paths, unchanged intent) and `media_agent` (safe mappings such as movie/series search and SABnzbd queue when the corresponding tools are **installed**).
- **Missing capability:** requests such as Navidrome album browsing with no installed handler return **400** JSON with `status: "missing_capability"`, `proposal_needed: true`, and a hint toward Automation Lab / explicit tool work — **no** pending plan and **no** notification append.
- **Unsupported agent:** **400** with FastAPI `detail` (same shape as before for unknown agents).
- Successful builds route through **`POST /plans/propose`** (policy, workspace mirror, pending + notification as today).

### Workspace Review API
Read-only endpoints for inspecting `data/workspaces/*` planning state (protected by `X-API-Key`).
They do not execute tools or mutate workspace files.

- `GET /workspaces?state=active|completed|rejected` — list compact workspace summaries.
- `GET /workspaces/{state}/{task_id}/compact` — compact “approval-card” summary for human review UX.
- `GET /workspaces/{state}/{task_id}` — detailed review summary including `PLAN.json` / `POLICY_DECISION.json` (if present).
- `GET /workspaces/{state}/{task_id}/files/{filename}` — read one known standard workspace file (e.g. `RESULT.md`).

For full file review, use the detailed endpoints above; the `/compact` endpoint is intentionally concise and read-only.

### Open WebUI integration (proposal-only)
This repo includes a simple wrapper script that **proposes plans only** (no approval, no execution).
Approval and execution remain separate gateway steps (`/plans/{plan_id}/approve`, `/plans/{plan_id}/execute`).

- Wrapper: `integrations/openwebui/mini_jarvis_plan_propose.py`
- Environment variables:
  - `MINI_JARVIS_BASE_URL` (default `http://127.0.0.1:8000`)
  - `MINI_JARVIS_API_KEY` (required; same value as gateway `GATEWAY_API_KEY`)
  - `MINI_JARVIS_AGENT` (default `project_maintainer_agent`)
  - `DEBUG=1` (optional; prints raw JSON responses)

Safe workflow (no shortcuts):
1. **Propose** (creates a pending plan; does not approve; does not execute):

```powershell
.\.venv\Scripts\python.exe integrations\openwebui\mini_jarvis_plan_propose.py "list project files"
```

2. **Review** the compact “approval-card” summary (read-only):

```powershell
.\.venv\Scripts\python.exe integrations\openwebui\mini_jarvis_plan_review.py show <plan_id>
```

### Open WebUI integration (review/approve/execute wrapper)
Separate wrapper for reviewing an existing plan and explicitly calling approval/execution endpoints.
Proposal, approval, and execution are intentionally separate steps.

- Wrapper: `integrations/openwebui/mini_jarvis_plan_review.py`
- Commands:
  - `pending` (list pending plans; read-only index + next-step commands)
  - `show <plan_id>`
  - `approve <plan_id> --confirm`
  - `reject <plan_id> --confirm`
  - `execute <plan_id> --confirm`

3. **Approve** (requires `--confirm`; does not execute tools):

```powershell
.\.venv\Scripts\python.exe integrations\openwebui\mini_jarvis_plan_review.py approve <plan_id> --confirm
```

4. **Execute** (requires `--confirm`; only works after approval; does not auto-approve):

```powershell
.\.venv\Scripts\python.exe integrations\openwebui\mini_jarvis_plan_review.py execute <plan_id> --confirm
```

Notes:
- Workspace summaries are **review aids only** (read-only mirrors). Authority remains with gateway code, policy, registry, approval state, and the sandbox execution boundary.
- Wrapper output is **compact by default**; set `DEBUG=1` if you need raw/verbose JSON.

### MCP integration (optional)
Optional, separate MCP stdio server that exposes **read-only workspace resources** only (no MCP tools).
Approval and execution remain via the gateway endpoints and wrappers.

- Script: `integrations/mcp/mini_jarvis_workspace_resources.py`
- Resources (examples):
  - `mini-jarvis://workspaces/active`
  - `mini-jarvis://workspaces/active/{task_id}/compact`
  - `mini-jarvis://workspaces/active/{task_id}/files/PLAN.json`

---

## Security invariants

- Every route except **`/health`** requires a valid **`X-API-Key`**. **`GATEWAY_API_KEY`** is the **master** key (all routes). Optional role keys restrict clients by route class; keys that are valid but insufficient for a path receive **`403`**. Paths outside the explicit role allowlist are **master-only** (fail closed for future routes).
- Plan lifecycle JSON under **`data/plans/`** is **hash-bound** for integrity and **per-plan transition locked** via **`data/plans/locks/<plan_id>.lockdir`** (atomic directory create; wait then **409** `plan_transition_locked` on contention). This is a minimal cross-platform filesystem guard, not a database; SQLite remains a possible later option if coordination needs grow.
- The classifier is constrained to an **allowlist of routing tokens**; free-form model output is not executed as code or routing.
- Tools run only if they appear in the registry with **`installed`** status; arguments are checked against the registry **`input_schema`** before the sandbox runs.
- **Tool execution** goes through **`sandbox.run()` → `sandbox_worker`** only; the gateway does not call tool coroutines directly on the ingest path.
- **`http_allowlist`** restricts tool HTTP destinations to the configured service base URLs; **`tools_http`** is the only approved `httpx` surface on the tool execution path (see `scripts/test_tool_http_allowlist_guard.py`).
- Sensitive or multimodal raw payloads are not forwarded blindly to LLMs per existing ingestion and routing policy (see code comments in `ingestion.py` / routing paths).

---

## Project checkpoint docs

- `docs/AGENT_HANDOFF.md`
- `docs/UI_CLIENT_CONTRACT.md`
- `docs/CURRENT_STATE.md`
- `docs/ARCHITECTURE_INVARIANTS.md`

## Project memory wiki

- `docs/wiki/README.md`

## Project backlog
Deferred ideas and future branch candidates live in [`docs/BACKLOG.md`](docs/BACKLOG.md). Backlog items are not active implementation instructions unless explicitly selected.

## Extending tools and routing

- **New built-in tool**: implement in `tools.py`, register in `_TOOL_FUNCS`, seed or lifecycle through `registry`, extend `_INTENT_MAP` as needed; route outbound HTTP through `tools_http` and keep `http_allowlist` checks before requests.
- **New routing target**: update `models.py`, `classification.py`, and `dispatch.py` together.
- **Agent personas**: extend under `agents/<agent_id>/`; wire-up in application code is a separate phase.
- **Generated tool candidates**: proposed/generated tools must move through proposal artifacts, a tool build workspace, tests, install review, explicit registry install, and then normal plan/policy/approval/schema/sandbox execution. Candidate files are not edited directly into production tools or registry state.
