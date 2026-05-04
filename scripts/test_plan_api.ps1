# Manual checks for the Plan API. Expects the gateway running locally (e.g. python main.py).
# Nothing here runs tools or the sandbox—only HTTP calls.

$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$Headers = @{
    "X-API-Key"        = $ApiKey
    "Content-Type"     = "application/json"
}

# radarr_search is seeded as installed in registry.py; if your registry differs, policy may return 400.
$PlanBody = @{
    plan_id             = "manual_test_001"
    summary             = "PowerShell script smoke test"
    agent               = "media_agent"
    risk                = "level_0"
    requires_approval   = $true
    steps               = @(
        @{
            step_id     = "step_1"
            tool        = "radarr_search"
            args        = @{ title = "Inception" }
            description = "Read-only search step for API test"
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

function Show-Response {
    param([string]$Label, [object]$Data)
    Write-Host ""
    Write-Host "--- $Label ---"
    if ($null -eq $Data) { Write-Host "(no body)" } else { $Data | ConvertTo-Json -Depth 8 }
}

Write-Host "Base URL: $BaseUrl"

Show-Response "GET /health" (Invoke-RestMethod -Uri "$BaseUrl/health" -Method Get)

Show-Response "GET /plans/pending (before)" `
    (Invoke-RestMethod -Uri "$BaseUrl/plans/pending" -Method Get -Headers $Headers)

Show-Response "POST /plans/propose" `
    (Invoke-RestMethod -Uri "$BaseUrl/plans/propose" -Method Post -Headers $Headers -Body $PlanBody)

Show-Response "GET /plans/pending (after propose)" `
    (Invoke-RestMethod -Uri "$BaseUrl/plans/pending" -Method Get -Headers $Headers)

$PlanId = "manual_test_001"
Show-Response "GET /plans/pending/$PlanId" `
    (Invoke-RestMethod -Uri "$BaseUrl/plans/pending/$PlanId" -Method Get -Headers $Headers)

$RejectBody = @{ reason = "manual test cleanup" } | ConvertTo-Json
Show-Response "POST /plans/$PlanId/reject" `
    (Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/reject" -Method Post -Headers $Headers -Body $RejectBody)

Show-Response "GET /plans/pending (after reject)" `
    (Invoke-RestMethod -Uri "$BaseUrl/plans/pending" -Method Get -Headers $Headers)

Write-Host ""
Write-Host "Done."
