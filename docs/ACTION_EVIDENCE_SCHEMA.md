# ACTION_EVIDENCE_SCHEMA

Structured action evidence is a future design proposal for improving action assurance in Mini-Jarvis.

This document is documentation only. It does not define runtime behavior, create endpoints, change policy, change approval, or add an execution path.

## Authority Boundary

- Model output is proposal, not authority.
- Workspace files are evidence and review state, not authority.
- Gateway remains authority for validation, policy, approval state, registry checks, and execution orchestration.
- Registry remains the source of truth for installed tools.
- Policy decides whether a proposed plan is allowed.
- Human approval is required before approved-plan execution.
- Approval and execution remain separate.
- Sandbox worker remains the only side-effect execution path.

Evidence records should help humans and future audits explain what happened. They must not be used as a second authority path.

## Design Goal

Future action evidence should make each proposed or executed action easy to review:

- What was proposed?
- Who or what proposed it?
- Which client presented or submitted it?
- What policy decision applied?
- Who approved it, if anyone?
- What executed, if anything?
- Where is the reviewable workspace/result evidence?

The schema below is a target shape for future records. It is intentionally descriptive and should be implemented only in a later branch after explicit approval.

## Proposed Fields

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `schema_version` | string | yes | Evidence schema version, for example `action-evidence.v1`. |
| `plan_id` | string | yes | Plan identity used by the plan, approval, workspace, and execution lifecycle. |
| `action_id` | string | optional | Future per-action identity when a plan contains multiple independently reviewed actions. |
| `agent_id` | string | yes | Agent identity from the proposed plan, for example `project_maintainer_agent`. |
| `source_client` | string | optional | Client or UI that submitted or displayed the proposal, for example `openwebui`, `local_dashboard`, or `external_script`. |
| `source_client_version` | string | optional | Future version/build reference for the source client, if available. |
| `proposed_tool` | string | yes | Tool name referenced by the proposal. |
| `proposed_args_summary` | object | yes | Capped, review-safe summary of proposed arguments. Do not require full raw args for human review. |
| `registry_tool_name` | string | optional | Registry tool name matched at evaluation/execution time, if available later. |
| `registry_tool_version` | string | optional | Registry tool version matched at evaluation/execution time, if available later. |
| `policy_allowed` | boolean | yes | Whether policy allowed the proposed plan/action. |
| `policy_reason` | string | yes | Human-readable policy reason or denial explanation. |
| `policy_decision_ref` | string | optional | Reference to `POLICY_DECISION.json`, audit entry, or future policy decision id. |
| `risk_level` | string | optional | Future risk level such as `level_0`, `level_1`, `level_2`, `level_3`, or `level_4`. |
| `approval_state` | string | yes | Approval lifecycle state, for example `pending`, `approved`, `rejected`, or `executed`. |
| `approval_reference` | string | optional | Reference to approval state, approval event, operator confirmation, or audit entry. |
| `execution_state` | string | yes | Execution lifecycle state, for example `not_executed`, `executed_success`, `executed_with_errors`, or `execution_failed`. |
| `sandbox_execution_reference` | string | optional | Reference to sandbox execution evidence, such as `EXECUTION_LOG.jsonl` or an audit event id. |
| `workspace_path` | string | yes | Workspace path under `data/workspaces/{active|completed|rejected}/<plan_id>/`. |
| `result_summary` | string | optional | Capped human-readable result summary. |
| `input_sources` | array | optional | Review-safe descriptions of input sources that influenced the proposal. |
| `untrusted_input_present` | boolean | yes | Whether untrusted or user-provided input influenced the proposal. |
| `generated_artifact_present` | boolean | yes | Whether model-generated or tool-generated artifacts were produced or referenced. |
| `error_state` | object | optional | Structured error summary, if policy, approval, execution, or evidence collection failed. |
| `created_at` | string | yes | ISO 8601 timestamp when evidence was created. |
| `updated_at` | string | optional | ISO 8601 timestamp when evidence was last updated. |
| `approved_at` | string | optional | ISO 8601 timestamp for approval, if approved. |
| `executed_at` | string | optional | ISO 8601 timestamp for execution, if executed. |

## Example Shape

```json
{
  "schema_version": "action-evidence.v1",
  "plan_id": "example_plan_001",
  "action_id": "example_plan_001:step_1",
  "agent_id": "project_maintainer_agent",
  "source_client": "local_dashboard",
  "source_client_version": null,
  "proposed_tool": "list_project_files",
  "proposed_args_summary": {
    "path": ".",
    "max_results": 100
  },
  "registry_tool_name": "list_project_files",
  "registry_tool_version": null,
  "policy_allowed": true,
  "policy_reason": "Tool is allowed for this agent and proposal.",
  "policy_decision_ref": "data/workspaces/active/example_plan_001/POLICY_DECISION.json",
  "risk_level": "level_0",
  "approval_state": "approved",
  "approval_reference": "data/plans/approved/example_plan_001.json",
  "execution_state": "not_executed",
  "sandbox_execution_reference": null,
  "workspace_path": "data/workspaces/active/example_plan_001",
  "result_summary": null,
  "input_sources": [
    {
      "kind": "user_message",
      "summary": "list project files"
    }
  ],
  "untrusted_input_present": true,
  "generated_artifact_present": false,
  "error_state": null,
  "created_at": "2026-05-07T00:00:00Z",
  "updated_at": null,
  "approved_at": "2026-05-07T00:01:00Z",
  "executed_at": null
}
```

## Future Implementation Rules

- Add runtime evidence only in a future branch with explicit approval.
- Keep evidence records read-only from client/UI authority perspective.
- Do not let evidence files approve, execute, retry, or authorize tools.
- Do not use evidence files to bypass registry status, policy decisions, approval state, or sandbox execution.
- Keep approval and execution separate even if evidence is displayed in a single UI review card.
- Cap raw input, args, and result previews when shown to humans.
- Treat missing evidence as a review problem, not as authorization to proceed.

