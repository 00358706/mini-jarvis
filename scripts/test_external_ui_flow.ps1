# External UI/client flow smoke test.
#
# This script simulates a UI client using gateway endpoints only. It does not
# call tools, sandbox code, Python modules, or any direct tool endpoint.

$ErrorActionPreference = "Stop"

$BaseUrl = if ($env:MINI_JARVIS_BASE_URL) { $env:MINI_JARVIS_BASE_URL } else { "http://127.0.0.1:8000" }
$ApiKey = if ($env:MINI_JARVIS_API_KEY) {
    $env:MINI_JARVIS_API_KEY
} elseif ($env:GATEWAY_API_KEY) {
    $env:GATEWAY_API_KEY
} else {
    "change-me-before-use"
}

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

$ClientPaths = New-Object System.Collections.Generic.List[string]

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Limit-Text {
    param([string]$Text, [int]$Max = 700)
    if ($null -eq $Text) { return "" }
    if ($Text.Length -le $Max) { return $Text }
    return ($Text.Substring(0, $Max) + "`n...(truncated)")
}

function Invoke-Gateway {
    param(
        [string]$Method,
        [string]$Path,
        [object]$Body = $null,
        [bool]$Auth = $true
    )

    $ClientPaths.Add($Path) | Out-Null
    $uri = $BaseUrl.TrimEnd("/") + $Path

    if ($null -ne $Body) {
        $json = $Body | ConvertTo-Json -Depth 12
        if ($Auth) {
            return Invoke-RestMethod -Uri $uri -Method $Method -Headers $Headers -Body $json
        }
        return Invoke-RestMethod -Uri $uri -Method $Method -Body $json -ContentType "application/json"
    }

    if ($Auth) {
        return Invoke-RestMethod -Uri $uri -Method $Method -Headers $Headers
    }
    return Invoke-RestMethod -Uri $uri -Method $Method
}

function Write-CompactReview {
    param([object]$Compact)

    $step = $null
    if ($Compact.steps -and $Compact.steps.Count -gt 0) {
        $step = $Compact.steps[0]
    }

    $argsPreview = ""
    if ($step -and $step.args) {
        $argsPreview = Limit-Text (($step.args | ConvertTo-Json -Depth 8 -Compress) -as [string]) 300
    }

    Write-Host ("  plan_id:          " + $Compact.task_id)
    Write-Host ("  state:            " + $Compact.state)
    Write-Host ("  agent:            " + $Compact.agent)
    Write-Host ("  proposed_tool:    " + $(if ($step) { $step.tool } else { "n/a" }))
    Write-Host ("  proposed_args:    " + $(if ($argsPreview) { $argsPreview } else { "{}" }))
    Write-Host ("  policy.allowed:   " + $Compact.policy.allowed)
    Write-Host ("  approval_status:  " + $(if ($Compact.approval_status) { $Compact.approval_status } else { "n/a" }))
    Write-Host ("  execution.status: " + $(if ($Compact.execution.status) { $Compact.execution.status } else { "not_started" }))
    Write-Host ("  execution.logs:   " + $Compact.execution.log_count)
}

Write-Host "External UI/client flow smoke test"
Write-Host ("Base URL: " + $BaseUrl)

Write-Host ""
Write-Host "1. Health check"
$Health = Invoke-Gateway -Method Get -Path "/health" -Auth $false
Assert-True ($Health.status -eq "ok") "Expected /health status=ok."
Write-Host "  OK"

Write-Host ""
Write-Host "2. Propose via /plans/from-message"
$PlanId = "external_ui_flow_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$Proposal = Invoke-Gateway -Method Post -Path "/plans/from-message" -Body @{
    message = "list project files"
    agent   = "project_maintainer_agent"
    plan_id = $PlanId
}
Assert-True ($Proposal.status -eq "pending_approval") "Expected pending_approval from /plans/from-message."
Assert-True ([string]::IsNullOrWhiteSpace($Proposal.plan_id) -eq $false) "Expected plan_id in proposal response."
$PlanId = [string]$Proposal.plan_id
Write-Host ("  plan_id: " + $PlanId)

Write-Host ""
Write-Host "3. Pending index contains plan"
$Pending = Invoke-Gateway -Method Get -Path "/plans/pending"
$PendingIds = @($Pending.plans)
Assert-True ($PendingIds -contains $PlanId) "Expected pending index to contain $PlanId."
Write-Host "  OK"

Write-Host ""
Write-Host "4. Compact active review"
$ActiveCompact = Invoke-Gateway -Method Get -Path "/workspaces/active/$PlanId/compact"
Write-CompactReview $ActiveCompact
Assert-True ($ActiveCompact.state -eq "active") "Expected active compact state."
Assert-True ($ActiveCompact.agent -eq "project_maintainer_agent") "Expected project_maintainer_agent."
Assert-True ($ActiveCompact.steps[0].tool -eq "list_project_files") "Expected proposed tool list_project_files."
Assert-True ($ActiveCompact.execution.log_count -eq 0) "Expected no execution before approval."

Write-Host ""
Write-Host "5. Approve as a separate explicit client command"
$Approve = Invoke-Gateway -Method Post -Path "/plans/$PlanId/approve"
Assert-True ($Approve.status -eq "approved") "Expected approve status=approved."
Write-Host "  approved; no execute command has been sent"

Write-Host ""
Write-Host "6. Verify approval did not execute"
$AfterApprove = Invoke-Gateway -Method Get -Path "/workspaces/active/$PlanId/compact"
Write-CompactReview $AfterApprove
Assert-True ($AfterApprove.execution.log_count -eq 0) "Approve must not execute tools."
Assert-True ($AfterApprove.execution.has_result -eq $false) "Approve must not create a result."

Write-Host ""
Write-Host "7. Execute as a separate explicit client command"
$Execute = Invoke-Gateway -Method Post -Path "/plans/$PlanId/execute"
Assert-True (($Execute.status -eq "executed_success") -or ($Execute.status -eq "executed_with_errors")) "Expected executed status."
Write-Host ("  execute status: " + $Execute.status)

Write-Host ""
Write-Host "8. Compact completed review"
$CompletedCompact = Invoke-Gateway -Method Get -Path "/workspaces/completed/$PlanId/compact"
Write-CompactReview $CompletedCompact
Assert-True ($CompletedCompact.state -eq "completed") "Expected completed compact state."
Assert-True ($CompletedCompact.execution.log_count -ge 1) "Expected execution log entries after execute."

Write-Host ""
Write-Host "9. Completed RESULT.md preview"
$ResultFile = Invoke-Gateway -Method Get -Path "/workspaces/completed/$PlanId/files/RESULT.md"
Assert-True ($ResultFile.exists -eq $true) "Expected completed RESULT.md to exist."
$Preview = Limit-Text ([string]$ResultFile.content) 700
Write-Host $Preview

Write-Host ""
Write-Host "10. Client did not use direct tool endpoints"
$DirectToolCalls = @($ClientPaths | Where-Object { $_ -like "/tools*" })
Assert-True ($DirectToolCalls.Count -eq 0) "External UI smoke test must not call direct /tools endpoints."
Write-Host "  OK"

Write-Host ""
Write-Host "Done."
