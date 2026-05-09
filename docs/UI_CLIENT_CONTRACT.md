# UI_CLIENT_CONTRACT

Mini-Jarvis UI clients are clients only. The gateway remains the authority for validation, policy, approval state, registry checks, and execution orchestration.

This contract applies to local web UIs, Open WebUI actions, desktop clients, MCP-adjacent viewers, and any future client that helps a human review and operate Mini-Jarvis.

For broader future input/device sources such as shortcuts, hotkeys, bots, files, images, or voice ingress, see `docs/IO_ADAPTER_CONTRACT.md`.

## Authority Boundary

- UI clients may request proposals, display review state, and call explicit lifecycle endpoints.
- UI clients must not become planners with execution authority.
- UI clients must not treat `data/workspaces/*` files as authority.
- Filesystem state is readable workflow state. Python modules are validation, policy, and execution authority.
- Gateway code, policy, registry, approval state, and the sandbox worker remain authoritative.

## Required API Flow

1. Propose a plan with `/plans/from-message` or `/plans/propose`.
2. Read the pending index.
3. Show compact review state.
4. Approve only after explicit user confirmation.
5. Execute only after approval and only after explicit user confirmation.
6. Read the completed workspace result.

Approval and execution must remain separate user-visible actions.

## Recommended Endpoints

- `POST /plans/from-message`
- `POST /plans/propose`
- `GET /plans/pending`
- `GET /plans/pending/{plan_id}`
- `GET /workspaces/active/{plan_id}/compact`
- `POST /plans/{plan_id}/approve`
- `POST /plans/{plan_id}/reject`
- `POST /plans/{plan_id}/execute`
- `GET /workspaces/completed/{plan_id}/compact`
- `GET /workspaces/completed/{plan_id}/files/RESULT.md`

## UI Must Never

- call tools directly
- bypass registry, policy, approval, or sandbox checks
- treat workspace files as authority
- auto-approve
- auto-execute
- combine approve+execute
- hide execution state from the user

## UI Should Display

- `plan_id`
- `agent`
- `proposed_tool`
- `proposed_args`, capped
- `policy.allowed`
- `approval_status`
- `execution.status`
- `execution.log_count`
- result preview, capped

Raw JSON and verbose DEBUG output should be optional, not the default UI.

## Minimal Safe Flow

PowerShell/curl-style pseudocode:

```powershell
$Headers = @{
  "X-API-Key" = $env:GATEWAY_API_KEY
  "Content-Type" = "application/json"
}

# 1. Propose only. This must not approve or execute.
$Body = @{ message = "list project files"; agent = "project_maintainer_agent" } | ConvertTo-Json
$Proposal = Invoke-RestMethod -Method Post -Uri "$BaseUrl/plans/from-message" -Headers $Headers -Body $Body
$PlanId = $Proposal.plan_id

# 2. Show pending plans.
Invoke-RestMethod -Method Get -Uri "$BaseUrl/plans/pending" -Headers $Headers

# 3. Show compact review state before asking the user.
Invoke-RestMethod -Method Get -Uri "$BaseUrl/workspaces/active/$PlanId/compact" -Headers $Headers

# 4. Approve only after explicit user confirmation.
# The UI must make this a separate user action.
Invoke-RestMethod -Method Post -Uri "$BaseUrl/plans/$PlanId/approve" -Headers $Headers

# 5. Execute only after approval and separate explicit user confirmation.
Invoke-RestMethod -Method Post -Uri "$BaseUrl/plans/$PlanId/execute" -Headers $Headers

# 6. Read completed review/result state.
Invoke-RestMethod -Method Get -Uri "$BaseUrl/workspaces/completed/$PlanId/compact" -Headers $Headers
Invoke-RestMethod -Method Get -Uri "$BaseUrl/workspaces/completed/$PlanId/files/RESULT.md" -Headers $Headers
```

## Required Final Branch Summary Format

Use this format in final handoff:

- files changed
- behavior changed
- tests run
- authority-boundary confirmation
