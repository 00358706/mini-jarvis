# Project maintainer strict agent-policy smoke test for /plans/propose.

$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

$InspectFilePlanId = "manual_project_agent_inspect_file_001"
$ForbiddenToolPlanId = "manual_project_agent_forbidden_tool_001"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Remove-TestWorkspacePaths {
    param([string]$PlanId)
    $targets = @(
        (Join-Path $RepoRoot "data\workspaces\active\$PlanId"),
        (Join-Path $RepoRoot "data\workspaces\rejected\$PlanId"),
        (Join-Path $RepoRoot "data\workspaces\completed\$PlanId")
    )
    foreach ($p in $targets) {
        if (Test-Path $p) {
            Remove-Item -Recurse -Force $p
            Write-Host "Removed old path: $p"
        }
    }
}

function New-PlanBody {
    param(
        [string]$PlanId,
        [string]$ToolName,
        [object]$ToolArgs,
        [string]$Description = "Policy check step"
    )
    return @{
        plan_id           = $PlanId
        summary           = "Project maintainer strict policy smoke test"
        agent             = "project_maintainer_agent"
        risk              = "level_0"
        requires_approval = $true
        steps             = @(
            @{
                step_id     = "step_1"
                tool        = $ToolName
                args        = $ToolArgs
                description = $Description
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

function Get-ErrorBody {
    param($ErrorRecord)
    try {
        if ($ErrorRecord.ErrorDetails -and $ErrorRecord.ErrorDetails.Message) {
            return [string]$ErrorRecord.ErrorDetails.Message
        }
        $resp = $ErrorRecord.Exception.Response
        if ($resp -and $resp.GetResponseStream) {
            $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
            return $reader.ReadToEnd()
        }
    } catch {
        return ""
    }
    return ""
}

Write-Host "Base URL: $BaseUrl"
Remove-TestWorkspacePaths -PlanId $InspectFilePlanId
Remove-TestWorkspacePaths -PlanId $ForbiddenToolPlanId

Write-Host ""
Write-Host "--- Case 1: strict-allowed registered tool (inspect_file) ---"
$BodyInspect = New-PlanBody -PlanId $InspectFilePlanId -ToolName "inspect_file" -ToolArgs @{ path = "README.md" }
try {
    $RespInspect = Invoke-RestMethod -Uri "$BaseUrl/plans/propose" -Method Post -Headers $Headers -Body $BodyInspect
    $RespInspect | ConvertTo-Json -Depth 10

    if ($RespInspect.status -ne "pending_approval") {
        throw "Case 1 failed. Expected status=pending_approval, got '$($RespInspect.status)'."
    }
    if ($RespInspect.plan_id -ne $InspectFilePlanId) {
        throw "Case 1 failed. Expected plan_id=$InspectFilePlanId, got '$($RespInspect.plan_id)'."
    }
    if (-not $RespInspect.policy -or $RespInspect.policy.allowed -ne $true) {
        throw "Case 1 failed. Expected policy.allowed=true."
    }
    Write-Host "Case 1 passed: inspect_file accepted as pending approval with policy.allowed=true."
} catch {
    $resp = $_.Exception.Response
    if ($resp -and $resp.StatusCode.value__ -eq 400) {
        $body = Get-ErrorBody $_
        Write-Host "HTTP 400 response body:"
        Write-Host $body
        throw "Case 1 failed. inspect_file should be allowed and return pending_approval."
    }
    throw
}

Write-Host ""
Write-Host "--- Case 2: strict-forbidden tool (radarr_search) ---"
$BodyForbidden = New-PlanBody -PlanId $ForbiddenToolPlanId -ToolName "radarr_search" -ToolArgs @{ title = "Inception" }
try {
    $RespForbidden = Invoke-RestMethod -Uri "$BaseUrl/plans/propose" -Method Post -Headers $Headers -Body $BodyForbidden
    $RespForbidden | ConvertTo-Json -Depth 10
    if ($RespForbidden.status -eq "pending_approval") {
        throw "Case 2 failed. Expected rejection (not pending_approval) for strict allowlist block, but got pending_approval."
    }
    throw "Case 2 failed. Expected rejection for strict allowlist block, but request succeeded with status '$($RespForbidden.status)'."
} catch {
    $resp = $_.Exception.Response
    if ($resp -and $resp.StatusCode.value__ -eq 400) {
        $body = Get-ErrorBody $_
        $exceptionMessage = [string]$_.Exception.Message
        Write-Host "HTTP 400 response body:"
        Write-Host $body
        if ([string]::IsNullOrWhiteSpace($body)) {
            Write-Host "HTTP 400 exception message:"
            Write-Host $exceptionMessage
        }
        $ok = (
            ($body -match 'not allowed by agent') -or
            ($body -match 'strict policy') -or
            ($body -match 'policy_rejected') -or
            ($exceptionMessage -match '400')
        )
        if ($ok) {
            Write-Host "Case 2 passed: strict policy blocked forbidden tool."
        } else {
            throw "Case 2 failed. Received HTTP 400 but did not match strict-policy markers."
        }
    } else {
        throw
    }
}

Write-Host ""
Write-Host "Done."
