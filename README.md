# mini-jarvis (Agentic Gateway)

A small **local-first gateway** that ingests multimodal requests, classifies intent with a deterministic local model, routes to the right backend (homelab tools, local LLM, or cloud LLM), and runs **registered** tool calls through an isolated subprocess. It targets a homelab stack (Radarr, Sonarr, SABnzbd) with structured responses and an audit trail.

---

## Current phase

**Execution-isolated gateway** with a separate **agent configuration layer** (under `agents/`). The gateway owns validation, routing, and execution; `agents/` holds human-readable workflow configuration (purpose, prompts, allowlisted tool names, policy text, examples, optional local data) for future planners. **Nothing under `agents/` runs tools or touches the network today.**

**Next architecture milestone: Plan + Policy + Approval layer.** `plans.py` defines structured plan models; `policy.py` evaluates proposed plans; `approvals.py` stores pending, approved, rejected, and executed plan JSON under `data/plans/`; `agent_loader.py` reads agent folder metadata. The **`/plans/*`** routes cover planning and approval; **`POST /plans/{plan_id}/execute`** runs **approved** plans only, re-checks policy, and executes each step through the registry, schema validation, and **`sandbox`** (pending/proposed plans never execute here). **`/plans/propose`** also mirrors accepted/rejected proposal state into `data/workspaces/` as readable files only; those files do not authorize execution. **`dispatch.process()`** is unchanged for now.

---

## Main pipeline (`POST /ingest`)

End-to-end flow for a typical ingest:

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
       │  LOCAL_TOOLS branch
       ▼
┌─────────────┐
│   tools     │  intent → registry lookup (installed only) →
└──────┬──────┘  validate_args_against_schema (registry input_schema)
       │
       ▼
┌─────────────┐
│  sandbox    │  sandbox.run() — subprocess spawn, timeout, restricted env
└──────┬──────┘
       │
       ▼
┌──────────────────┐
│ sandbox_worker   │  stdin JSON → run_tool_by_name() in child process
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│  tool execution  │  httpx to configured services (after http_allowlist check)
└──────┬───────────┘
       │
       ▼
┌─────────────┐
│    audit    │  append structured entries (ingest, tool, lifecycle, …)
└─────────────┘
```

Other routing targets (`LOCAL_LLM`, `CLOUD_LLM`, `DROP`) skip the tool registry and sandbox; they still go through `dispatch` and are audited where applicable.

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

## `http_allowlist.py`

Built-in tools use **httpx** against Radarr, Sonarr, and SABnzbd URLs derived from configuration. `validate_http_destination()` ensures each request URL matches the **configured base URL** (same scheme, host, port, and path prefix). That blocks accidental or buggy requests to arbitrary hosts; it is **not** a substitute for OS-level network isolation.

---

## `CURSOR_RULES.md`

If you use Cursor with project-scoped rules, keep a **`CURSOR_RULES.md`** at the repository root as the **canonical place for editor/agent conventions** (safety boundaries, file ownership, review expectations). It does not affect runtime; it aligns human and agent contributors with how this repo is meant to evolve. Add the file when your workflow needs it.

---

## Repository layout (runtime)

| Module | Role |
|--------|------|
| `main.py` | FastAPI app, auth, `/ingest`, `/plans/*`, `/health`, `/logs`, `/tools`, lifecycle endpoints |
| `ingestion.py` | Normalise ingest payloads |
| `classification.py` | Intent → `RoutingTarget` |
| `dispatch.py` | Orchestrate classify → route → execute → failure notes → audit |
| `routing.py` | Local / cloud LLM backends |
| `registry.py` | Tool definitions and lifecycle |
| `tools.py` | Intent parsing, registry + schema gate, `sandbox.run()` |
| `sandbox.py` | Subprocess isolation for tools |
| `sandbox_worker.py` | Child entrypoint for one tool invocation |
| `http_allowlist.py` | Per-request URL policy for tool HTTP calls |
| `audit.py` | Structured audit log |
| `config.py` | Environment-backed settings |
| `plans.py` | Defines structured plan models; no execution |
| `policy.py` | Evaluates proposed plans against policy; no execution |
| `approvals.py` | Stores pending, approved, rejected, and executed plan JSON under `data/plans/` |
| `agent_loader.py` | Reads agent folder metadata from `agents/<id>/`; no code execution from agent dirs |
| `workspace.py` | Manages task workspace files under `data/workspaces/`; filesystem only |

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

Bind address: set `GATEWAY_HOST` (for example a Tailscale IP) so the gateway does not listen more broadly than you intend.

---

## Endpoint inventory

Current `main.py` routes:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | unauthenticated health/status |
| `POST` | `/ingest` | normalise, classify, route, and return a gateway response |
| `POST` | `/plans/propose` | policy-check and store a proposed plan; no execution |
| `POST` | `/plans/from-message` | deterministic frontend helper that creates a proposed plan; no approval or execution |
| `GET` | `/plans/pending` | list pending plan ids |
| `GET` | `/plans/pending/{plan_id}` | read one pending plan |
| `POST` | `/plans/{plan_id}/approve` | move pending plan to approved; no execution |
| `POST` | `/plans/{plan_id}/reject` | move pending plan to rejected |
| `POST` | `/plans/{plan_id}/execute` | execute an approved plan through registry/schema/sandbox checks |
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
| `GATEWAY_API_KEY` | Required `X-API-Key` value for authenticated routes |
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

**2. Ingest — local tool path** (classifier must route to `LOCAL_TOOLS`; example text matches Radarr intent):

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
- On Linux/macOS, `scripts/test_plans_from_message.sh` mirrors the `/plans/from-message` PowerShell smoke test.
- `python scripts/test_plans_from_message_no_execute.py` is a local regression test that fails if `/plans/from-message` crosses into tool execution.
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
It is deterministic (rule-based), does **not** approve plans, and does **not** execute tools.

- `POST /plans/from-message` — builds a single-step plan and routes it through the same policy/workspace mirror as `POST /plans/propose`.

### Workspace Review API
Read-only endpoints for inspecting `data/workspaces/*` planning state (protected by `X-API-Key`).
They do not execute tools or mutate workspace files.

- `GET /workspaces?state=active|completed|rejected` — list compact workspace summaries.
- `GET /workspaces/{state}/{task_id}` — review summary including `PLAN.json` / `POLICY_DECISION.json` (if present).
- `GET /workspaces/{state}/{task_id}/files/{filename}` — read one known standard workspace file (e.g. `RESULT.md`).

### Open WebUI integration (proposal-only)
This repo includes a simple wrapper script that **proposes plans only** (no approval, no execution).
Approval and execution remain separate gateway steps (`/plans/{plan_id}/approve`, `/plans/{plan_id}/execute`).

- Wrapper: `integrations/openwebui/mini_jarvis_plan_propose.py`
- Environment variables:
  - `MINI_JARVIS_BASE_URL` (default `http://127.0.0.1:8000`)
  - `MINI_JARVIS_API_KEY` (required; same value as gateway `GATEWAY_API_KEY`)
  - `MINI_JARVIS_AGENT` (default `project_maintainer_agent`)

### Open WebUI integration (review/approve/execute wrapper)
Separate wrapper for reviewing an existing plan and explicitly calling approval/execution endpoints.
Proposal, approval, and execution are intentionally separate steps.

- Wrapper: `integrations/openwebui/mini_jarvis_plan_review.py`
- Commands:
  - `show <plan_id>`
  - `approve <plan_id> --confirm`
  - `reject <plan_id> --confirm`
  - `execute <plan_id> --confirm`

---

## Security invariants

- Every route except **`/health`** requires a valid **`X-API-Key`** header matching `GATEWAY_API_KEY`.
- The classifier is constrained to an **allowlist of routing tokens**; free-form model output is not executed as code or routing.
- Tools run only if they appear in the registry with **`installed`** status; arguments are checked against the registry **`input_schema`** before the sandbox runs.
- **Tool execution** goes through **`sandbox.run()` → `sandbox_worker`** only; the gateway does not call tool coroutines directly on the ingest path.
- **`http_allowlist`** restricts tool HTTP destinations to the configured service base URLs.
- Sensitive or multimodal raw payloads are not forwarded blindly to LLMs per existing ingestion and routing policy (see code comments in `ingestion.py` / routing paths).

---

## Project checkpoint docs

- `docs/CURRENT_STATE.md`
- `docs/ARCHITECTURE_INVARIANTS.md`

## Extending tools and routing

- **New built-in tool**: implement in `tools.py`, register in `_TOOL_FUNCS`, seed or lifecycle through `registry`, extend `_INTENT_MAP` as needed, keep httpx calls behind `http_allowlist` checks.
- **New routing target**: update `models.py`, `classification.py`, and `dispatch.py` together.
- **Agent personas**: extend under `agents/<agent_id>/`; wire-up in application code is a separate phase.
