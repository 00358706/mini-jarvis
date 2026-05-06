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
- `source_ui`
- `principal_id` or `local_operator`
- `proposed_tool`
- `proposed_args_summary`
- `authority_scope`
- `risk_level`
- `policy_decision`
- `approval_reference`
- `execution_status`
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
- Add or document a structured evidence schema only.
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
