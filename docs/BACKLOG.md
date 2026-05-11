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

### `routine-contract`

Define repeatable workflow definitions before adding any routine runtime.

Scope:
- Docs/schema only.
- Add `docs/ROUTINE_CONTRACT.md`.
- Define routine fields, trigger modes, authorization relationship, capability requirements, output/evidence requirements, missing capability behavior, and lifecycle states.
- Clarify that schedules/input adapters are triggers, not authority.
- Clarify that routines are not agents, tools, services, or execution authorities.

Rules:
- Do not change runtime execution behavior.
- Do not add scheduler runtime.
- Do not add generated tool execution.
- Do not add automatic tool registration.
- Do not change `/ingest`.
- Gateway remains authority.
- Registry, policy, authorization, schema validation, and sandbox execution remain the enforcement path.

Suggested follow-up branch:
- `capability-registry-schema`
## Near-term backlog

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

### Workspace cleanup later

Problem:
Smoke tests and experiments create many active/completed/rejected workspaces.

Safe first step:
- Add read-only workspace archive candidates.
- Show old workspaces by state and age.

Rules:
- No deletion by default.
- Prefer archive/move over delete.
- Require explicit confirmation for any mutation.
- Keep audit trail.

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
