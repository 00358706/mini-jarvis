# ROUTINE_CONTRACT (docs-only)

This document is a **docs-only routine contract** for Mini-Jarvis. It defines what **routines** are, how they relate to triggers and capabilities, and what evidence and lifecycle states mean **before** any routine runtime, scheduler, or new endpoints exist.

**This document does not change runtime behavior.** It does not add scheduler runtime, generated tool execution, automatic registry installation, apply-patch, `/ingest` changes, endpoints, UI behavior, or MCP tools.

**Evidence:** this file path in the repo; align with `docs/ARCHITECTURE_INVARIANTS.md`, `docs/EXECUTION_AUTHORIZATION.md`, `docs/IO_ADAPTER_CONTRACT.md`, and `docs/ACTION_EVIDENCE_SCHEMA.md`.

---

## What routines are

- **Routines** are **repeatable workflow definitions**: human-readable and machine-readable descriptions of a goal, allowed context, triggers, risk, output, failure behavior, and what must be true before a plan may be proposed or executed.
- A routine describes **how** something may be invoked or proposed again; it does **not** perform work by itself.
- Routines are intended to compose with the existing gateway path: **registry** (installed tools), **policy**, **human authorization** (see `docs/EXECUTION_AUTHORIZATION.md`), **schema validation**, and **sandbox execution** only.

---

## What routines are not

- **Not agents**: agents remain folders under `agents/<id>/`; routines are not agent processes or services.
- **Not tools**: routines do not implement tool behavior or call the sandbox.
- **Not services**: routines are not daemons, schedulers, or network authorities.
- **Not execution authorities**: a routine definition file or record does **not** approve, authorize, or execute anything.
- **Not triggers with authority**: a schedule or adapter firing is **only** a trigger to create context or request a proposal; it is **not** permission to execute.

---

## Core invariant

**Gateway remains the authority.** Routine definitions, schedules, input adapters, model output, and workspace files are **never** substitutes for gateway validation, policy, registry/schema checks, explicit human authorization where required, and sandbox-side-effect execution.

- **Schedule is trigger, not authority.**
- **Input adapters are clients, not authority** (see `docs/IO_ADAPTER_CONTRACT.md`).
- **Model output is proposal, not authority.**
- **Registry, policy, authorization, schema validation, and sandbox execution remain the enforcement path** for any side effect.

---

## Routine definition fields (target schema)

A **future** routine definition should include the following. Field names and enums are contractual targets; storage format (YAML/JSON/SQL) is TBD.

### Identity and metadata

| Field | Type | Notes |
|-------|------|--------|
| `routine_id` | string | Stable identifier, e.g. `daily_project_status`. |
| `name` | string | Human-facing name. |
| `version` | string | Definition version string (semver or opaque). |
| `description` | string | What the routine is for. |

### Lifecycle (definition state, not plan approval)

| Field | Type | Notes |
|-------|------|--------|
| `status` | enum | `draft` \| `proposed` \| `approved` \| `enabled` \| `disabled` \| `retired`. Describes the **routine definition** lifecycle, not a single plan’s pending/approved/executed state. |

### Ownership and audit

| Field | Type | Notes |
|-------|------|--------|
| `owner` | string | Accountable owner (human or org id; format TBD). |
| `created_by` | string | Who created the definition. |
| `created_at` | string | ISO 8601. |
| `updated_at` | string | ISO 8601. |

### Trigger modes

| Field | Type | Notes |
|-------|------|--------|
| `trigger_modes` | array of enum | Allowed triggers for **starting** routine-related work (proposal path). Values: `manual`, `scheduled`, `input_adapter`, `event_adapter`. |

**Semantics**

- **`manual`**: explicit human or client action (still a client; not authority).
- **`scheduled`**: time-based trigger only; **no scheduler runtime is implied by this contract**. When a scheduler exists, it must only enqueue or request gateway-safe flows; it must not approve or execute.
- **`input_adapter`**: normalized ingress per `docs/IO_ADAPTER_CONTRACT.md`; adapter provides context, not authorization.
- **`event_adapter`**: future event-driven trigger (e.g. device/event feed); same rules as input adapter—**trigger, not authority**.

### Schedule (optional; descriptive only until scheduler exists)

| Field | Type | Notes |
|-------|------|--------|
| `schedule.enabled` | boolean | Whether a future scheduler should consider this routine. |
| `schedule.expression_type` | enum | `none` \| `cron` \| `interval` \| `calendar`. |
| `schedule.expression` | string or null | Opaque expression; interpreted only by future scheduler code under gateway rules. |
| `schedule.timezone` | string or null | IANA timezone when relevant. |

### Input contract

| Field | Type | Notes |
|-------|------|--------|
| `input_contract.input_sources` | array of enum | e.g. `user_message`, `workspace`, `file`, `device`, `api`. |
| `input_contract.required_fields` | array | Field names required for a valid run request. |
| `input_contract.optional_fields` | array | Optional fields. |
| `input_contract.untrusted_input_allowed` | boolean | If false, untrusted input must not be accepted without explicit policy/UI rules. |

### Capabilities and tools

| Field | Type | Notes |
|-------|------|--------|
| `required_capabilities[]` | objects | Each: `capability_id` (string), `purpose` (string), `required` (boolean). Describes **needs**, not installed tools. |
| `allowed_agents[]` | objects | Each: `agent_id` (string). Preferences for proposal context; **not** execution grants. |
| `allowed_tools[]` | objects | Each: `tool_name` (string). Names that may appear in **proposed** plans; **registry remains source of truth**—only `installed` tools may execute. |

**Capability / tool relationship**

- **Capabilities** are abstract requirements (`required_capabilities`).
- **Tools** are concrete registry entries (`allowed_tools` references names; execution requires `installed` + schema + policy + authorization + sandbox).
- A routine may require capabilities that **do not yet** map to an installed tool; see **Missing capability behavior** below.

### Output contract

| Field | Type | Notes |
|-------|------|--------|
| `output_contract.destinations` | array of enum | e.g. `workspace`, `chat`, `notification`, `file`. |
| `output_contract.format` | enum | `text` \| `markdown` \| `json`. |
| `output_contract.evidence_required` | boolean | If true, runs must produce/attach evidence per **Evidence requirements**. |

### Authorization (routine-level default; per-run must still match `docs/EXECUTION_AUTHORIZATION.md`)

| Field | Type | Notes |
|-------|------|--------|
| `authorization.mode` | enum | `approve_for_later` \| `authorize_and_run_exact_plan` \| `scoped_grant_future`. Maps conceptually to `docs/EXECUTION_AUTHORIZATION.md` (approve for later; authorize & run exact reviewed plan; future scoped grant). **`execute_approved`** is a separate explicit human step when not using combined authorize-and-run. |
| `authorization.requires_human` | boolean | If true, no autonomous approval/execution. |
| `authorization.bind_to_plan_hash` | boolean | If true, any execution must bind to reviewed plan content (e.g. `plan_hash`); invalid if plan changes. |
| `authorization.grant_id` | string or null | Reference to a future scoped grant record, if any. |
| `authorization.expires_at` | string or null | ISO 8601; authorization/grant expiry. |

**Authorization modes (distinction)**

1. **Approve for later** — routine may expect a human to approve a plan for later execution; **no execution** in that step.
2. **Execute an already approved plan** — separate explicit action (not stored as `authorization.mode` on the routine alone; it is the `execute_approved` path in `docs/EXECUTION_AUTHORIZATION.md`).
3. **Authorize & Run this exact reviewed plan** — single explicit human action after review; **not** hidden auto-execute; must bind to reviewed content when `bind_to_plan_hash` is true.
4. **Future scoped routine/capability grants** — `scoped_grant_future` only; bounded, expiring, revocable; must not become auto-execute.

### Risk

| Field | Type | Notes |
|-------|------|--------|
| `risk.level` | enum | `level_0` … `level_4` (see backlog / future risk model). |
| `risk.side_effects` | array | e.g. `none`, or enumerated side-effect classes when defined. |
| `risk.network_access` | enum | `none` \| `local` \| `tailnet` \| `internet`. |
| `risk.destructive` | boolean | |
| `risk.costly` | boolean | |

### Failure policy

| Field | Type | Notes |
|-------|------|--------|
| `failure_policy.stop_on_missing_capability` | boolean | |
| `failure_policy.stop_on_policy_denied` | boolean | |
| `failure_policy.stop_on_schema_error` | boolean | |
| `failure_policy.stop_on_tool_failure` | boolean | |
| `failure_policy.retry_allowed` | boolean | Retries are gateway-controlled; never bypass policy/registry/sandbox. |
| `failure_policy.max_retries` | integer | |

### Evidence (routine expectations; aligns with `docs/ACTION_EVIDENCE_SCHEMA.md`)

| Field | Type | Notes |
|-------|------|--------|
| `evidence.write_request` | boolean | |
| `evidence.write_plan` | boolean | |
| `evidence.write_policy_decision` | boolean | |
| `evidence.write_authorization_record` | boolean | |
| `evidence.write_execution_result` | boolean | |
| `evidence.write_artifacts` | boolean | |

Workspace artifacts remain **evidence**, not authority.

### Missing capability behavior

| Field | Type | Notes |
|-------|------|--------|
| `missing_capability_behavior.action` | enum | `stop` \| `propose_tool` \| `propose_agent` \| `propose_routine_update`. |
| `missing_capability_behavior.generated_tool_execution_allowed` | boolean | **Must be `false`.** Generated tools stay proposal-only until lifecycle review and **manual** install; no automatic registry installation, no generated tool execution. |

---

## Lifecycle states (routine definition)

`draft` → `proposed` → `approved` → `enabled` → (`disabled` | `retired`)

- **`draft`**: not ready for use.
- **`proposed`**: ready for human/gateway review of the definition itself (distinct from plan pending/approval).
- **`approved`**: definition approved for future enablement.
- **`enabled`**: may be selected/triggered subject to triggers and gateway rules.
- **`disabled`**: temporarily off.
- **`retired`**: terminal; must not be used for new runs.

---

## Evidence requirements (summary)

Any routine-invoked flow that can lead to execution must leave an auditable trail consistent with:

- `docs/ACTION_EVIDENCE_SCHEMA.md` (future records),
- workspace mirrors under `data/workspaces/*` (evidence only),
- audit log entries (gateway-owned).

At minimum, evidence flags in `evidence.*` express what a compliant implementation should write when those phases occur.

---

## Examples

### Example: read-only status routine (proposal-first)

```json
{
  "routine_id": "daily_project_status",
  "name": "Daily project status",
  "version": "0.1.0",
  "description": "Summarize repo read-only state for human review.",
  "status": "draft",
  "owner": "local-operator",
  "created_by": "local-operator",
  "created_at": "2026-05-09T12:00:00Z",
  "updated_at": null,
  "trigger_modes": ["manual", "scheduled"],
  "schedule": {
    "enabled": false,
    "expression_type": "none",
    "expression": null,
    "timezone": null
  },
  "input_contract": {
    "input_sources": ["user_message"],
    "required_fields": ["message"],
    "optional_fields": [],
    "untrusted_input_allowed": true
  },
  "required_capabilities": [
    { "capability_id": "repo.read_tree", "purpose": "List files safely", "required": true }
  ],
  "allowed_agents": [{ "agent_id": "project_maintainer_agent" }],
  "allowed_tools": [
    { "tool_name": "list_project_files" },
    { "tool_name": "search_repo" }
  ],
  "output_contract": {
    "destinations": ["workspace", "chat"],
    "format": "markdown",
    "evidence_required": true
  },
  "authorization": {
    "mode": "approve_for_later",
    "requires_human": true,
    "bind_to_plan_hash": true,
    "grant_id": null,
    "expires_at": null
  },
  "risk": {
    "level": "level_0",
    "side_effects": ["none"],
    "network_access": "none",
    "destructive": false,
    "costly": false
  },
  "failure_policy": {
    "stop_on_missing_capability": true,
    "stop_on_policy_denied": true,
    "stop_on_schema_error": true,
    "stop_on_tool_failure": true,
    "retry_allowed": false,
    "max_retries": 0
  },
  "evidence": {
    "write_request": true,
    "write_plan": true,
    "write_policy_decision": true,
    "write_authorization_record": true,
    "write_execution_result": true,
    "write_artifacts": true
  },
  "missing_capability_behavior": {
    "action": "propose_tool",
    "generated_tool_execution_allowed": false
  }
}
```

---

## Non-goals (explicit)

- No embedded scheduler implementation in this contract.
- No automatic approval or automatic execution from routine definition alone.
- No “routine installs tools” or “routine elevates registry” behavior.
- No apply-patch or generated tool execution from routine triggers.
- No using routine files as authority over gateway policy or approval state.

---

## Relationship to other contracts

| Document | Relationship |
|----------|----------------|
| `docs/EXECUTION_AUTHORIZATION.md` | Human authorization modes, `plan_hash` binding, expiry/revocation, and execution re-check rules. |
| `docs/IO_ADAPTER_CONTRACT.md` | Input/event adapters as clients; normalized envelope as context. |
| `docs/ACTION_EVIDENCE_SCHEMA.md` | Future structured evidence for proposals and executions. |
| `docs/ARCHITECTURE_INVARIANTS.md` | Non-negotiable gateway, registry, policy, sandbox boundaries. |

---

## Future implementation rules

- Implement routine runtime only in a future branch with explicit approval.
- Any scheduler must **only** trigger gateway-safe proposal/review flows unless a separate, explicitly approved authorization model exists.
- Routines that reference tools must still respect **installed-only** execution, policy re-check at execution time, and **sandbox worker** as the sole side-effect path.
