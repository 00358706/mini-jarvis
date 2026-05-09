# ROUTINE_CONTRACT

This document defines a docs-only contract for repeatable Mini-Jarvis routines.

It does not add runtime behavior, endpoints, scheduler behavior, policy logic, registry entries, tools, UI behavior, or MCP tools.

## Purpose

A routine is a repeatable workflow definition that can be run on demand or triggered later by a schedule or input adapter.

Routines are not agents, not tools, and not authority. They may propose or trigger plans through the gateway authority model.

## Authority Boundary

- Gateway remains authority for validation, policy, approval state, registry checks, and execution orchestration.
- Agents are folders, not services.
- Routines are workflow definitions, not services.
- Routine definitions are not execution authority.
- Schedule is a trigger, not authority.
- Input adapters are clients/context sources, not authority.
- Model output is proposal, not authority.
- Workspace files are evidence and review state, not authority.
- Registry remains the source of truth for installed tools.
- Policy decides whether a proposed plan is allowed.
- Human approval or explicit authorization is required before approved-plan execution.
- Approval and execution remain separate unless a future explicit `authorize_and_run_once` mode is implemented under `docs/EXECUTION_AUTHORIZATION.md`.
- Sandbox worker remains the only side-effect execution path.

## Routine Definition Fields

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `routine_id` | string | yes | Stable routine identifier, for example `daily_project_status`. |
| `agent_id` | string | yes | Agent folder id used for proposal context, for example `project_maintainer_agent`. |
| `description` | string | yes | Human-readable description of the repeatable workflow. |
| `trigger_modes` | array | yes | Allowed trigger modes: `on_demand`, `schedule`, and/or `input_adapter`. |
| `io_envelope` | object or null | optional | Normalized input envelope context, following `docs/IO_ADAPTER_CONTRACT.md`, when triggered by an input adapter. |
| `allowed_tools` | array | optional | Tool names the routine may reference in proposed plans. This is not execution permission. |
| `required_capabilities` | array | optional | Capability names or descriptions the routine needs, even when no installed tool exists yet. |
| `authorization_mode` | string | yes | One of `propose_only`, `approve_for_later`, `authorize_and_run_once`, or `future_scoped_grant`. |
| `risk_level` | string | yes | Routine risk level, such as `level_0`, `level_1`, `level_2`, `level_3`, or `level_4`. |
| `output_destinations` | array | yes | One or more of `control_panel_feed`, `workspace_result`, `notification`, or `external_client_response`. |
| `workspace_requirements` | object | yes | Required workspace/evidence artifacts for review and audit. |
| `failure_stop_conditions` | array | yes | Conditions that must stop proposal, authorization, or execution. |
| `created_at` | string | optional | ISO 8601 timestamp for routine definition creation. |
| `updated_at` | string | optional | ISO 8601 timestamp for routine definition update. |

## Trigger Modes

### `on_demand`

An explicit user/client action asks Mini-Jarvis to run or propose the routine.

Rules:
- The user action is a trigger only.
- The routine must still pass through gateway proposal, policy, approval/authorization, registry, and sandbox boundaries.

### `schedule`

A future scheduler may trigger the routine at a configured time or interval.

Rules:
- Schedule is a trigger, not authority.
- A schedule must not approve plans.
- A schedule must not execute tools.
- A schedule must not bypass policy, registry, approval/authorization, or sandbox checks.

### `input_adapter`

A future input adapter may trigger the routine from a normalized I/O adapter envelope.

Rules:
- The input adapter envelope provides context/evidence, not execution authority.
- `requested_agent_id`, attachments, trusted-network metadata, and requested output mode are preferences/context only.
- The routine must not treat adapter input as approval or authorization.

## Relationship To The Normalized I/O Adapter Envelope

Routines may be triggered by the normalized envelope described in `docs/IO_ADAPTER_CONTRACT.md`.

Relevant envelope fields may populate routine context:
- `source_client`
- `source_client_version`
- `device_id`
- `message` or `user_intent`
- `input_type`
- `modalities`
- `attachments`
- `trusted_network`
- `requested_agent_id`
- `requested_output_mode`
- `created_at`

These fields help describe the request and evidence trail. They do not authorize execution.

## Allowed Tools And Required Capabilities

`allowed_tools` describes tools a routine may reference in proposed plans.

Rules:
- Tool references are not execution permission.
- Tools must still be installed in the registry before execution.
- Tool arguments must still validate against registry schema.
- Policy must still allow the proposed plan.
- Execution must still go through sandbox worker after approval/authorization.

`required_capabilities` may describe capabilities that do not exist yet.

If a required capability is missing, Mini-Jarvis may propose a tool design or implementation plan, but must not install or execute generated tools automatically.

## Authorization Modes

### `propose_only`

The routine may create or request a proposed plan only.

Properties:
- No approval occurs.
- No execution occurs.
- Human review is still required before any side effect.

### `approve_for_later`

The routine may support a human approving a reviewed plan for later execution.

Properties:
- Approval does not execute tools.
- Execution remains a separate explicit action.
- See `docs/EXECUTION_AUTHORIZATION.md`.

### `authorize_and_run_once`

Future docs-only target for a single explicit human action after review that authorizes and runs the exact reviewed plan once.

Properties:
- Must bind to exact reviewed plan content, such as a `plan_hash`.
- Must re-check policy and registry/schema at execution time.
- Must run only through sandbox worker.
- Must not become hidden auto-execution.
- See `docs/EXECUTION_AUTHORIZATION.md`.

### `future_scoped_grant`

Future-only bounded grant for routine or capability execution.

Properties:
- Must be designed and approved separately before implementation.
- Must be revocable, expiring, auditable, and constrained by risk/capability scope.
- Must not become a hidden auto-approve or auto-execute channel.

## Output Destinations

Routine output may be directed to one or more future destinations:

- `control_panel_feed`: show status/result in a local control panel.
- `workspace_result`: write review/result evidence into the plan workspace.
- `notification`: send a notification after proposal, failure, approval need, or completion.
- `external_client_response`: return a capped response to the triggering client/input adapter.

Output destinations are presentation and evidence channels. They do not authorize execution.

## Workspace And Evidence Requirements

Every routine-triggered proposal or execution should preserve enough evidence for review:

- routine id and version/reference when available
- trigger mode
- triggering source client or scheduler reference
- normalized I/O adapter envelope reference when applicable
- proposed plan id and reviewed plan reference
- policy decision reference
- authorization mode and authorization reference when applicable
- workspace path
- execution log reference when executed
- result summary or result artifact reference
- error state if stopped or failed

Workspace files remain evidence/review state, not authority.

## Failure And Stop Conditions

A routine must stop before approval/authorization/execution if any required condition fails:

- missing or invalid `routine_id`
- missing or unknown `agent_id`
- trigger mode not allowed by the routine definition
- requested capability is unavailable and no proposal-only fallback is selected
- proposed tool is not installed in the registry
- policy denies the proposed plan
- required human approval/authorization is missing
- reviewed plan content changes after authorization
- authorization is expired or revoked
- registry/schema re-check fails at execution time
- sandbox execution cannot be used
- required workspace/evidence artifact cannot be written or referenced

Failure should produce reviewable evidence when possible. Failure must not be converted into permission to proceed.

## Example Shape

```json
{
  "routine_id": "daily_project_status",
  "agent_id": "project_maintainer_agent",
  "description": "Create a read-only project status summary for review.",
  "trigger_modes": ["on_demand", "schedule"],
  "io_envelope": null,
  "allowed_tools": ["list_project_files", "search_repo", "inspect_file"],
  "required_capabilities": ["read repository state", "summarize changed files"],
  "authorization_mode": "propose_only",
  "risk_level": "level_0",
  "output_destinations": ["control_panel_feed", "workspace_result"],
  "workspace_requirements": {
    "write_plan": true,
    "write_policy_decision": true,
    "write_authorization_ref": false,
    "write_execution_log_if_executed": true,
    "write_result_if_executed": true
  },
  "failure_stop_conditions": [
    "policy_denied",
    "tool_not_installed",
    "authorization_missing",
    "sandbox_unavailable"
  ],
  "created_at": "2026-05-09T00:00:00Z",
  "updated_at": null
}
```

## Generated Tools Rule

Missing capabilities may produce a proposed tool design, schema, or implementation plan.

They must not:
- install generated tools automatically
- execute generated tools automatically
- bypass tool lifecycle review
- bypass registry installation status
- bypass policy, approval/authorization, or sandbox execution

## Future Implementation Rules

- Add runtime routine behavior only in a future branch with explicit approval.
- Do not add scheduler behavior as part of this contract.
- Do not add endpoints as part of this contract.
- Do not treat routine definitions as authority.
- Keep routine-triggered work on the existing gateway authority path.

