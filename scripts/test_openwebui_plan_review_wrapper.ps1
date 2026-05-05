# Open WebUI plan review wrapper smoke test.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ReviewWrapper = Join-Path $RepoRoot "integrations\openwebui\mini_jarvis_plan_review.py"

$BaseUrl = if ($env:MINI_JARVIS_BASE_URL) { $env:MINI_JARVIS_BASE_URL } else { "http://127.0.0.1:8000" }
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$env:MINI_JARVIS_BASE_URL = $BaseUrl
$env:MINI_JARVIS_API_KEY = $ApiKey

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

function Assert-Contains {
    param([string]$Text, [string]$Needle, [string]$Message)
    if ($Text -notmatch [Regex]::Escape($Needle)) {
        throw $Message
    }
}

function Assert-Matches {
    param([string]$Text, [string]$Pattern, [string]$Message)
    if ($Text -notmatch $Pattern) {
        Write-Host "--- ASSERTION FAILED OUTPUT ---"
        Write-Host $Text
        throw $Message
    }
}

function Assert-ExitNonZero {
    param([int]$ExitCode, [string]$Message)
    if ($ExitCode -eq 0) {
        throw $Message
    }
}

Write-Host "--- Create plan via POST /plans/from-message ---"
$PlanId = "manual_review_wrapper_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$Body = @{
    message = "list project files"
    agent   = "project_maintainer_agent"
    plan_id = $PlanId
} | ConvertTo-Json -Depth 6

$Resp = Invoke-RestMethod -Uri "$BaseUrl/plans/from-message" -Method Post -Headers $Headers -Body $Body
if ($Resp.status -ne "pending_approval") {
    throw "Expected pending_approval from /plans/from-message."
}

Write-Host ""
Write-Host "--- show <plan_id> ---"
$Show1 = python $ReviewWrapper show $PlanId | Out-String
Write-Host $Show1
Assert-Contains $Show1 "state: active" "Expected active state in show output."
Assert-Contains $Show1 "tool: list_project_files" "Expected list_project_files in show output."

Write-Host ""
Write-Host "--- approve without --confirm should refuse ---"
$ApproveNo = python $ReviewWrapper approve $PlanId | Out-String
$Exit1 = $LASTEXITCODE
Write-Host $ApproveNo
Assert-ExitNonZero $Exit1 "Approve without --confirm should be nonzero."
Assert-Contains $ApproveNo "Refusing to approve without --confirm" "Expected refusal message for approve."

Write-Host ""
Write-Host "--- approve with --confirm ---"
$ApproveYes = python $ReviewWrapper approve $PlanId --confirm | Out-String
$Exit2 = $LASTEXITCODE
Write-Host $ApproveYes
if ($Exit2 -ne 0) { throw "Approve with --confirm failed." }
Assert-Contains $ApproveYes "approve http_status: 200" "Expected approve http_status: 200 in approve output."
Assert-Matches $ApproveYes '"status"\s*:\s*"approved"' "Expected status=approved JSON in approve output."

Write-Host ""
Write-Host "--- execute without --confirm should refuse ---"
$ExecNo = python $ReviewWrapper execute $PlanId | Out-String
$Exit3 = $LASTEXITCODE
Write-Host $ExecNo
Assert-ExitNonZero $Exit3 "Execute without --confirm should be nonzero."
Assert-Contains $ExecNo "Refusing to execute without --confirm" "Expected refusal message for execute."

Write-Host ""
Write-Host "--- execute with --confirm ---"
$ExecYes = python $ReviewWrapper execute $PlanId --confirm | Out-String
$Exit4 = $LASTEXITCODE
Write-Host $ExecYes
if ($Exit4 -ne 0) { throw "Execute with --confirm failed." }
Assert-Contains $ExecYes "execute http_status: 200" "Expected execute http_status: 200 in execute output."
Assert-Contains $ExecYes "executed_success" "Expected executed_success in execute output."

Write-Host ""
Write-Host "--- show <plan_id> (completed) ---"
$Show2 = python $ReviewWrapper show $PlanId | Out-String
Write-Host $Show2
Assert-Contains $Show2 "state: completed" "Expected completed state after execution."
Assert-Contains $Show2 "RESULT.md:" "Expected result text in completed show output."

Write-Host ""
Write-Host "Done."

