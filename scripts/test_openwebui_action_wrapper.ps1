# Open WebUI action wrapper smoke test (proposal-only).

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Wrapper = Join-Path $RepoRoot "integrations\openwebui\mini_jarvis_plan_propose.py"

$env:MINI_JARVIS_BASE_URL = if ($env:MINI_JARVIS_BASE_URL) { $env:MINI_JARVIS_BASE_URL } else { "http://127.0.0.1:8000" }
$env:MINI_JARVIS_API_KEY = if ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } else { "change-me-before-use" }
$env:MINI_JARVIS_AGENT = "project_maintainer_agent"

function Assert-Contains {
    param([string]$Text, [string]$Needle, [string]$Message)
    if ($Text -notmatch [Regex]::Escape($Needle)) {
        throw $Message
    }
}

function Assert-NotContains {
    param([string]$Text, [string]$Needle, [string]$Message)
    if ($Text -match [Regex]::Escape($Needle)) {
        throw $Message
    }
}

Write-Host "--- Case 1: list project files ---"
$Out1 = python $Wrapper "list project files" | Out-String
Write-Host $Out1
Assert-Contains $Out1 "pending_approval" "Expected pending_approval in wrapper output."
Assert-Contains $Out1 "proposed_tool: list_project_files" "Expected proposed_tool in wrapper output."
Assert-Contains $Out1 "No tools have been executed." "Expected no-execution note in wrapper output."
Assert-Contains $Out1 "Next steps (explicit):" "Expected next steps section in wrapper output."
Assert-Contains $Out1 "mini_jarvis_plan_review.py show" "Expected review command in wrapper output."
Assert-Contains $Out1 "mini_jarvis_plan_review.py approve" "Expected approve command in wrapper output."

Write-Host "--- Case 2: search repo for PATCH_PROPOSAL.md ---"
$Out2 = python $Wrapper "search repo for PATCH_PROPOSAL.md" | Out-String
Write-Host $Out2
Assert-Contains $Out2 "proposed_tool: search_repo" "Expected search_repo in wrapper output."
Assert-Contains $Out2 "PATCH_PROPOSAL.md" "Expected PATCH_PROPOSAL.md in wrapper output."

Write-Host "--- Case 3: unsafe message (radarr_search) ---"
$Out3 = python $Wrapper "run radarr_search for Inception" | Out-String
Write-Host $Out3
Assert-NotContains $Out3 "proposed_tool: radarr_search" "Wrapper must not propose radarr_search."

Write-Host "Done."

