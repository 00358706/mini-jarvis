## EXECUTION_AUTHORIZATION (docs-only contract)

This document defines a **docs-only execution authorization contract** for Mini‑Jarvis.

It is intended to evolve Mini‑Jarvis from a permanent “two-click” approve/execute UX toward **explicit human authorization of the exact reviewed plan**.

### Non-negotiable authority boundary (unchanged)
- **Gateway remains the authority** for validation, policy evaluation, approval state, registry/schema checks, and execution orchestration.
- **Agents/models/clients are not authorities** and cannot execute tools directly.
- **Sandbox worker remains the only side-effect execution path**.
- Workspace files and wiki pages are **evidence and review state**, not authority.

This document **does not** change runtime behavior, endpoints, or approval/execution logic today.

---

## Terms and entities

- **plan**: a structured `Plan` with `plan_id` and steps.
- **reviewed plan content**: the exact plan representation that a human reviewed (e.g. normalized canonical JSON of `PLAN.json`).
- **policy decision**: deterministic policy evaluation captured as evidence (e.g. `POLICY_DECISION.json`).
- **authorization**: a human action that grants the gateway permission to run a specific plan (or a bounded class of plans) under a specific mode.

### Plan immutability for authorization

**Authorization is invalid if the reviewed plan changes.**

Clients must treat any change in the reviewed plan content as requiring a new review and a new authorization.

---

## The four authorization modes (must be distinguishable)

### 1) Approve for later

Purpose:
- Mark a pending plan as approved so it is eligible for later execution.

Properties:
- No tool execution occurs.
- Approval is **not** an execution authorization by itself (it is a prerequisite state transition).

### 2) Execute an already approved plan

Purpose:
- Execute a plan that is already in approved state.

Properties:
- Must still require an explicit human action.
- Must re-check policy + registry/schema at execution time.
- Must run through sandbox worker.

### 3) Authorize & Run this exact reviewed plan

Purpose:
- After reviewing the compact summary and/or full plan evidence, the human performs a single explicit action:
  - **Authorize & Run** the *exact reviewed plan*.

Important wording:
- “Authorize & Run” is **not auto-execute** if it is a **single explicit human action** performed **after review**.
- It is still separate from proposal creation and remains an explicit, user-visible authorization step.

Required properties:
- Authorization must bind to the **reviewed plan content** via a `plan_hash` (or equivalent reviewed-content reference).
- Authorization must be invalidated if the reviewed plan changes.
- Execution must re-check policy + registry/schema at execution time and run only via sandbox worker.

### 4) Future scoped routine / capability grants (future-only)

Purpose:
- Allow a human to grant a bounded capability for routine actions (e.g. “allow level_0 read-only tools for 30 minutes”).

Properties:
- **Future-only**: must be designed explicitly and approved separately.
- Must not become a hidden auto-execute channel.
- Must be revocable, expiring, auditable, and constrained by risk/capability scope.

---

## Authorization record (contract fields)

An authorization is represented by an **Authorization Record** (conceptual shape; storage TBD).

### Required fields
- **`authorization_id`**: unique identifier for this authorization event/record.
- **`plan_id`**: the plan identifier being authorized (or the plan set identifier for future scoped grants).
- **`plan_hash`** *(or reviewed content reference)*:
  - a cryptographic hash of the canonical reviewed plan content, OR
  - an immutable reference to reviewed content (e.g. content-addressed store id).
- **`authorized_by`**: identity of the human/operator who authorized (local operator identity model TBD).
- **`authorization_mode`**: one of:
  - `approve_for_later`
  - `execute_approved`
  - `authorize_and_run_exact`
  - `scoped_grant` (future-only)
- **`authorized_action`**: explicit action allowed, e.g.:
  - `approve`
  - `execute`
  - `authorize_and_execute`
- **`policy_decision_ref`**: reference to the policy decision used during review (e.g. workspace policy JSON path or audit id).
- **`registry_schema_recheck_required`**: must be `true` for any execution path.
- **`sandbox_execution_required`**: must be `true` for any side-effect execution.

### Lifecycle / control fields
- **`created_at`**: ISO 8601 timestamp.
- **`expires_at`**: ISO 8601 timestamp (required for `authorize_and_run_exact` and future scoped grants; optional for approve-for-later).
- **`revoked_at`**: ISO 8601 timestamp or null.
- **`revocation_reason`**: string or null.

### Evidence / audit references
- **`workspace_ref`**: reference to workspace evidence (e.g. `data/workspaces/active/<plan_id>/` or completed path).
- **`audit_refs`**: references to audit events (proposal created, approved, executed).
- **`execution_log_ref`**: reference to execution log evidence (e.g. `EXECUTION_LOG.jsonl`) if executed.
- **`result_ref`**: reference to result evidence (`RESULT.md`) if executed.

---

## Execution requirements (must be stated explicitly)

Any execution (modes 2 and 3, and future grants in mode 4) must:
- **Re-check policy at execution time** (policy can change; installed tools can change).
- **Re-check registry + schema at execution time** (tool must still be `installed`; args must still validate).
- Execute only through **gateway-controlled sandbox worker**.
- Be **auditable**, producing durable evidence (audit entry + workspace artifacts).

---

## Invalidation rules

Authorization must be treated as **invalid** if any of these change between review and execution:
- The reviewed plan content (plan hash mismatch).
- The policy decision changes from allowed → not allowed at execution time.
- The referenced tool is no longer installed or its schema validation fails.
- Authorization is expired or revoked.

---

## UI/client requirements (summary)

UI clients must:
- Present **clear separation** between:
  - propose
  - review
  - approve
  - execute
  - authorize & run exact (explicit review-then-authorize action)
- Show which mode the human is performing.
- Display the **reviewed plan reference** (plan_id + plan_hash or reviewed-content ref).
- Make revocation/expiry visible when applicable.

UI clients must never:
- execute tools directly
- bypass policy/registry/approval/sandbox checks
- store secrets in repo or silently authorize execution

