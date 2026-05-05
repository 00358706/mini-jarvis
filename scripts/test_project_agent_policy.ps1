# Project maintainer strict agent-policy smoke test for /plans/propose.

$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

$MissingToolPlanId = "manual_project_agent_missing_tool_001"
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
Remove-TestWorkspacePaths -PlanId $MissingToolPlanId
Remove-TestWorkspacePaths -PlanId $ForbiddenToolPlanId

Write-Host ""
Write-Host "--- Case 1: strict-allowed but likely missing registry install (inspect_file) ---"
$BodyMissing = New-PlanBody -PlanId $MissingToolPlanId -ToolName "inspect_file" -ToolArgs @{ path = "README.md" }
try {
    $RespMissing = Invoke-RestMethod -Uri "$BaseUrl/plans/propose" -Method Post -Headers $Headers -Body $BodyMissing
    $RespMissing | ConvertTo-Json -Depth 10
    throw "Case 1 failed. Expected likely HTTP 400 policy_rejected due to missing registry install, but request succeeded with status '$($RespMissing.status)'."
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
            ($body -match 'not installed') -or
            ($body -match 'unknown tool') -or
            ($body -match 'policy_rejected') -or
            ($body -match 'registry') -or
            ($exceptionMessage -match '400')
        )
        if ($ok) {
            Write-Host "Case 1 passed: safe failure for missing/uninstalled maintainer tool."
        } else {
            throw "Case 1 failed. Received HTTP 400 but did not match expected safe-failure markers."
        }
    } else {
        throw
    }
}

Write-Host ""
Write-Host "--- Case 2: strict-forbidden tool (radarr_search) ---"
$BodyForbidden = New-PlanBody -PlanId $ForbiddenToolPlanId -ToolName "radarr_search" -ToolArgs @{ title = "Inception" }
try {
    $RespForbidden = Invoke-RestMethod -Uri "$BaseUrl/plans/propose" -Method Post -Headers $Headers -Body $BodyForbidden
    $RespForbidden | ConvertTo-Json -Depth 10
    throw "Case 2 failed. Expected HTTP 400 policy_rejected for strict allowlist block, but request succeeded with status '$($RespForbidden.status)'."
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
