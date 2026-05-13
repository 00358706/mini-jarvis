# Authority and evidence model (design)

**Status:** Design only. **No runtime behavior in mini-jarvis is defined or changed by this document** until implemented on explicit follow-up branches. This branch (`authority-files-and-slim-evidence`) is documentation only.

## Purpose

Describe a cleaner long-term split between:

1. **Durable authority/config** — files and runtime state that define what is allowed, denied, approval-gated, and enforceable.
2. **Compact audit records** — small, append-friendly records for routine actions so every operation does not imply a large on-disk workspace.
3. **Full evidence workspaces** — reserved for human review, high risk, failures, generated-tool lifecycle, explicit “save full evidence,” or development when a folder tree is genuinely useful.

The repo today creates many evidence trees under `data/workspaces/`, `data/automation_lab/`, `data/tool_builds/`, dry-run paths, and similar areas. That was appropriate while proving safety. Long-term, **routine** paths should default to **slim audit** output; **full folders** remain the exception, not the default.

## Problem being solved

Without a shared vocabulary:

- Review folders are mistaken for permission to act.
- Large workspaces accumulate without a retention story.
- Triggers (schedules, adapters) risk being treated as if they carried execution authority.

This model names categories so future branches can align storage, schemas, and UX without re-litigating principles each time.

## Authority vs evidence (non-negotiables)

- **Gateway remains authority** for validation, orchestration of plan/policy/approval flows, and what the system accepts as executable intent.
- **Registry, policy, approval, and sandbox remain enforcement** — a row in a JSON file or a folder on disk does not replace them.
- **Workspaces are evidence**, not authority. They mirror or explain state for humans and auditors; they do not approve or execute.
- **Agents are configuration/context**, not execution authority. They constrain proposals and framing; they do not run tools or bypass the gateway.
- **Schedules and input/device adapters are triggers**, not authority. They may enqueue proposals or surface context; they must not approve plans, install tools, or execute outside normal enforcement.
- **Generated tool artifacts** (Automation Lab, tool build, candidate, install review, registry metadata append, dry-run) are **review evidence** until a human-driven install path runs and, separately, any **explicit dispatch wiring** exists. **Install is not execution approval.**

## File categories

### 1. Authority / config (durable, human-reviewable)

These describe **what is allowed**, **what is denied**, **what requires approval**, **what counts as authority**, and **what triggers may do** (proposal-only vs execution paths). Examples of *classes* of durable inputs (exact paths evolve with the product):

- Agent policy files (allowlists, tool constraints, persona boundaries).
- Registry metadata (including generated **metadata-only** installs where applicable).
- Capability allow/deny rules and overlap hints.
- Risk tiers and approval requirements (when the policy/risk model exists).
- Routine definitions (per `docs/ROUTINE_CONTRACT.md` — definitions, not execution).
- Service/network boundaries and environment contracts (names and scopes, not secrets in-repo).

**Principle:** Changing these should be deliberate, reviewable, and versionable. They are not “logs.”

### 2. Compact audit records (routine default, long term)

**Target future shape:** append-only or small per-action records (e.g. JSON lines) that answer, without a full workspace:

- What was requested?
- What classification / policy decision applied?
- Whether approval existed and what scope it covered?
- What executed (tool names, args summary, outcome), with pointers to deeper evidence if any?

**Not** a full folder per low-risk routine action by default.

### 3. Temporary / full workspaces (exceptions)

Use **full folder trees** when at least one of:

- **Pending human approval** — rich context for reviewers.
- **High-risk actions** — extra evidence density is warranted.
- **Generated-tool lifecycle** — proposal, build, static review, install review, metadata install evidence, dry-run (see backlog roadmap).
- **Failed execution or debugging** — reproducibility and forensics.
- **Explicit “save full evidence” mode** — operator-chosen retention.
- **Development / tests** — when tests intentionally materialize trees; tests should **clean up** and restore durable files (see §5).

### 4. Archives / compaction (policy, not silent deletion)

- Completed/rejected workspaces and bulky evidence may be **archived or compacted later** only with **explicit human confirmation** and clear rules.
- Preserve **summaries**, **hashes**, **final decisions**, and **pointers** into compact audit streams where possible.
- **Never silently delete** active, high-risk, or legally sensitive evidence.

### 5. Test artifacts

- Tests that write under `data/` should use **`try` / `finally`**, remove created trees, and **restore** any durable file they touch **byte-for-byte** when applicable.
- Prefer **predictable prefixes** or ids so stray dirs are easy to spot and delete manually if a test aborts mid-run.

### 6. Runtime future (explicitly out of scope for this doc-only branch)

Future implementation may include:

- **Slim-workspace mode** — avoid creating a full workspace tree for low-risk routine actions when policy allows.
- **Retention service** — compact/archive old evidence per §4.
- **Structured action evidence** — replace many per-action folders with compact records aligned with `docs/ACTION_EVIDENCE_SCHEMA.md` when that schema is adopted.
- **Routine/scheduling runtime** — schedules fire **proposals** or **triggers**; they do not become authority (see `docs/ROUTINE_CONTRACT.md`).

None of the above is implemented by this document.

## Generated-tool lifecycle (exception class)

Generated-tool flows intentionally produce **rich, separable evidence** under Automation Lab and tool-build paths. That remains **review and packaging**, distinct from:

- Registry **execution truth** (`status=installed` and dispatch where wired).
- **Sandbox execution** of approved plans.

Metadata install and dry-run remain **non-executing** evidence unless and until dispatch and normal execution gates exist.

## Suggested future branch sequence

Order may change when implementation starts; dependencies should be respected.

1. **`workspace-storage-report`** — read-only size/candidate reporting (no mutation).
2. **`authority-evidence-config-schema`** — schemas/docs for durable authority vs audit record fields.
3. **`slim-workspace-mode`** — optional runtime path: compact records by default where policy allows.
4. **`workspace-archive-candidates`** — identify archivable trees; still no silent delete.
5. **`workspace-compact-archive`** — explicit confirmation workflows for archive/compact.
6. **`routine-proposal-runtime`** — routines create proposal/review artifacts only.
7. **`scheduled-routine-proposal`** — scheduler as trigger into proposal lane.
8. **`scoped-readonly-scheduled-execution`** — if ever allowed: narrow, policy-bound execution with full audit; not a shortcut around approval.

## Related docs

- `docs/ACTION_EVIDENCE_SCHEMA.md` — structured action evidence proposal.
- `docs/ROUTINE_CONTRACT.md` — routines: trigger vs authority.
- `docs/IO_ADAPTER_CONTRACT.md` — adapters as clients/triggers.
- `docs/EXECUTION_AUTHORIZATION.md` — human authorization of reviewed execution.
- `docs/ARCHITECTURE_INVARIANTS.md` — system-wide invariants.
- `docs/CURRENT_STATE.md` — what is implemented today.
