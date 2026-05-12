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

**Current hardening:** candidate generation rejects unsafe build indexes (`authority` must be false, `review_evidence_only` must be true) and restores the original `BUILD_INDEX.json` if generation fails after validation.

**Still later:** the `generated-tool-test-harness` branch may add runnable tests; model-driven refinement remains out of scope for the narrow script above.

### Routine contract later

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

Repeatable Mini-Jarvis tasks should follow `docs/ROUTINE_CONTRACT.md` before any runtime routine or scheduler work.

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

Future trusted-network input sources should follow `docs/IO_ADAPTER_CONTRACT.md` before any implementation work.

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

Problem:
Smoke tests, proposal flows, and review mirrors create many workspace folders. Over time, `data/workspaces/` can become larger than the codebase because it stores redundant copies of plan, policy, result, and review artifacts.

Goal:
Keep workspaces useful for human review while preventing unbounded storage growth.

Design:
- Add a read-only workspace storage report.
- Show size by state, age, and largest folders.
- Identify archive candidates without mutating anything.
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
1. `workspace-storage-report`
2. `workspace-archive-candidates`
3. `workspace-compact-archive`
4. `test-workspace-retention`

### Action assurance / structured evidence later

Inspired by the principle: model output is not authority.

Design checkpoint:
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

This roadmap is a branch sequence for moving from advisory automation lab artifacts toward a reviewed generated-tool lifecycle. It is backlog guidance only, not approval to execute, register, install, or run generated tools.

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

Remaining focused sequence:

1. `generated-tool-test-harness`
   - Scope: Add a harness for deterministic tests against generated tool candidates.
   - Purpose: Validate schemas, input/output behavior, mocked integrations, and safety assumptions before install review.
   - Hard safety rules: Tests must not mutate the real registry, call the sandbox worker, touch real services by default, or convert a passing candidate into an installed tool.

2. `tool-install-review`
   - Scope: Package the candidate, tests, risk notes, side effects, network access, and proposed registry diff for human review.
   - Purpose: Make the install decision auditable and separate from candidate generation.
   - Hard safety rules: The package cannot install itself; approval for implementation is not approval for execution; all side effects and network access remain review items.

3. `registry-install-review`
   - Scope: Add a manual/admin-controlled path to install a reviewed candidate from a review package.
   - Purpose: Convert a tested, reviewed candidate into a real registry entry only after explicit human action.
   - Hard safety rules: No automatic or model-driven install; registry `status=installed` remains the only execution truth; installed entries must include validated schemas.

4. `generated-tool-dry-run`
   - Scope: Add a dry-run path for newly installed generated tools through the normal execution controls.
   - Purpose: Verify sandbox wiring and evidence for generated tools without granting broad runtime autonomy.
   - Hard safety rules: Dry runs require prior manual install and must go through normal plan, policy, approval, registry, schema, and sandbox checks.

5. `navidrome-readonly-tool`
   - Scope: Exercise the lifecycle with a low-risk Navidrome read-only generated tool candidate.
   - Purpose: Prove the reviewed lifecycle on release/new-album lookup behavior before considering broader generated tools.
   - Hard safety rules: No write or destructive behavior; no automatic install or execution; any real run must use installed registry status and the normal approved execution path.

6. `routine-proposal-runtime`
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
