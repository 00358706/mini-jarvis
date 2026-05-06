# Workspace compact summary smoke test (read-only).

$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

$PlanId = "manual_workspace_compact_" + (Get-Date -Format "yyyyMMdd_HHmmss")

function Invoke-Get {
    param([string]$Uri)
    return Invoke-RestMethod -Uri $Uri -Method Get -Headers $Headers
}

function Get-HttpStatusCode {
    param($ErrorRecord)
    try {
        $resp = $ErrorRecord.Exception.Response
        if ($resp -and $resp.StatusCode) {
            return [int]$resp.StatusCode.value__
        }
    } catch {
        return -1
    }
    return -1
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

Write-Host "Base URL: $BaseUrl"
Write-Host "Plan id :  $PlanId"

Write-Host ""
Write-Host "--- POST /plans/from-message (create proposed plan) ---"
$Body = @{
    message = "list project files"
    agent   = "project_maintainer_agent"
    plan_id = $PlanId
} | ConvertTo-Json -Depth 6

$Resp = Invoke-RestMethod -Uri "$BaseUrl/plans/from-message" -Method Post -Headers $Headers -Body $Body
Write-Host ("from-message status: " + $Resp.status)
Assert-True ($Resp.status -eq "pending_approval") "Expected pending_approval from /plans/from-message."

Write-Host ""
Write-Host "--- GET /workspaces/active/{plan_id}/compact ---"
$ActiveCompact = Invoke-Get -Uri "$BaseUrl/workspaces/active/$PlanId/compact"

Assert-True ($ActiveCompact.task_id -eq $PlanId) "compact.task_id mismatch."
Assert-True ($ActiveCompact.state -eq "active") "Expected compact.state=active."
Assert-True ($ActiveCompact.agent -eq "project_maintainer_agent") "Expected compact.agent=project_maintainer_agent."

Assert-True ($ActiveCompact.approval_status -eq "pending_approval") "Expected approval_status=pending_approval."
Assert-True ($ActiveCompact.policy.allowed -eq $true) "Expected policy.allowed=true."

Assert-True ($ActiveCompact.execution.log_count -eq 0) "Expected execution.log_count==0 before execution."
Assert-True ($ActiveCompact.execution.has_result -eq $false) "Expected execution.has_result=false before execution."

Assert-True ($ActiveCompact.review.recommended_next_action -eq "review_then_approve_or_reject") "Expected recommended_next_action for active proposals."

Assert-True ($ActiveCompact.steps -is [System.Array] -and $ActiveCompact.steps.Count -ge 1) "Expected at least one step in compact response."
$Step0 = $ActiveCompact.steps[0]

Assert-True ($Step0.tool -eq "list_project_files") "Expected step.tool=list_project_files."
Assert-True ($Step0.args.root -eq ".") "Expected step.args.root=."
Assert-True ($Step0.args.max_results -eq 200) "Expected step.args.max_results=200."

Write-Host "Active compact summary looks correct (read-only; no execution occurred)."

Write-Host ""
Write-Host "--- POST /plans/{id}/approve + execute ---"
$Approve = Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/approve" -Method Post -Headers $Headers
Assert-True ($Approve.status -eq "approved") "Expected approved from /plans/{id}/approve."

$Execute = Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/execute" -Method Post -Headers $Headers
Write-Host ("execute status: " + $Execute.status)
Assert-True ($Execute.status -eq "executed_success") "Expected executed_success from /plans/{id}/execute."

Write-Host ""
Write-Host "--- GET /workspaces/completed/{plan_id}/compact ---"
$CompletedCompact = Invoke-Get -Uri "$BaseUrl/workspaces/completed/$PlanId/compact"

Assert-True ($CompletedCompact.task_id -eq $PlanId) "compact.task_id mismatch (completed)."
Assert-True ($CompletedCompact.state -eq "completed") "Expected compact.state=completed."

Assert-True (
    ($CompletedCompact.execution.status -eq "executed_success" -or $CompletedCompact.execution.status -eq "executed_with_errors")
) "Expected completed.execution.status to be executed_success or executed_with_errors."

Assert-True ($CompletedCompact.artifacts.result_present -eq $true) "Expected artifacts.result_present=true after execution."
Assert-True ($CompletedCompact.execution.has_result -eq $true) "Expected execution.has_result=true after execution."

Write-Host ""
Write-Host "--- Invalid state/task_id traversal should be rejected ---"
try {
    Invoke-Get -Uri "$BaseUrl/workspaces/badstate/$PlanId/compact" | Out-Null
    throw "Invalid state unexpectedly succeeded."
} catch {
    $code = Get-HttpStatusCode $_
    Write-Host ("invalid state HTTP status: " + $code)
    Assert-True ($code -eq 400) "Expected HTTP 400 for invalid state."
}

try {
    # Invalid task id contains '..' and should fail storage-id validation (HTTP 400).
    Invoke-Get -Uri "$BaseUrl/workspaces/active/bad..id/compact" | Out-Null
    throw "Invalid task_id unexpectedly succeeded."
} catch {
    $code = Get-HttpStatusCode $_
    Write-Host ("invalid task_id HTTP status: " + $code)
    Assert-True ($code -eq 400) "Expected HTTP 400 for invalid task_id."
}

Write-Host ""
Write-Host "Done."

