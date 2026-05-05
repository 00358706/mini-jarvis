# Workspace review API smoke test (read-only).

$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

$PlanId = "manual_workspace_review_" + (Get-Date -Format "yyyyMMdd_HHmmss")

function Invoke-Get {
    param([string]$Uri)
    return Invoke-RestMethod -Uri $Uri -Method Get -Headers $Headers
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
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

Write-Host "Base URL: $BaseUrl"
Write-Host "Plan id :  $PlanId"

Write-Host ""
Write-Host "--- POST /plans/propose ---"
$PlanBody = @{
    plan_id           = $PlanId
    summary           = "Workspace review API test"
    agent             = "project_maintainer_agent"
    risk              = "level_0"
    requires_approval = $true
    steps             = @(
        @{
            step_id     = "step_1"
            tool        = "inspect_file"
            args        = @{ path = "README.md" }
            description = "Read repository README (review test)"
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

$Propose = Invoke-RestMethod -Uri "$BaseUrl/plans/propose" -Method Post -Headers $Headers -Body $PlanBody
Write-Host ("propose status: " + $Propose.status)
Assert-True ($Propose.status -eq "pending_approval") "Expected pending_approval from /plans/propose."

Write-Host ""
Write-Host "--- GET /workspaces?state=active ---"
$ActiveList = Invoke-Get -Uri "$BaseUrl/workspaces?state=active"
Write-Host ""
Write-Host "--- DEBUG active workspace response ---"
$ActiveList | ConvertTo-Json -Depth 20 | Write-Host
Write-Host "--- DEBUG active response properties ---"
$ActiveList.PSObject.Properties.Name | ForEach-Object { Write-Host $_ }
$ActiveMatches = @($ActiveList.workspaces | Where-Object { $_.task_id -eq $PlanId })
$InList = $ActiveMatches.Count -gt 0
Assert-True $InList "Plan id '$PlanId' not found in /workspaces?state=active."
Write-Host ("active workspace present: " + $true)

Write-Host ""
Write-Host ("--- GET /workspaces/active/{0} ---" -f $PlanId)
$ActiveSummary = Invoke-Get -Uri "$BaseUrl/workspaces/active/$PlanId"
Assert-True ($ActiveSummary.state -eq "active") "Expected state=active in workspace summary."
Assert-True ($ActiveSummary.files.present -contains "PLAN.json") "PLAN.json missing from workspace summary."
Assert-True ($ActiveSummary.files.present -contains "POLICY_DECISION.json") "POLICY_DECISION.json missing from workspace summary."
Write-Host ("workspace files present include PLAN.json and POLICY_DECISION.json.")

Write-Host ""
Write-Host ("--- GET /workspaces/active/{0}/files/PLAN.json ---" -f $PlanId)
$PlanFile = Invoke-Get -Uri "$BaseUrl/workspaces/active/$PlanId/files/PLAN.json"
Assert-True ($PlanFile.exists -eq $true) "Expected PLAN.json to exist."
Assert-True ($PlanFile.content_type -eq "json") "Expected content_type=json for PLAN.json."

try {
    $ParsedPlan = $PlanFile.content | ConvertFrom-Json
    Assert-True ($ParsedPlan.plan_id -eq $PlanId) "Parsed PLAN.json.plan_id does not match."
} catch {
    throw "PLAN.json content was not valid JSON."
}
Write-Host "PLAN.json readable and parseable."

Write-Host ""
Write-Host "--- POST /plans/{id}/approve ---"
$Approve = Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/approve" -Method Post -Headers $Headers
Write-Host ("approve status: " + $Approve.status)
Assert-True ($Approve.status -eq "approved") "Expected approved from /plans/{id}/approve."

Write-Host ""
Write-Host "--- POST /plans/{id}/execute ---"
$Execute = Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/execute" -Method Post -Headers $Headers
Write-Host ("execute status: " + $Execute.status)
Assert-True ($Execute.status -eq "executed_success") "Expected executed_success from /plans/{id}/execute."

Write-Host ""
Write-Host "--- GET /workspaces?state=completed ---"
$CompletedList = Invoke-Get -Uri "$BaseUrl/workspaces?state=completed"
$CompletedMatches = @($CompletedList.workspaces | Where-Object { $_.task_id -eq $PlanId })
$InCompletedList = $CompletedMatches.Count -gt 0
Assert-True $InCompletedList "Plan id '$PlanId' not found in /workspaces?state=completed."
Write-Host "completed workspace present."

Write-Host ""
Write-Host ("--- GET /workspaces/completed/{0}/files/RESULT.md ---" -f $PlanId)
$ResultFile = Invoke-Get -Uri "$BaseUrl/workspaces/completed/$PlanId/files/RESULT.md"
Assert-True ($ResultFile.exists -eq $true) "Expected RESULT.md to exist in completed workspace."
Assert-True ($ResultFile.content_type -eq "markdown") "Expected content_type=markdown for RESULT.md."
Write-Host "RESULT.md readable."

Write-Host ""
Write-Host "--- Invalid filename should be rejected (expect HTTP 400) ---"
try {
    $InvalidUri = "$BaseUrl/workspaces/completed/$PlanId/files/README.md.bak"
    Invoke-RestMethod -Uri $InvalidUri -Method Get -Headers $Headers | Out-Null
    throw "Invalid filename request unexpectedly succeeded."
} catch {
    $code = Get-HttpStatusCode $_
    Write-Host ("invalid filename HTTP status: " + $code)
    if ($code -eq 400) {
        Write-Host "Invalid filename rejected as expected (HTTP 400)."
    } else {
        throw "Invalid filename did not fail with HTTP 400."
    }
}

Write-Host ""
Write-Host "--- Filename traversal should be rejected (accept HTTP 400 or 404) ---"
try {
    # Try to route through the same endpoint by keeping traversal inside one path segment.
    $TraversalUri = "$BaseUrl/workspaces/completed/$PlanId/files/%2e%2e%2fREADME.md"
    Invoke-RestMethod -Uri $TraversalUri -Method Get -Headers $Headers | Out-Null
    throw "Traversal request unexpectedly succeeded."
} catch {
    $code = Get-HttpStatusCode $_
    Write-Host ("traversal HTTP status: " + $code)
    if ($code -eq 400 -or $code -eq 404) {
        Write-Host "Traversal rejected as expected."
    } else {
        throw "Traversal did not fail with HTTP 400/404."
    }
}

Write-Host ""
Write-Host "Done."

