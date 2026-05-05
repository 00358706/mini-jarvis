# Workspace route-context smoke test (propose -> reject cleanup).

$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

$PlanId = "manual_route_context_001"
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
    summary           = "Workspace route context smoke test"
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

$ActiveRoute = Join-Path $ActivePath "ROUTE.json"
$ActiveAgent = Join-Path $ActivePath "AGENT.md"
$ActiveContext = Join-Path $ActivePath "CONTEXT.md"

Write-Host ""
Write-Host "--- Active workspace files ---"
Write-Host ("ROUTE.json exists: " + (Test-Path $ActiveRoute))
Write-Host ("AGENT.md exists: " + (Test-Path $ActiveAgent))
Write-Host ("CONTEXT.md exists: " + (Test-Path $ActiveContext))

if (Test-Path $ActiveRoute) {
    Write-Host ""
    Write-Host "--- ROUTE.json ---"
    Get-Content -Raw $ActiveRoute
}

$RejectBody = @{ reason = "workspace route context test cleanup" } | ConvertTo-Json
Write-Host ""
Write-Host "--- POST /plans/$PlanId/reject ---"
$Reject = Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/reject" -Method Post -Headers $Headers -Body $RejectBody
$Reject | ConvertTo-Json -Depth 8

$RejectedRoute = Join-Path $RejectedPath "ROUTE.json"
Write-Host ""
Write-Host "--- Rejected workspace files ---"
Write-Host ("ROUTE.json exists: " + (Test-Path $RejectedRoute))

Write-Host ""
Write-Host "Done."
