# CAPABILITY_REGISTRY_SCHEMA (docs-only)

This document is a **docs-only capability registry schema contract** for Mini-Jarvis. It describes **advisory capability metadata** that may eventually attach to or sit beside **installed tool** registry entries so planners, routines, and humans can reason about **what tools do** and **how needs overlap**—without changing who may execute what.

**This document does not change runtime behavior.** It does not change `/ingest`, add generated tool execution, automatic tool registration, automatic registry installation, model-driven tool installation, new endpoints, or MCP tools.

**Align with:** `docs/ARCHITECTURE_INVARIANTS.md`, `docs/ROUTINE_CONTRACT.md`, `docs/EXECUTION_AUTHORIZATION.md`, `docs/ACTION_EVIDENCE_SCHEMA.md`.

---

## Purpose of capability metadata

- **Discovery and deduplication**: help humans and future planners decide whether an existing **installed** tool already satisfies a need, whether multiple tools should be **composed**, or whether a **new tool proposal** is justified.
- **Routine alignment**: give stable identifiers and descriptions that `docs/ROUTINE_CONTRACT.md` `required_capabilities[].capability_id` can reference without implying those capabilities are installed or executable.
- **Risk and review context**: surface purpose, side effects, and composability for policy and human review (metadata informs; it does **not** grant execution).

Capability metadata is **advisory only** in this branch: it must not bypass or replace **gateway** validation, **policy**, **human authorization** where required, **registry/schema** checks at execution time, or **sandbox** execution.

---

## What a capability is

- A **capability** is an **abstract, named description of an effect or information need** (for example “read-only listing of files under a workspace root” or “query download client queue status”).
- A **tool** is a **concrete registry entry** with an implementation, `input_schema`, execution wiring, and `status` (only `installed` tools may execute per `docs/ARCHITECTURE_INVARIANTS.md`).
- **One capability** may be satisfied by **zero, one, or many** installed tools over time; **one tool** may **implement** multiple capabilities or overlap partially with others.

Model output that names or sketches capabilities or tools remains **proposal, not authority** (`docs/ARCHITECTURE_INVARIANTS.md`).

---

## Target registry metadata fields

Storage shape (YAML/JSON columns, sidecar files, or DB) is **TBD**. The contract below is the **target** for capability-related metadata associated with the **tool registry** (either embedded on each tool record or linked by `tool_name` / `tool_id`).

### Tool capability advertisement (per installed or catalogued tool)

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `tool_name` | string | yes | Registry tool name; must match execution lookup. |
| `tool_version` | string | optional | Version string for review/diff (semver or opaque). |
| `capability_ids` | array of string | yes | Stable ids this tool is claimed to satisfy (subset semantics TBD per tool). |
| `summary` | string | yes | Short human-readable what-it-does. |
| `purpose` | string | yes | Intent / when to use; advisory for planners. |
| `inputs_summary` | object or string | optional | Review-safe description of expected inputs (not a substitute for `input_schema`). |
| `outputs_summary` | object or string | optional | Review-safe description of outputs and artifacts. |
| `side_effects` | array of enum | yes | e.g. `none`, `filesystem_read`, `filesystem_write`, `network_read`, `network_write`, `external_mutation` (enum extensible). |
| `risk_level` | enum | yes | `level_0` … `level_4` (definitions shared with `docs/ROUTINE_CONTRACT.md` / backlog). |
| `network_access` | enum | optional | `none` \| `local` \| `tailnet` \| `internet` (advisory; enforcement remains policy + implementation). |
| `composes_with` | array of string | optional | Other `tool_name` values often used in sequence; **not** an execution graph. |
| `supersedes_tool_names` | array of string | optional | Deprecated tool names this entry replaces, if any. |
| `tags` | array of string | optional | Faceted search: domain, modality, data class, etc. |
| `overlap_notes` | string | optional | Human notes on partial overlap with other tools/capabilities. |
| `metadata_version` | string | yes | Version of this capability-metadata schema, e.g. `capability-registry.v1`. |
| `last_reviewed_at` | string | optional | ISO 8601; human/process audit hint only. |

### Standalone capability definition (optional catalog)

For routines and planners, a **capability catalog** entry (same or linked store) may exist:

| Field | Type | Required | Purpose |
|-------|------|--------|--------|
| `capability_id` | string | yes | Stable id; referenced by routines and tool `capability_ids`. |
| `title` | string | yes | Short label. |
| `description` | string | yes | What need is satisfied. |
| `acceptance_criteria` | string | optional | How to judge satisfaction (human-oriented). |
| `related_capability_ids` | array of string | optional | Broader/narrower/alternate ids for overlap reasoning. |
| `status` | enum | optional | `draft` \| `active` \| `deprecated` (catalog lifecycle, not tool `installed`). |

---

## Required minimum fields

Any **compliant** capability-metadata record used for lookup in a future implementation must include at least:

| Context | Minimum fields |
|---------|------------------|
| **Per tool** | `tool_name`, `capability_ids` (non-empty), `summary`, `purpose`, `side_effects`, `risk_level`, `metadata_version` |
| **Per catalog capability** | `capability_id`, `title`, `description` |

All other fields remain optional but recommended for deduplication and review quality.

---

## Capability lookup outcomes

When a future process matches a **stated need** (e.g. routine `required_capabilities` or a planner question) against **registry capability metadata**, it should classify the result into exactly one **primary** advisory outcome:

| Outcome | Meaning |
|---------|--------|
| **`reuse_existing`** | One installed tool’s metadata clearly satisfies the need; prefer referencing that tool in proposals. |
| **`extend_existing`** | An installed tool almost satisfies the need; a small **schema** or **implementation** extension (still via normal tool lifecycle) may suffice—**not** silent mutation of registry. |
| **`compose_existing`** | Multiple installed tools together satisfy the need; proposals should sequence or combine steps (subject to policy). |
| **`propose_new`** | No satisfactory installed mapping; a **new tool** may be proposed via human-reviewed lifecycle (`docs/ROUTINE_CONTRACT.md` missing capability behavior remains proposal-only). |
| **`reject_duplicate`** | The need is already satisfied by an existing tool (or composition) and a **new** tool would be redundant or harmful; **do not** propose a parallel tool without explicit human override. |

These outcomes are **advisory**: the gateway still enforces **installed-only** execution, policy, authorization, and sandbox rules.

---

## Duplicate and overlap rules

- **Duplicate capability_id on one tool**: invalid metadata; a tool record must not list the same `capability_id` more than once (normalize before treating metadata as trusted).
- **Multiple tools claiming the same `capability_id`**: allowed; lookup must list **candidates** and prefer disambiguation via `summary`, `risk_level`, `tags`, and policy—not automatic “winner” execution.
- **Semantic overlap without shared `capability_id`**: `overlap_notes` and `related_capability_ids` should be used; lookup may return **`compose_existing`** or **`reject_duplicate`** with human-visible rationale.
- **`reject_duplicate`**: use when overlap is **high** and marginal value of a new tool is **low**, or when policy forbids redundant network or mutation surface—still a **human-visible** classification, not a silent block unless policy says so.
- **Registry remains source of truth for installed tools**: capability metadata must not invent `installed` status; **`status=installed`** stays on the tool registry authority path.

---

## Relationship to routines

- `docs/ROUTINE_CONTRACT.md` defines `required_capabilities[]` with `capability_id`, `purpose`, and `required`.
- Routines **declare needs**; capability metadata and lookup outcomes **inform** proposals and `missing_capability_behavior` (e.g. `propose_tool` vs `stop`).
- A routine **must not** treat advisory lookup as execution permission; **allowed_tools** in a routine still only **name** tools—execution requires the existing gateway path.

---

## Relationship to future tool proposals

- A **`propose_new`** outcome feeds a **future** structured tool proposal document (see backlog: `tool-proposal-schema` branch)—schemas for proposal artifacts, review checklist, and install steps are **out of scope** for this file.
- Until that exists, proposals remain human-reviewed artifacts; **no** model-driven installation or automatic registration.
- Generated or model-suggested tools remain **proposal-only** until reviewed, tested, approved, and **manually** reflected in the registry per invariants.

---

## Non-goals

- No automatic registration or installation of tools from metadata or model output.
- No execution or policy bypass based on “capability match score.”
- No requirement that every tool immediately populate full optional metadata (minimum fields suffice for early adoption).
- No merging of capability catalog and **approval state**; approvals stay in the plan/authorization model (`docs/EXECUTION_AUTHORIZATION.md`).
- No replacement for `input_schema` validation at execution time.

---

## Future implementation rules

- Implement capability metadata storage and lookup only in a **future branch** with explicit approval.
- Any automation must keep **gateway** as authority; metadata readers are **clients** of registry truth.
- Execution paths must continue to re-check **policy**, **registry/schema**, **authorization**, and **sandbox** per `docs/ARCHITECTURE_INVARIANTS.md` and `docs/ACTION_EVIDENCE_SCHEMA.md`.
- When emitting evidence, prefer referencing **which capability_ids** and **which lookup outcome** informed a proposal, without treating that record as permission to execute.
