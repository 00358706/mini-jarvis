# mini-jarvis Backlog

This file is for deferred ideas and future branch candidates.

Backlog items are **not active implementation instructions** unless the user explicitly selects one.

Before implementing anything here, read:

- `README.md`
- `docs/CURRENT_STATE.md`
- `docs/ARCHITECTURE_INVARIANTS.md`
- `docs/ENVIRONMENT.md`
- `docs/wiki/README.md`

## Current recommended next branch

No single “next branch” is recommended right now. Pick a backlog item explicitly and keep changes small and branch-scoped.

## Near-term backlog

### Tool proposal schema later

Structured tool proposal artifacts should follow `docs/TOOL_PROPOSAL_SCHEMA.md` before any generated-tool, registry lifecycle, or runtime work.

Goal:
Define review-only artifacts for proposed new or materially changed tools after capability lookup.

A tool proposal should describe:
- capability lookup results and candidate tools considered
- why `reuse_existing`, `extend_existing`, `compose_existing`, or `reject_duplicate` is not the selected outcome before `propose_new`
- proposed inputs, outputs, side effects, risk level, and network access
- sandbox expectations, implementation plan, and test plan
- review outcome and decision notes

Rules:
- Tool proposals are review artifacts only.
- Approval for implementation is not approval for execution.
- Registry `status=installed` remains the only execution truth after manual install.
- Registry, policy, authorization, schema validation, and sandbox execution remain the enforcement path.
- Do not change runtime execution behavior.
- Do not change `/ingest`.
- Do not add generated tool execution.
- Do not add automatic tool registration or automatic registry installation.
- Do not add model-driven tool installation.
- Do not add endpoints or MCP tools.

Safe first branch:
- `tool-proposal-schema` adds or refines `docs/TOOL_PROPOSAL_SCHEMA.md`.
- Update `docs/CURRENT_STATE.md` only for a docs-only design checkpoint.
- Do not make backlog "current recommended next branch" wording depend on the active branch.

### Tool candidate generation current

**Implemented (narrow):** `scripts/automation_lab_generate_tool_candidate.ps1` emits template-only review artifacts under `data/tool_builds/<request_id>/` after `scripts/automation_lab_create_tool_build.ps1` (see `docs/CURRENT_STATE.md`). This is not install, execution, or registry-backed.

**Implemented (static harness):** `scripts/automation_lab_test_tool_candidate.ps1` writes `TEST_RESULTS.json` and `TEST_SUMMARY.md` under the same build folder using offline checks only; it does not execute or import candidate code. Passing results are review evidence only and do not approve install or execution.

**Implemented (install review packaging):** `scripts/automation_lab_create_tool_install_review.ps1` writes `INSTALL_MANIFEST.json` and `INSTALL_REVIEW.md` for human review only; it does not install, mutate the registry, or execute tools. Execution after any future install still requires the normal plan/policy/approval/registry/schema/sandbox path.

**Current hardening:** candidate generation rejects unsafe build indexes (`authority` must be false, `review_evidence_only` must be true) and restores the original `BUILD_INDEX.json` if generation fails after validation.

**Implemented (persistent generated registry metadata):** After install-review packaging, `scripts/automation_lab_install_reviewed_tool.ps1` with explicit phrase `INSTALL_REVIEWED_TOOL` appends metadata to `data/registry/generated_installed_tools.json`; `registry.py` loads those rows at startup. **No** new gateway routes, **no** sandbox/tool execution, **no** `tools.py` dispatch for generated names.

**Implemented (agent-style tool proposal lane, proposal-only):** `scripts/test_agent_tool_proposal_flow.ps1` shows an agent-context Navidrome read-only need entering the Automation Lab `tool_proposal` artifact path via `automation_lab_propose.ps1` only — no install, execution, registry mutation, or dispatch.

**Implemented (generated-tool dry-run, review-only):** `scripts/automation_lab_generated_tool_dry_run.ps1` plus `scripts/generated_tool_dry_run.py` write evidence under `data/generated_tool_dry_runs/<run_id>/` proving registry metadata vs absence of `tools.py` dispatch; no candidate execution, no registry mutation, no sandbox. This is a **safety/review boundary only**, not approval to execute.

**Implemented (offline Navidrome read-only lifecycle example):** `scripts/test_automation_lab_navidrome_readonly_generated_tool_lifecycle_example.ps1` chains the same lifecycle scripts with a synthetic Navidrome read-only proposal text only; **no** real Navidrome traffic, **no** `tools.py` dispatch, **no** runnable Navidrome integration — review/evidence discipline only.

**Still later:** callable wiring for generated tools (dispatch in `tools.py` or equivalent) and any execution path; execution still requires the normal plan/policy/approval/registry/schema/sandbox path.

### Centralized tool HTTP client (static guard)

**Implemented:** `tools_http.py` is the only module on the tool execution surface (`tools.py`, `sandbox.py`, `sandbox_worker.py`, optional future `tools/` package) that imports `httpx`. Built-in tools keep calling `http_allowlist.validate_http_destination` before requests.

**Still later:** optional enforcement of registry-declared HTTP allowlists, shared timeouts, and audit metadata inside `tools_http` (or equivalent), without weakening plan/policy/approval boundaries.

### Gateway authority hardening later

Problem:
Mini-Jarvis has grown from a simple `/ingest` classifier/router into a gateway authority system with explicit plan, policy, approval, registry, schema, and sandbox enforcement. The older `/ingest` → `LOCAL_TOOLS` → `tools_execute` shortcut is **gated by default** on branch `ingest-lane-gating` (no direct tool or sandbox execution from `/ingest` for that target; use `/plans/*`). Further lane-router work may still be needed for other entry surfaces and for automatic plan materialization from gated ingest text.

Goal:
Normalize all external entrypoints into an explicit authority-preserving flow:

```text
chatbar / channel / event / /ingest
-> input envelope
-> lane router
-> plan proposal or automation-lab proposal or review lane
-> policy / approval / registry / schema / sandbox only when execution is explicitly allowed
```

Rules:
- `/ingest` remains the input surface.
- `/ingest` must not bypass plan/policy/approval for side-effecting or uncertain actions.
- `LOCAL_TOOLS` should become a planning/lane hint, not execution permission.
- No approve+execute shortcuts.
- Model output is not authorization.
- Registry, policy, approval, schema, and sandbox remain enforcement.
- Do not add generated tool execution as part of gateway hardening.
- Keep each branch narrow and avoid endpoint expansion unless that branch explicitly selects a router split.

Branch sequence:

1. `ingest-lane-gating` (**baseline implemented**)
   - Scope: Change `/ingest` routing semantics so `LOCAL_TOOLS` classifications do **not** call `tools.execute` or the sandbox by default; return an explicit plan-required lane and audit gate instead of immediate tool execution. (Further work: deterministic plan-from-ingest helpers without broad refactor — see `plan-builder-generalization`.)
   - Purpose: Make `/ingest` a lane router aligned with the gateway authority model while preserving it as the multimodal input surface.
   - Hard safety rules: No approve+execute shortcuts; no automatic execution for side-effecting or uncertain actions; model/classifier output must not authorize execution; registry/policy/approval/schema/sandbox remain required before any execution.

2. `approval-state-locking` (**baseline implemented**)
   - Scope: Bind approval to canonical plan content (`reviewed_plan_sha256` on pending, `approved_plan_sha256` on approved); verify on approve; verify before execute; `409` when a plan was already executed; legacy plans without hashes fail closed until re-proposed. **Per-plan filesystem transition locks** (`data/plans/locks/<plan_id>.lockdir`, atomic `mkdir`, short wait then **409** `plan_transition_locked`) serialize `save_pending_plan`, `approve_plan`, `reject_plan`, and the full `POST /plans/{plan_id}/execute` critical section through `_mark_executed_body` and immediate persistence/audit that must not duplicate. Tests: `scripts/test_approval_file_locking.py`. SQLite may be considered later if plan coordination grows; not introduced here.
   - Purpose: Prevent stale, swapped, or rewritten plan JSON from inheriting approval or executing twice.
   - Hard safety rules: Approval is not portable across plan edits; workspace files remain evidence, not authority; execution fails closed on missing or mismatched hashes before policy/tools/sandbox; no approve+execute shortcut.

3. `policy-approval-unit-tests` (**baseline implemented**)
   - Scope: Add focused tests for policy decisions, approval transitions, and execution preconditions around `/plans/*` and the gated ingest lane (`scripts/test_policy_approval_unit_tests.py`).
   - Purpose: Lock down the authority boundary before widening generated dispatch or runtime integrations.
   - Hard safety rules: Tests must not call real services, install generated tools, mutate durable registry behavior, or add execution shortcuts.

4. `approval-role-keys` (**baseline implemented**)
   - Scope: Optional `GATEWAY_INPUT_API_KEY`, `GATEWAY_APPROVAL_API_KEY`, `GATEWAY_ADMIN_API_KEY` with route-class checks in `main.py` middleware (`services/auth_roles.py`); `GATEWAY_API_KEY` remains master for all routes.
   - Purpose: Separate “can call the gateway” from approve/execute vs registry admin when operators configure split keys.
   - Hard safety rules: No weaker auth; approval key is not admin; `/health` stays public; no plan or ingest semantic changes.

5. `pending-approval-notifications` (**baseline implemented**)
   - Scope: Append-only **`data/notifications/pending_approvals.jsonl`** on each `save_pending_plan`; read-only **`GET /notifications/pending-approvals`** (`READ_REVIEW`, exact path only, latest **200** records, no marking read). Tests: `scripts/test_pending_approval_notifications.py`.
   - Purpose: Improve operator visibility while keeping human review explicit.
   - Hard safety rules: Notifications must be informational only; no approve/reject/execute side effects from notification delivery; no auto-approval; no webhooks/scheduler/MCP; JSONL lines are not deduplicated (re-propose appends).

6. `plan-builder-generalization` (**baseline implemented**)
   - Scope: `services/plan_builder.py` deterministic NL→Plan for `POST /plans/from-message` (maintainer preserved; `media_agent` for installed Radarr/Sonarr/SABnzbd search/queue mappings; `missing_capability` when no installed tool). Tests: `scripts/test_plan_builder_generalization.py`.
   - Purpose: Give lane-gated inputs a consistent way to become reviewable plan proposals without execution.
   - Hard safety rules: Plan building is proposal-only; it must not approve, execute, install tools, invent uninstalled tools, call real services in tests, or bypass policy/registry checks; `/ingest` stays gated.

7. `tool-http-allowlist-guard` (**baseline implemented**)
   - Scope: `tools_http.py` centralizes `httpx` for the tool execution surface; `scripts/test_tool_http_allowlist_guard.py` statically forbids direct `requests` / `httpx` / `aiohttp` / `urllib.request` usage in `tools.py`, `sandbox.py`, `sandbox_worker.py`, and optional `tools/**/*.py`. Built-in tools still call `http_allowlist.validate_http_destination` before outbound calls. This is a **lint-style guard**, not OS-level sandboxing; registry-wide HTTP policy inside the helper remains future work.
   - Purpose: Reduce accidental bypass of configured service bases by scattering raw HTTP clients across tool code.
   - Hard safety rules: No new real service calls in tests; no `/ingest` or approval/execute semantic changes; no registry mutation behavior change.

8. `fastapi-router-split` (**baseline implemented**)
   - Scope: Split `main.py` HTTP handlers into `routers/` modules; move API-key role rules to `services/auth_roles.py`; plan workspace mirror helpers to `services/workspace_mirror.py`. `main.py` remains the composition root (logging, lifespan, middleware, exception handler, `/health`, `include_router`). **`dispatch.py`** unchanged as ingest lane router.
   - Purpose: Reduce coupling and file size without changing paths, methods, status codes, response shapes, or role classification (unknown routes remain **`MASTER_ONLY`**).
   - Hard safety rules: Preserve endpoint contracts; do not add endpoints; do not weaken auth; refactor-only. Tests: `scripts/test_router_split_regression.py` plus existing authority scripts.

9. `plan-step-idempotency-dry-run`
   - Scope: Add plan-step metadata and dry-run/preflight conventions for idempotency, duplicate detection, and side-effect review.
   - Purpose: Help operators understand whether repeating a step is safe before execution.
   - Hard safety rules: Dry-run/preflight is not execution approval; no real service mutation; execution still requires policy, approval, registry, schema, and sandbox.

### Routine contract later

Design framing: `docs/AUTHORITY_AND_EVIDENCE_MODEL.md` (durable authority vs evidence; schedules/adapters as triggers).

Problem:
Mini-Jarvis needs a first-class way to describe repeatable workflows without turning schedules, agents, or input adapters into execution authorities.

Goal:
Define a routine as a repeatable workflow definition that can be triggered manually, by schedule, or by an input adapter, while preserving gateway authority.

A routine may describe:
- goal
- trigger modes
- required capabilities
- allowed agents/tools
- input contract
- output destination
- authorization mode
- risk level
- evidence requirements
- failure behavior
- missing capability behavior

A routine must not:
- execute tools directly
- approve itself
- install generated tools
- bypass policy
- bypass registry/schema checks
- bypass sandbox execution
- treat schedule as authority
- treat model output as authority

Design rules:
- Schedule is trigger, not authority.
- Input adapters are clients, not authority.
- Routine files are configuration/review state, not authority.
- Missing capabilities may produce proposal artifacts.
- Generated tools remain proposal-only until reviewed, tested, approved, and installed.
- Human authorization or a future valid scoped grant is required before side-effect execution.

Safe first branch:
- `routine-contract`
- Add `docs/ROUTINE_CONTRACT.md`.
- Update docs/backlog references only.
- Do not change runtime behavior.

### Routines later

Repeatable Mini-Jarvis tasks should follow `docs/ROUTINE_CONTRACT.md` before any runtime routine or scheduler work. See also `docs/AUTHORITY_AND_EVIDENCE_MODEL.md` for audit vs full-workspace defaults.

Examples:
- on-demand project status routine
- scheduled read-only maintenance summary
- input-adapter-triggered review workflow

Rules:
- Routines are workflow definitions, not agents, tools, or authority.
- Schedule is a trigger, not authority.
- Routine definitions must not approve or execute tools by themselves.
- Keep routine execution behind gateway policy, registry, approval/authorization, and sandbox checks.
- Missing capabilities may produce tool proposals, but must not install or execute generated tools automatically.

### Input and device adapters later

Future trusted-network input sources should follow `docs/IO_ADAPTER_CONTRACT.md` before any implementation work. Triggers vs authority: `docs/AUTHORITY_AND_EVIDENCE_MODEL.md`.

Examples:
- control panel chat bar
- iPhone Shortcut
- Windows hotkey
- Discord bot
- file/image ingress
- voice ingress

Rules:
- Treat these as client/input adapters unless explicitly designed otherwise.
- Do not let adapters become execution authorities.
- Do not bypass the plan/policy/approval path.
- Do not add auto-approval, auto-execution, or approve+execute shortcuts.
- Keep tool/execution adapters behind registry, policy, approval, and sandbox execution.

### MCP prompts later

Add reusable MCP prompts, not MCP tools.

Examples:
- summarize workspace for approval
- review plan for invariant violations
- explain completed result
- draft a follow-up proposed plan

Rules:
- MCP prompts are advisory only.
- Do not expose approve/reject/execute as MCP tools.
- Do not expose sandbox/tool execution through MCP.

### Workspace retention and compaction later

Design framing: `docs/AUTHORITY_AND_EVIDENCE_MODEL.md` (archives, compaction principles, test cleanup expectations).

**Implemented (read-only reporting only):** `scripts/report_workspace_storage.ps1` with `scripts/test_workspace_storage_report.ps1` — stdout-only size report for a `DataRoot` tree (default repo `data/`), largest-folder ranking, test-looking name hints, and archive-age hints; **no** file writes, deletes, compaction, or runtime behavior changes. `workspace-storage-report` branch scope is reporting-only.

**Implemented (read-only archive candidates):** `scripts/report_workspace_archive_candidates.ps1` with `scripts/test_workspace_archive_candidates.ps1` — merged candidate list (age and/or test-artifact naming), sorted oldest-first then by size, capped by `-Top`; active workspaces excluded by default and listed as **review-only** when `-IncludeActive` is set; **no** mutation. `workspace-archive-candidates` branch scope is reporting-only.

Problem:
Smoke tests, proposal flows, and review mirrors create many workspace folders. Over time, `data/workspaces/` can become larger than the codebase because it stores redundant copies of plan, policy, result, and review artifacts.

Goal:
Keep workspaces useful for human review while preventing unbounded storage growth.

Design:
- ~~Add a read-only workspace storage report.~~ **Done:** `scripts/report_workspace_storage.ps1` (see above).
- ~~Identify archive candidates without mutating anything.~~ **Done:** `scripts/report_workspace_archive_candidates.ps1` (read-only merged candidate list; see above).
- Show size by state, age, and largest folders.
- Compact old completed/rejected workspaces into archive folders or zip bundles.
- Preserve `WORKSPACE_SUMMARY.md`, `INDEX.json`, hashes, and audit references.
- Keep active workspaces untouched.
- Treat test-generated workspaces separately.

Rules:
- No deletion by default.
- Prefer archive/compact over delete.
- Require explicit confirmation for any mutation.
- Never archive active workspaces automatically.
- Keep enough evidence to answer what happened, when, and why.
- Workspace files remain review evidence, not authority.
- Gateway, plan state, registry, policy, approvals, sandbox, and audit remain the authority path.

Suggested branch sequence:
1. `workspace-storage-report` — **implemented** (read-only script + test; no data mutation).
2. `workspace-archive-candidates` — **implemented** (read-only candidate list + test; no data mutation).
3. `workspace-compact-archive`
4. `test-workspace-retention`

### Action assurance / structured evidence later

Inspired by the principle: model output is not authority.

Design checkpoint:
- See `docs/AUTHORITY_AND_EVIDENCE_MODEL.md` for authority vs compact audit vs full workspaces.
- See `docs/ACTION_EVIDENCE_SCHEMA.md` for the docs-only proposed evidence schema.
- See `docs/EXECUTION_AUTHORIZATION.md` for the docs-only execution authorization contract.
- The schema is not implemented in runtime code.

Goal:
Improve Mini-Jarvis evidence records so each approved execution can clearly answer:
- Who or what proposed the action?
- On whose behalf was it proposed?
- What authority scope applied?
- Was the action allowed at execution time?
- Who approved it?
- What actually executed?
- What evidence proves the result?

Possible future evidence fields:
- `action_id` / `plan_id`
- `agent_id`
- `source_client`
- `principal_id` or `local_operator`
- `proposed_tool`
- `proposed_args_summary`
- `authority_scope`
- `risk_level`
- `policy_decision`
- `approval_reference`
- `execution_state`
- `workspace_path`
- `audit_event_refs`
- `input_sources`
- `untrusted_input_present`

Rules:
- Model output remains proposal, not authority.
- Workspace files remain readable evidence, not authority.
- Gateway remains the authority.
- Policy, registry, approval state, and sandbox execution remain the enforcement path.
- Do not add auto-approval.
- Do not add auto-execution.
- Do not combine approve+execute.
- Do not add generated tool execution.
- Do not add apply-patch as part of this work.

Safe first branch:
- `structured-action-evidence-schema` adds the docs-only schema proposal.
- Prefer docs/schema proposal before runtime changes.
- Do not change execution behavior in the first pass.

### Policy/risk model later

Durable policy surface vs execution evidence: `docs/AUTHORITY_AND_EVIDENCE_MODEL.md`.

Current policy is still simple.

Future:
- capability-based permissions
- meaningful risk levels
- stricter preflight validation

Possible risk levels:
- `level_0`: read-only / no side effects
- `level_1`: proposal-only / creates review artifacts
- `level_2`: local reversible side effect
- `level_3`: destructive, networked, or costly
- `level_4`: special manual confirmation

### Tool duplication / capability reuse later

Problem:
As generated-tool proposals become possible, the system may create tools with different names but substantially overlapping behavior.

Examples:
- `navidrome_recent_albums`
- `navidrome_list_new_albums`
- `get_new_navidrome_releases`

Goal:
Before proposing a new tool, the system should determine whether the requested capability can be:
- satisfied by an existing installed tool
- handled by extending an existing tool
- composed from existing tools
- or truly requires a new tool

Possible future design:
- Add richer registry metadata for each tool:
  - purpose
  - input schema summary
  - output schema summary
  - side effects
  - capability tags
- Search existing tools by capability, not only by tool name.
- Add a duplicate/overlap check before generated-tool proposal.
- Require a proposed new tool to explain why existing tools are insufficient.
- Surface likely overlaps during human review.

Possible outcomes of overlap review:
- reuse existing tool
- extend existing tool
- compose existing tools
- create new tool
- reject as duplicate

Rules:
- Registry remains the source of truth for installed tools.
- Model output remains proposal, not authority.
- Do not install a new tool solely because the model proposed one.
- Prefer reuse or extension over near-duplicate tools when contracts substantially overlap.
- Keep duplicate detection advisory at first; human review remains decisive.

Safe first step:
- Add capability metadata fields to the future tool proposal / registry design.
- Do not change runtime execution behavior in the first pass.

### Generated tool lifecycle roadmap later

This roadmap is a branch sequence for moving from advisory automation lab artifacts toward a reviewed generated-tool lifecycle. It is backlog guidance only, not approval to execute, register, install, or run generated tools. Evidence vs execution authority: `docs/AUTHORITY_AND_EVIDENCE_MODEL.md`.

Global safety rules:
- Model output is proposal, not authority.
- Automation lab artifacts are review evidence only.
- Registry `status=installed` remains execution truth.
- Generated tools must be tested and reviewed before install.
- Execution must happen only through the normal plan/policy/approval/registry/schema/sandbox flow.
- Each branch must stay within its named scope and must not add automatic tool registration, automatic registry installation, model-driven tool installation, generated tool execution, endpoints, MCP tools, or `/ingest` changes.

Implemented/current slices:
- `capability-registry-lookup`: read-only registry evidence is included in Automation Lab capability matching. It remains advisory and does not mutate registry state.
- `capability-match-scoring`: deterministic advisory scoring, precedence, and conflicts are included in `CAPABILITY_MATCHES.json` v3.
- `tool-build-workspace`: review-only build workspaces are created under `data/tool_builds/<request_id>/`.
- `tool-candidate-generation` / `tool-candidate-hardening`: review-only candidate files can be generated under a build workspace, with fail-closed boundary checks and rollback protection.
- `generated-tool-test-harness`: static/offline harness writes review evidence only (`TEST_RESULTS.json`, `TEST_SUMMARY.md`) and does not import or execute candidate code.
- `tool-install-review`: install-review packaging writes `INSTALL_MANIFEST.json` / `INSTALL_REVIEW.md` as human review evidence only; it does not install, execute, call sandbox, add dispatch, or add gateway routes.
- `registry-install-review`: persistent generated registry metadata can be appended only through the explicit `INSTALL_REVIEWED_TOOL` manual confirmation path; install remains metadata-only and is not execution approval.
- `generated-tool-dry-run`: review-only dry-run evidence proves installed generated metadata against the absence of callable `tools.py` dispatch; it does not import or execute candidate code, call sandbox, mutate registry, or add routes.
- `navidrome-readonly-tool`: the offline Navidrome read-only lifecycle example exercises the existing build -> candidate -> static harness -> install-review -> manual metadata install -> dry-run flow with synthetic artifacts only; it is not a runnable Navidrome integration.

Prerequisite note:
Before `generated-callable-dispatch-gate`, `navidrome-runtime-readonly-integration`, or any real runtime generated-tool execution, complete or explicitly defer:
- `ingest-lane-gating`
- `approval-state-locking`
- `policy-approval-unit-tests`

Remaining focused sequence:

1. `executable-isolated-candidate-test-harness`
   - Scope: Add a future harness for mocked executable tests against reviewed generated tool candidates.
   - Purpose: Validate input/output behavior and mocked integration assumptions after static review, before install review.
   - Hard safety rules: Tests must not mutate the real registry, call the sandbox worker, touch real services by default, or convert a passing candidate into an installed tool.

2. `generated-callable-dispatch-gate`
   - Scope: Add explicit callable wiring for generated tools, if approved, behind normal registry/schema/policy/approval checks.
   - Purpose: Move from metadata-only generated installs toward tightly controlled execution without granting broad runtime autonomy.
   - Hard safety rules: No automatic or model-driven dispatch; install is not execution approval; execution must still use the normal plan/policy/approval/registry/schema/sandbox path.

3. `navidrome-runtime-readonly-integration`
   - Scope: Add a real Navidrome read-only runtime integration only after generated callable dispatch rules exist.
   - Purpose: Exercise a concrete read-only service integration with explicit environment configuration and no write/download/playback/delete behavior.
   - Hard safety rules: No playlist edits, downloads, deletes, playback control, or unapproved service calls; any real run must use installed registry status and the normal approved execution path.

4. `routine-proposal-runtime`
    - Scope: Add proposal-only routine runtime behavior that can create review artifacts from routine definitions.
    - Purpose: Connect routines to the generated-tool lifecycle while keeping schedules and adapters as triggers only.
    - Hard safety rules: Routines are workflow definitions, not authority; missing capabilities create proposals only; execution remains limited to the normal plan/policy/approval/registry/schema/sandbox flow.

OpenClaw-style channel/session/gateway ideas are useful input and session architecture references. In Mini-Jarvis, model workers and agent runtimes may propose, draft, or generate candidate code, but registry, policy, approval, schema validation, and sandbox execution remain enforcement. Workspace/context files are review and planning context, not authority.

## Medium-term backlog


### Orchestrator agent later

Inspired by OpenSwarm, but stricter.

Goal:
Add an orchestrator-like agent that proposes routes/plans only.

Allowed:
- Produce `ROUTE.json`.
- Propose agent selection.
- Propose plan drafts.

Not allowed:
- Execute tools.
- Approve plans.
- Bypass gateway.
- Delegate direct tool execution.
- Multi-agent autonomy.

Rule:
The orchestrator can improve routing, but the gateway remains authority.

### Linux hardening later

Future Linux deployment should consider:
- dedicated low-privilege worker user
- systemd sandboxing
- filesystem permission isolation
- environment allowlist
- network restrictions for non-network tools
- per-tool timeout
- memory/process limits

Do not overbuild while still developing on Windows.

### Apply-patch later

Do not implement yet.

Prerequisites:
- compact review UX is stable
- patch proposal workflow is trusted
- stronger policy/risk levels exist
- good tests exist
- backup or git-diff safety strategy exists

Safe future flow:

```text
propose_patch
→ PATCH_PROPOSAL.md
→ human review
→ separate apply_patch plan
→ policy check
→ human approval
→ sandbox execution
→ tests
→ RESULT.md
```
