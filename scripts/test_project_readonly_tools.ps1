# Project maintainer readonly tools smoke test (list_project_files + search_repo).

$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }

$Headers = @{
    "X-API-Key"    = $ApiKey
    "Content-Type" = "application/json"
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Propose-Approve-Execute {
    param(
        [string]$PlanId,
        [string]$ToolName,
        [hashtable]$ToolArgs,
        [string]$Description
    )

    $Body = @{
        plan_id           = $PlanId
        summary           = "project readonly tools test"
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
    } | ConvertTo-Json -Depth 8

    Write-Host ""
    Write-Host ("--- POST /plans/propose ({0}) ---" -f $ToolName)
    $Propose = Invoke-RestMethod -Uri "$BaseUrl/plans/propose" -Method Post -Headers $Headers -Body $Body
    Assert-True ($Propose.status -eq "pending_approval") "Expected pending_approval for $ToolName."

    Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/approve" -Method Post -Headers $Headers | Out-Null
    $Exec = Invoke-RestMethod -Uri "$BaseUrl/plans/$PlanId/execute" -Method Post -Headers $Headers
    Assert-True ($Exec.status -eq "executed_success") "Expected executed_success for $ToolName, got '$($Exec.status)'."
    return $Exec
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
    } catch { return "" }
    return ""
}

$Plan1 = "manual_project_readonly_list_001"
$Plan2 = "manual_project_readonly_search_001"
$Plan3 = "manual_project_readonly_traversal_001"

Write-Host "Base URL: $BaseUrl"

# 1) list_project_files
$Exec1 = Propose-Approve-Execute `
    -PlanId $Plan1 `
    -ToolName "list_project_files" `
    -ToolArgs @{
        root = "."
        max_results = 200
    } `
    -Description "List repository files"

$Step1 = $Exec1.steps | Select-Object -First 1
$Files = $Step1.result.data.files
Assert-True ($Files.Count -gt 0) "Expected non-empty files list."
$Paths = $Files | ForEach-Object { $_.path }
Assert-True (($Paths -contains "main.py") -or ($Paths -contains "workspace.py") -or ($Paths -contains "README.md")) "Expected common repo files in list_project_files result."
Write-Host "list_project_files returned expected repo paths."

# 2) search_repo for PATCH_PROPOSAL.md
$Exec2 = Propose-Approve-Execute -PlanId $Plan2 -ToolName "search_repo" -ToolArgs @{
    query = "PATCH_PROPOSAL.md"
    root = "."
    max_results = 50
    max_file_size_bytes = 100000
} -Description "Search repository for PATCH_PROPOSAL.md references"

$Step2 = $Exec2.steps | Select-Object -First 1
$Matches = $Step2.result.data.matches
Assert-True ($Matches.Count -ge 1) "Expected at least one match for PATCH_PROPOSAL.md."
Write-Host "search_repo returned matches for PATCH_PROPOSAL.md."

# 3) search_repo for Workspace Review API text
$Exec3 = Propose-Approve-Execute -PlanId ("manual_project_readonly_search_002") -ToolName "search_repo" -ToolArgs @{
    query = "Workspace Review API"
    root = "."
    max_results = 20
    max_file_size_bytes = 100000
} -Description "Search repository for Workspace Review API"

$Step3 = $Exec3.steps | Select-Object -First 1
$Matches2 = $Step3.result.data.matches
Assert-True ($Matches2.Count -ge 1) "Expected at least one match for 'Workspace Review API'."
Write-Host "search_repo returned matches for Workspace Review API."

# 4) traversal should be rejected by tool validation (expect executed_with_errors)
Write-Host ""
Write-Host "--- traversal rejection (expect error) ---"
$BodyBad = @{
    plan_id           = $Plan3
    summary           = "project readonly tools traversal rejection"
    agent             = "project_maintainer_agent"
    risk              = "level_0"
    requires_approval = $true
    steps             = @(
        @{
            step_id     = "step_1"
            tool        = "list_project_files"
            args        = @{ root = ".." }
            description = "Attempt traversal"
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

$ProposeBad = Invoke-RestMethod -Uri "$BaseUrl/plans/propose" -Method Post -Headers $Headers -Body $BodyBad
Assert-True ($ProposeBad.status -eq "pending_approval") "Expected pending_approval for traversal plan propose."
Invoke-RestMethod -Uri "$BaseUrl/plans/$Plan3/approve" -Method Post -Headers $Headers | Out-Null
$ExecBad = Invoke-RestMethod -Uri "$BaseUrl/plans/$Plan3/execute" -Method Post -Headers $Headers
Assert-True ($ExecBad.status -eq "executed_with_errors") "Expected executed_with_errors for traversal attempt."
$ErrMsg = ($ExecBad.steps | Select-Object -First 1).result.error
Assert-True ($ErrMsg -match "traversal|inside the repository root") "Expected traversal-related error message."
Write-Host "Traversal attempt rejected as expected."

Write-Host ""
Write-Host "Done."

