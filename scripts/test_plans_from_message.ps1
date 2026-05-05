# /plans/from-message smoke test (Open WebUI friendly proposal endpoint).

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

Write-Host "Base URL: $BaseUrl"

# Case 1: list project files
$PlanId1 = "manual_from_message_list_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$Body1 = @{
    message = "list project files"
    agent   = "project_maintainer_agent"
    plan_id = $PlanId1
} | ConvertTo-Json -Depth 6

Write-Host ""
Write-Host "--- Case 1: list project files ---"
$Resp1 = Invoke-RestMethod -Uri "$BaseUrl/plans/from-message" -Method Post -Headers $Headers -Body $Body1
Assert-True ($Resp1.status -eq "pending_approval") "Expected pending_approval for case 1."
Assert-True ($Resp1.workspace.state -eq "active") "Expected workspace.state=active for case 1."

$Ws1 = Invoke-RestMethod -Uri ($BaseUrl + $Resp1.workspace.summary_url) -Method Get -Headers $Headers
Assert-True ($Ws1.plan_json.steps[0].tool -eq "list_project_files") "Expected tool=list_project_files in case 1 plan_json."
Write-Host "Case 1 OK: tool=list_project_files"

# Case 2: search repo for PATCH_PROPOSAL.md
$PlanId2 = "manual_from_message_search_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$Body2 = @{
    message = "search repo for PATCH_PROPOSAL.md"
    agent   = "project_maintainer_agent"
    plan_id = $PlanId2
} | ConvertTo-Json -Depth 6

Write-Host ""
Write-Host "--- Case 2: search repo for PATCH_PROPOSAL.md ---"
$Resp2 = Invoke-RestMethod -Uri "$BaseUrl/plans/from-message" -Method Post -Headers $Headers -Body $Body2
Assert-True ($Resp2.status -eq "pending_approval") "Expected pending_approval for case 2."

$Ws2 = Invoke-RestMethod -Uri ($BaseUrl + $Resp2.workspace.summary_url) -Method Get -Headers $Headers
Assert-True ($Ws2.plan_json.steps[0].tool -eq "search_repo") "Expected tool=search_repo in case 2 plan_json."
$Q2 = $Ws2.plan_json.steps[0].args.query
Assert-True (($Q2 -like "*PATCH_PROPOSAL.md*") -or ($Q2 -eq "PATCH_PROPOSAL.md")) "Expected args.query to include PATCH_PROPOSAL.md."
Write-Host "Case 2 OK: tool=search_repo and query includes PATCH_PROPOSAL.md"

# Case 3: unsafe phrasing "run radarr_search" should not produce radarr_search
$PlanId3 = "manual_from_message_unsafe_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$Body3 = @{
    message = "run radarr_search for Inception"
    agent   = "project_maintainer_agent"
    plan_id = $PlanId3
} | ConvertTo-Json -Depth 6

Write-Host ""
Write-Host "--- Case 3: unsafe phrasing (radarr_search) ---"
try {
    $Resp3 = Invoke-RestMethod -Uri "$BaseUrl/plans/from-message" -Method Post -Headers $Headers -Body $Body3
    if ($Resp3.status -eq "pending_approval") {
        $Ws3 = Invoke-RestMethod -Uri ($BaseUrl + $Resp3.workspace.summary_url) -Method Get -Headers $Headers
        $Tool3 = $Ws3.plan_json.steps[0].tool
        Assert-True ($Tool3 -ne "radarr_search") "Unsafe message produced radarr_search (must not)."
        Write-Host ("Case 3 OK: did not propose radarr_search (tool=" + $Tool3 + ")")
    } else {
        Write-Host ("Case 3 OK: not pending_approval (status=" + $Resp3.status + ")")
    }
} catch {
    $body = Get-ErrorBody $_
    Write-Host "Case 3 received HTTP error (acceptable)."
    Write-Host $body
    Assert-True (($body -match "policy_rejected") -or ($_.Exception.Message -match "400")) "Expected policy rejection markers for unsafe message."
}

Write-Host ""
Write-Host "Done."

