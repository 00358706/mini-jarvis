# inspect_file end-to-end smoke test (propose -> approve -> execute).

$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

$PlanId = "manual_inspect_file_001"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ActivePath = Join-Path $RepoRoot "data\workspaces\active\$PlanId"
$RejectedPath = Join-Path $RepoRoot "data\workspaces\rejected\$PlanId"
$CompletedPath = Join-Path $RepoRoot "data\workspaces\completed\$PlanId"
$CompletedLog = Join-Path $CompletedPath "EXECUTION_LOG.jsonl"
$CompletedResult = Join-Path $CompletedPath "RESULT.md"

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
    summary           = "inspect_file read-only maintainer test"
    agent             = "project_maintainer_agent"
    risk              = "level_0"
    requires_approval = $true
    steps             = @(
        @{
            step_id     = "step_1"
            tool        = "inspect_file"
            args        = @{ path = "README.md" }
            description = "Read repository README"
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
Write-Host ("status: " + $Propose.status)
Write-Host ("plan_id: " + $Propose.plan_id)
if ($Propose.status -ne "pending_approval") {
    throw "Expected pending_approval from /plans/propose, got '$($Propose.status)'."
}

Write-Host ""
Write-Host "--- POST /plans/$PlanId/approve ---"
$Approve = Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/approve" -Method Post -Headers $Headers
Write-Host ("status: " + $Approve.status)
Write-Host ("plan_id: " + $Approve.plan_id)
if ($Approve.status -ne "approved") {
    throw "Expected approved from /plans/{id}/approve, got '$($Approve.status)'."
}

Write-Host ""
Write-Host "--- POST /plans/$PlanId/execute ---"
$Execute = Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/execute" -Method Post -Headers $Headers
if ($Execute.status -ne "executed_success") {
    $StepFailure = $Execute.steps | Select-Object -First 1
    if ($StepFailure) {
        Write-Host "--- inspect_file failure detail ---"
        Write-Host ("step_status: " + $StepFailure.status)
        Write-Host ("tool_error: " + $StepFailure.result.error)
    }
    throw "Expected executed_success from /plans/{id}/execute, got '$($Execute.status)'."
}

Write-Host ""
Write-Host "--- Completed workspace checks ---"
Write-Host ("completed path exists: " + (Test-Path $CompletedPath))
Write-Host ("EXECUTION_LOG.jsonl exists: " + (Test-Path $CompletedLog))
Write-Host ("RESULT.md exists: " + (Test-Path $CompletedResult))

if (-not (Test-Path $CompletedPath)) {
    throw "Completed workspace path missing: $CompletedPath"
}
if (-not (Test-Path $CompletedLog)) {
    throw "Missing EXECUTION_LOG.jsonl: $CompletedLog"
}
if (-not (Test-Path $CompletedResult)) {
    throw "Missing RESULT.md: $CompletedResult"
}

$Step1 = $Execute.steps | Select-Object -First 1
if (-not $Step1) {
    throw "Execute response did not include a step result."
}

$ToolData = $Step1.result.data
Write-Host ""
Write-Host "--- inspect_file execute summary ---"
Write-Host ("execute status: " + $Execute.status)
Write-Host ("tool: " + $Step1.tool)
Write-Host ("status: " + $Step1.status)
Write-Host ("result success: " + $Step1.result.success)
Write-Host ("path: " + $ToolData.path)
Write-Host ("size_bytes: " + $ToolData.size_bytes)
if ($ToolData.content) {
    $previewLength = [Math]::Min(200, $ToolData.content.Length)
    Write-Host ("content_preview: " + $ToolData.content.Substring(0, $previewLength))
}

Write-Host ""
Write-Host "Done."
