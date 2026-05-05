# propose_patch end-to-end smoke test (propose -> approve -> execute).

$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

$PlanId = "manual_propose_patch_001"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ReadmePath = Join-Path $RepoRoot "README.md"
$ReadmeBefore = Get-Content -Raw $ReadmePath
$ActivePath = Join-Path $RepoRoot "data\workspaces\active\$PlanId"
$RejectedPath = Join-Path $RepoRoot "data\workspaces\rejected\$PlanId"
$CompletedPath = Join-Path $RepoRoot "data\workspaces\completed\$PlanId"
$CompletedLog = Join-Path $CompletedPath "EXECUTION_LOG.jsonl"
$CompletedResult = Join-Path $CompletedPath "RESULT.md"

foreach ($p in @($ActivePath, $RejectedPath, $CompletedPath)) {
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p
        Write-Host "Removed old test path: $p"
    }
}

$PatchText = @"
--- a/README.md
+++ b/README.md
@@ -1,3 +1,3 @@
-# mini-jarvis (Agentic Gateway)
+# mini-jarvis (Agentic Gateway OS)
 
 A small local-first gateway.
"@

$PlanBody = @{
    plan_id           = $PlanId
    summary           = "propose_patch proposal-only smoke test"
    agent             = "project_maintainer_agent"
    risk              = "level_0"
    requires_approval = $true
    steps             = @(
        @{
            step_id     = "step_1"
            tool        = "propose_patch"
            args        = @{
                path    = "README.md"
                summary = "Suggest a small README wording change"
                patch   = $PatchText
            }
            description = "Create a proposal-only patch artifact"
        }
    )
    limits            = @{
        max_tool_calls      = 6
        max_runtime_seconds = 90
        allow_cloud         = $false
        allow_delete        = $false
    }
    status            = "proposed"
} | ConvertTo-Json -Depth 8

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
        Write-Host ("step_status: " + $StepFailure.status)
        Write-Host ("tool_error: " + $StepFailure.result.error)
    }
    throw "Expected executed_success from /plans/{id}/execute, got '$($Execute.status)'."
}

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
Write-Host "--- propose_patch execute summary ---"
Write-Host ("execute status: " + $Execute.status)
Write-Host ("tool: " + $Step1.tool)
Write-Host ("step status: " + $Step1.status)
Write-Host ("proposal_only: " + $ToolData.proposal_only)
Write-Host ("applied: " + $ToolData.applied)
Write-Host ("summary: " + $ToolData.summary)
if ($ToolData.patch) {
    $previewLength = [Math]::Min(300, $ToolData.patch.Length)
    Write-Host ("patch_preview: " + $ToolData.patch.Substring(0, $previewLength))
}

$ReadmeAfter = Get-Content -Raw $ReadmePath
if ($ReadmeBefore -ne $ReadmeAfter) {
    throw "README.md was modified by propose_patch, but tool must be proposal-only."
}
Write-Host "README.md unchanged: True"
