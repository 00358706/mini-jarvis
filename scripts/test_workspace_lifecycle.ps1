# Workspace lifecycle smoke test (propose -> reject).
# This script checks readable workspace state only.

$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

$PlanId = "manual_workspace_001"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ActivePath = Join-Path $RepoRoot "data\workspaces\active\$PlanId"
$RejectedPath = Join-Path $RepoRoot "data\workspaces\rejected\$PlanId"
$CompletedPath = Join-Path $RepoRoot "data\workspaces\completed\$PlanId"

Write-Host "Base URL: $BaseUrl"
Write-Host "Plan id : $PlanId"

# Clean up only this test workspace id.
foreach ($p in @($ActivePath, $RejectedPath, $CompletedPath)) {
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p
        Write-Host "Removed old test path: $p"
    }
}

$PlanBody = @{
    plan_id           = $PlanId
    summary           = "Workspace lifecycle smoke test"
    agent             = "media_agent"
    risk              = "level_0"
    requires_approval = $true
    steps             = @(
        @{
            step_id     = "step_1"
            tool        = "radarr_search"
            args        = @{ title = "Inception" }
            description = "Read-only search step"
        }
    )
    limits            = @{
        max_tool_calls      = 6
        max_runtime_seconds = 90
        allow_cloud         = $false
        allow_delete        = $false
    }
    status            = "proposed"
} | ConvertTo-Json -Depth 6

Write-Host ""
Write-Host "--- POST /plans/propose ---"
$Propose = Invoke-RestMethod -Uri "$BaseUrl/plans/propose" -Method Post -Headers $Headers -Body $PlanBody
$Propose | ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "--- Active workspace exists ---"
Write-Host ("active path exists: " + (Test-Path $ActivePath))

$ActiveRequest = Join-Path $ActivePath "REQUEST.md"
$ActivePlan = Join-Path $ActivePath "PLAN.json"
$ActivePolicy = Join-Path $ActivePath "POLICY_DECISION.json"
$ActiveApproval = Join-Path $ActivePath "APPROVAL.md"

Write-Host ""
Write-Host "--- Active workspace files ---"
Write-Host ("REQUEST.md exists: " + (Test-Path $ActiveRequest))
Write-Host ("PLAN.json exists: " + (Test-Path $ActivePlan))
Write-Host ("POLICY_DECISION.json exists: " + (Test-Path $ActivePolicy))
Write-Host ("APPROVAL.md exists: " + (Test-Path $ActiveApproval))

$RejectBody = @{ reason = "workspace lifecycle test cleanup" } | ConvertTo-Json

Write-Host ""
Write-Host "--- POST /plans/$PlanId/reject ---"
$Reject = Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/reject" -Method Post -Headers $Headers -Body $RejectBody
$Reject | ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "--- Rejected workspace exists ---"
Write-Host ("rejected path exists: " + (Test-Path $RejectedPath))

$RejectedResult = Join-Path $RejectedPath "RESULT.md"
$RejectedApproval = Join-Path $RejectedPath "APPROVAL.md"

Write-Host ""
Write-Host "--- Rejected workspace files ---"
Write-Host ("RESULT.md exists: " + (Test-Path $RejectedResult))
Write-Host ("APPROVAL.md exists: " + (Test-Path $RejectedApproval))

Write-Host ""
Write-Host "Done."
