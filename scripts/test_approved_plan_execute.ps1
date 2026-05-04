# Manual test: propose → approve → execute for one approved plan (read-only radarr_search).
# If Radarr is up, the step may succeed; if not, you may still see a sandbox/tool error in the step result.

$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

$PlanId = "manual_execute_001"

$PlanBody = @{
    plan_id             = $PlanId
    summary             = "Approved-plan execute script (read-only)"
    agent               = "media_agent"
    risk                = "level_0"
    requires_approval   = $true
    steps               = @(
        @{
            step_id     = "step_1"
            tool        = "radarr_search"
            args        = @{ title = "Inception" }
            description = "Read-only Radarr lookup"
        }
    )
    limits              = @{
        max_tool_calls       = 6
        max_runtime_seconds  = 90
        allow_cloud          = $false
        allow_delete         = $false
    }
    status              = "proposed"
} | ConvertTo-Json -Depth 6

Write-Host "Base URL: $BaseUrl"
Write-Host "Plan id:  $PlanId"

Invoke-RestMethod -Uri "$BaseUrl/plans/propose" -Method Post -Headers $Headers -Body $PlanBody | Out-Null
Write-Host "Proposed (pending approval)."

Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/approve" -Method Post -Headers $Headers | Out-Null
Write-Host "Approved."

$ExecuteResponse = Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/execute" -Method Post -Headers $Headers

Write-Host ""
Write-Host "--- POST /plans/$PlanId/execute response ---"
$ExecuteResponse | ConvertTo-Json -Depth 12

Write-Host ""
Write-Host "--- GET /plans/pending (plan should not be listed) ---"
$Pending = Invoke-RestMethod -Uri "$BaseUrl/plans/pending" -Method Get -Headers $Headers
$Pending | ConvertTo-Json -Depth 6

if ($Pending.plans -contains $PlanId) {
    Write-Host "WARNING: $PlanId still appears in pending (unexpected after approve/execute)."
} else {
    Write-Host "OK: $PlanId is not in pending."
}

Write-Host ""
Write-Host "Done."
