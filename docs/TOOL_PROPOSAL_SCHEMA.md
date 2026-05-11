# TOOL_PROPOSAL_SCHEMA (docs-only)

This document is a **docs-only tool proposal schema contract** for Mini-Jarvis. It defines the **shape and review rules** for artifacts that describe a **new or materially changed tool** before any registry mutation or execution exists.

**This document does not change runtime behavior.** It does not change `/ingest`, add generated tool execution, automatic tool registration, automatic registry installation, model-driven tool installation, endpoints, or MCP tools.

**Align with:** `docs/ARCHITECTURE_INVARIANTS.md`, `docs/CAPABILITY_REGISTRY_SCHEMA.md`, `docs/ROUTINE_CONTRACT.md`, `docs/EXECUTION_AUTHORIZATION.md`, `docs/ACTION_EVIDENCE_SCHEMA.md`.

---

## Purpose

- **Human review first**: package everything a reviewer needs to decide whether to implement, change scope, reject as duplicate, defer, or refuse on risk—without treating the proposal as executable or installable.
- **Bridge capability gaps**: when `docs/CAPABILITY_REGISTRY_SCHEMA.md` lookup yields `propose_new` (or a human overrides `reject_duplicate` with documented rationale), a tool proposal is the **structured** carrier for that intent.
- **Audit trail**: bind proposals to capability ids, lookup outcomes, and rationale so future evidence (`docs/ACTION_EVIDENCE_SCHEMA.md`) can reference **what was considered** and **why a new tool was justified**.

Tool proposals are **review artifacts only**. They are **not** registry entries, **not** execution permission, and **not** authority.

---

## Core invariant

**Gateway remains the authority.** **Registry remains the source of truth for installed tools.** A tool proposal—whether authored by a model or a human—remains **proposal, not authority** until a **separate, explicit** human-driven lifecycle results in an `installed` registry entry and normal policy/schema/sandbox paths apply.

**Model output remains proposal, not authority.** Filling this schema from an LLM does not relax policy, authorization, schema validation, or sandbox execution requirements.

**Approval for implementation is not approval for execution.** After manual implementation and install, registry `status=installed` plus the real registry `input_schema` remain the only execution truth, and every execution still goes through gateway policy, authorization, schema validation, and sandbox execution.

---

## When a tool proposal is allowed

A compliant **new-tool** proposal (primary outcome `propose_new` or equivalent human-initiated path) is **in scope for this schema** only when **all** of the following hold:

1. **Capability lookup performed**: documented results per `docs/CAPABILITY_REGISTRY_SCHEMA.md` (candidates, primary outcome, and notes). Lookup may be manual in early phases; the **artifact must still record** what was considered.
2. **Insufficient existing tools**: explicit narrative (or structured fields below) explaining why **`reuse_existing`**, **`extend_existing`**, and **`compose_existing`** are insufficient—or why **`reject_duplicate`** is overridden with human-visible rationale when proposing anyway.
3. **No execution or install from artifact**: the proposal must not imply automatic registration, model-driven installation, or execution; implementation is **out of band** until registry and gateway rules say otherwise.
4. **Routine alignment (when applicable)**: if the proposal exists because of a routine’s `missing_capability_behavior`, reference `routine_id` / `capability_id` as context only—**not** as approval.

Proposals that are **only** “rename existing tool” or “cosmetic doc for installed tool” should use change-management outside this schema or clearly mark scope as **metadata-only** (still not auto-applied).

---

## Required fields (minimum viable proposal)

Storage format (JSON in workspace, wiki page, DB row) is **TBD**. Every compliant tool proposal must include:

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `schema_version` | string | yes | e.g. `tool-proposal.v1`. |
| `proposal_id` | string | yes | Stable unique id for this proposal artifact. |
| `title` | string | yes | Short human-facing title. |
| `proposed_tool_name` | string | yes | Suggested registry `tool_name` (must not collide with `installed` without explicit migration story). |
| `status` | enum | yes | Proposal lifecycle: `draft` \| `submitted` \| `in_review` \| `decided` (see **Proposal outcomes** for decision). |
| `submitted_by` | string | yes | Human or role id; if model-generated, still attribute submitting human/process. |
| `submitted_at` | string | yes | ISO 8601. |
| `capability_lookup` | object | yes | See **Capability lookup requirements**. |
| `insufficiency_explanation` | string | yes | Why reuse/extension/composition does not suffice (or override rationale). |
| `proposed_tool` | object | yes | See **Proposed tool metadata**. |
| `risk` | object | yes | See **Side effects and risk fields**. |
| `implementation_plan` | object | yes | See **Implementation plan fields**. |
| `test_plan` | object | yes | See **Test plan fields**. |
| `review` | object | yes | See **Review requirements** (may be partially empty until review starts). |

---

## Capability lookup requirements

The `capability_lookup` object must contain at least:

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `stated_need` | string | yes | Plain-language or structured need statement. |
| `capability_ids` | array of string | yes | Ids from routine or catalog (`docs/ROUTINE_CONTRACT.md`, capability catalog). |
| `primary_outcome` | enum | yes | One of `reuse_existing` \| `extend_existing` \| `compose_existing` \| `propose_new` \| `reject_duplicate` per `docs/CAPABILITY_REGISTRY_SCHEMA.md`. |
| `candidate_tools` | array of object | yes | Each: `tool_name`, `match_notes` (why considered / ruled out). May be empty only if catalog truly empty and documented. |
| `lookup_notes` | string | optional | Ambiguity, partial overlap, policy hints. |
| `performed_at` | string | yes | ISO 8601 (or “manual review session” reference). |

If `primary_outcome` is not `propose_new`, the artifact should normally be a **change request** against an existing tool or plan, not a net-new tool proposal—unless a human explicitly files this schema with `primary_outcome` overridden and `insufficiency_explanation` expanded.

Before setting `primary_outcome` to `propose_new`, the proposal must record consideration of `reuse_existing`, `extend_existing`, `compose_existing`, and `reject_duplicate`. This can be brief, but it must be visible to reviewers through `candidate_tools`, `lookup_notes`, and/or `insufficiency_explanation`.

---

## Proposed tool metadata

The `proposed_tool` object should include:

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `summary` | string | yes | One paragraph what the tool does. |
| `purpose` | string | yes | When operators should use it. |
| `inputs` | object | yes | Human description; future `input_schema` draft may be attached as nested `draft_json_schema` (still proposal until registry adopts). |
| `outputs` | object | yes | Return shape, files written, audit expectations (review-level). |
| `registry_integration` | string | yes | How it maps to existing registry patterns (module path, worker contract)—design only. |
| `agent_allowlist_impact` | string | optional | Which `agents/*/tools.yaml` entries might need updates after install. |

This metadata **does not** replace gateway `input_schema` or registry `installed` checks at execution time.

---

## Side effects and risk fields

The `risk` object should align with routine/risk vocabulary where possible:

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `risk_level` | enum | yes | `level_0` … `level_4`. |
| `side_effects` | array of enum | yes | Same family as `docs/CAPABILITY_REGISTRY_SCHEMA.md` (e.g. `none`, `filesystem_read`, …). |
| `network_access` | enum | yes | `none` \| `local` \| `tailnet` \| `internet`. |
| `destructive` | boolean | yes | Irreversible or hard-to-reverse mutations. |
| `costly` | boolean | yes | Money, quota, or heavy compute. |
| `sandbox_expectations` | string | yes | Timeout, env, secrets handling, subprocess boundaries—must respect sandbox-only execution path (`docs/ARCHITECTURE_INVARIANTS.md`). |

---

## Implementation plan fields

The `implementation_plan` object must include:

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `phases` | array of object | yes | Each: `name`, `description`, `dependencies` (optional). |
| `rollback` | string | yes | How to disable or revert if the tool misbehaves post-install. |
| `security_notes` | string | yes | Trust boundaries, untrusted input, injection surfaces. |

---

## Test plan fields

The `test_plan` object must include:

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `unit_tests` | string | yes | Scope or “N/A” with justification (discouraged for non-trivial tools). |
| `integration_tests` | string | yes | Against sandbox worker, mock services, or staging. |
| `manual_checklist` | array of string | yes | Human verification steps before marking registry `installed`. |

---

## Review requirements

The `review` object must support:

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `reviewers_required` | integer | yes | Minimum human reviewers (typically ≥ 1). |
| `policy_consultation_required` | boolean | yes | If true, policy owner sign-off recorded in notes. |
| `decision` | enum or null | yes after decision | One of **Proposal outcomes** below; `null` while pending. |
| `decided_at` | string | optional | ISO 8601 when `decision` set. |
| `decision_notes` | string | optional | Conditions, follow-ups, links to PRs/commits (out of scope for this doc to mandate format). |

---

## Proposal outcomes

After review, `review.decision` must be one of:

| Outcome | Meaning |
|---------|--------|
| **`approve_for_implementation`** | Proceed with implementation and later **manual** registry install steps; still no execution until registry `status=installed` and the normal plan approval/authorization path. |
| **`request_changes`** | Proposal needs revision; no registry change from this artifact. |
| **`reject_duplicate`** | Redundant with existing tools/metadata; do not implement. |
| **`reject_too_risky`** | Rejected on risk, scope, or policy fit. |
| **`defer`** | Parked; may be reopened with new `proposal_id` or version field (TBD). |

These outcomes affect **process only**; they do not bypass `docs/EXECUTION_AUTHORIZATION.md` for any execution.

---

## Non-goals

- No automatic creation or mutation of registry rows from proposal files.
- No model-driven or agent-driven installation or “self-approved” tools.
- No execution of proposed tool code from the proposal artifact.
- No replacement for plan-level approval or workspace evidence authority model.
- No new endpoints or MCP tools introduced by this contract alone.

---

## Relationship to other documents

| Document | Relationship |
|----------|----------------|
| `docs/CAPABILITY_REGISTRY_SCHEMA.md` | Lookup outcomes and candidate tools **must** be recorded before a net-new proposal; advisory metadata informs duplication risk. |
| `docs/ROUTINE_CONTRACT.md` | `required_capabilities` and `missing_capability_behavior` may **trigger** proposal work; routines do not authorize install or execution. |
| `docs/EXECUTION_AUTHORIZATION.md` | Executing **plans** that use a newly installed tool still requires normal authorization modes; proposals do not grant `execute`. |
| `docs/ACTION_EVIDENCE_SCHEMA.md` | Future evidence records may reference `proposal_id`, `capability_ids`, and `primary_outcome` for auditability. |
| `docs/ARCHITECTURE_INVARIANTS.md` | Non-negotiable gateway, registry, policy, approval, sandbox boundaries apply before and after a tool is implemented. |

---

## Future implementation rules

- Store or render tool proposals only in a **future branch** with explicit approval (e.g. workspace templates, wiki, or admin UI).
- Any automation that pre-fills this schema from model output must label sources and keep humans in the review loop.
- After implementation, **registry `status=installed`** and **schema** in the real registry remain the only execution truth; update capability metadata per `docs/CAPABILITY_REGISTRY_SCHEMA.md` when the tool ships.
