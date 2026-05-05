# Workspace execution-log smoke test (propose -> approve -> execute).

$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

$PlanId = "manual_execution_log_001"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ActivePath = Join-Path $RepoRoot "data\workspaces\active\$PlanId"
$RejectedPath = Join-Path $RepoRoot "data\workspaces\rejected\$PlanId"
$CompletedPath = Join-Path $RepoRoot "data\workspaces\completed\$PlanId"

Write-Host "Base URL: $BaseUrl"
Write-Host "Plan id : $PlanId"

foreach ($p in @($ActivePath, $RejectedPath, $CompletedPath)) {
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p
        Write-Host "Removed old test path: $p"
    }
}

$PlanBody = @{
    plan_id           = $PlanId
    summary           = "Workspace execution log smoke test"
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
Write-Host "--- POST /plans/$PlanId/approve ---"
$Approve = Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/approve" -Method Post -Headers $Headers
$Approve | ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "--- POST /plans/$PlanId/execute ---"
$Execute = Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/execute" -Method Post -Headers $Headers
$Execute | ConvertTo-Json -Depth 12

if ($Execute.status -in @("executed_success", "executed_with_errors")) {
    Write-Host ("execute status: " + $Execute.status)
} else {
    Write-Host ("WARNING: unexpected execute status: " + $Execute.status)
}

$CompletedLog = Join-Path $CompletedPath "EXECUTION_LOG.jsonl"
$CompletedResult = Join-Path $CompletedPath "RESULT.md"

Write-Host ""
Write-Host "--- Completed workspace checks ---"
Write-Host ("completed path exists: " + (Test-Path $CompletedPath))
Write-Host ("EXECUTION_LOG.jsonl exists: " + (Test-Path $CompletedLog))
Write-Host ("RESULT.md exists: " + (Test-Path $CompletedResult))

if (Test-Path $CompletedLog) {
    Write-Host ""
    Write-Host "--- EXECUTION_LOG.jsonl ---"
    Get-Content -Raw $CompletedLog
}

Write-Host ""
Write-Host "Done."
