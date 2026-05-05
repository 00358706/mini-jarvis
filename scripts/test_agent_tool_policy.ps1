# Agent tool-policy smoke test for /plans/propose.

$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

$AllowedPlanId = "manual_agent_policy_allowed_001"
$BlockedPlanId = "manual_agent_policy_blocked_001"

function New-PlanBody {
    param(
        [string]$PlanId,
        [string]$ToolName
    )
    return @{
        plan_id           = $PlanId
        summary           = "Agent tool policy smoke test"
        agent             = "media_agent"
        risk              = "level_0"
        requires_approval = $true
        steps             = @(
            @{
                step_id     = "step_1"
                tool        = $ToolName
                args        = if ($ToolName -eq "radarr_search") { @{ title = "Inception" } } else { @{} }
                description = "Policy check step"
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
}

Write-Host "Base URL: $BaseUrl"

Write-Host ""
Write-Host "--- Case 1: allowed tool (radarr_search) ---"
$BodyAllowed = New-PlanBody -PlanId $AllowedPlanId -ToolName "radarr_search"
$RespAllowed = Invoke-RestMethod -Uri "$BaseUrl/plans/propose" -Method Post -Headers $Headers -Body $BodyAllowed
$RespAllowed | ConvertTo-Json -Depth 10

if ($RespAllowed.status -eq "pending_approval") {
    Write-Host "Allowed case accepted as pending approval."
    # Cleanup pending item if created.
    $RejectBody = @{ reason = "agent tool policy test cleanup" } | ConvertTo-Json
    Invoke-RestMethod -Uri "$BaseUrl/plans/$AllowedPlanId/reject" -Method Post -Headers $Headers -Body $RejectBody | Out-Null
} else {
    Write-Host "WARNING: allowed case did not return pending_approval."
}

Write-Host ""
Write-Host "--- Case 2: candidate blocked tool (sabnzbd_pause) ---"
$BodyBlocked = New-PlanBody -PlanId $BlockedPlanId -ToolName "sabnzbd_pause"
$BlockedRejected = $false
try {
    $RespBlocked = Invoke-RestMethod -Uri "$BaseUrl/plans/propose" -Method Post -Headers $Headers -Body $BodyBlocked
    $RespBlocked | ConvertTo-Json -Depth 10
    Write-Host "ERROR: blocked case was accepted unexpectedly."
    # Cleanup pending item if created.
    if ($RespBlocked.status -eq "pending_approval") {
        $RejectBody2 = @{ reason = "agent tool policy test cleanup" } | ConvertTo-Json
        Invoke-RestMethod -Uri "$BaseUrl/plans/$BlockedPlanId/reject" -Method Post -Headers $Headers -Body $RejectBody2 | Out-Null
    }
} catch {
    $resp = $_.Exception.Response
    if ($resp -and $resp.StatusCode.value__ -eq 400) {
        $BlockedRejected = $true
        Write-Host "Blocked case rejected with HTTP 400 (expected in strict mode)."
    } else {
        throw
    }
}

if ($BlockedRejected) {
    Write-Host "Case 2 result: PASS (rejection is expected)."
} else {
    Write-Host "Case 2 result: FAIL (expected rejection)."
}

Write-Host ""
Write-Host "Done."
