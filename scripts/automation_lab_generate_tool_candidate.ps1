# Write review-only candidate drafts into an existing tool build workspace.
# No registry, sandbox, gateway, tool execution, installs, or model calls.

param(
    [Parameter(Mandatory = $true)]
    [string]$ToolBuildId
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $root = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $root "README.md"))) {
        throw "Could not find repo root (README.md missing) at: $root"
    }
    return $root
}

function Exit-GenError {
    param([string]$Message, [int]$Code = 1)
    Write-Host $Message -ForegroundColor Red
    exit $Code
}

function Read-JsonObject {
    param([string]$Path)
    $raw = Get-Content -Raw -LiteralPath $Path -Encoding UTF8
    return $raw | ConvertFrom-Json
}

function Get-NormalizedFullPath {
    param([string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Test-PathUnderRoot {
    param([string]$Path, [string]$Root)

    $separators = [char[]]@(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $normalizedPath = (Get-NormalizedFullPath -Path $Path).TrimEnd($separators)
    $normalizedRoot = (Get-NormalizedFullPath -Path $Root).TrimEnd($separators)
    $rootPrefix = $normalizedRoot + [System.IO.Path]::DirectorySeparatorChar
    return (
        $normalizedPath.Equals($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $normalizedPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)
    )
}

function Assert-PathUnderRoot {
    param([string]$Path, [string]$Root, [string]$Label)

    if (-not (Test-PathUnderRoot -Path $Path -Root $Root)) {
        Exit-GenError "$Label path escapes expected root."
    }
}

function Remove-CandidateOutputsIfPresent {
    param([string]$CandidateDir, [string]$TestsDir)

    $paths = @(
        (Join-Path $CandidateDir "CANDIDATE_TOOL.py"),
        (Join-Path $CandidateDir "TOOL_SCHEMA.json"),
        (Join-Path $CandidateDir "CANDIDATE_NOTES.md"),
        (Join-Path $CandidateDir "RISK_NOTES.md"),
        (Join-Path $TestsDir "TEST_PLAN.md")
    )
    foreach ($p in $paths) {
        if (Test-Path -LiteralPath $p) {
            Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
        }
    }
}

$RepoRoot = Resolve-RepoRoot
$buildId = $ToolBuildId.Trim()
if (-not $buildId) {
    Exit-GenError "ToolBuildId must not be empty."
}
if ($buildId -notmatch '^[A-Za-z0-9_-]{8,80}$') {
    Exit-GenError "ToolBuildId must match ^[A-Za-z0-9_-]{8,80}$."
}

$dataRoot = Join-Path $RepoRoot "data"
$toolBuildsRoot = Join-Path $dataRoot "tool_builds"
$buildRoot = Join-Path $toolBuildsRoot $buildId

Assert-PathUnderRoot -Path $buildRoot -Root $toolBuildsRoot -Label "Tool build workspace"

if (-not (Test-Path -LiteralPath $buildRoot)) {
    Exit-GenError "Tool build workspace not found: data/tool_builds/$buildId"
}

$indexPath = Join-Path $buildRoot "BUILD_INDEX.json"
$proposalPath = Join-Path $buildRoot "source_automation_lab\TOOL_PROPOSAL.md"
$candidateDir = Join-Path $buildRoot "candidate"
$testsDir = Join-Path $buildRoot "tests"

if (-not (Test-Path -LiteralPath $indexPath)) {
    Exit-GenError "Required file missing: BUILD_INDEX.json"
}
if (-not (Test-Path -LiteralPath $proposalPath)) {
    Exit-GenError "Required file missing: source_automation_lab/TOOL_PROPOSAL.md"
}
if (-not (Test-Path -LiteralPath $candidateDir)) {
    Exit-GenError "Required directory missing: candidate/"
}
if (-not (Test-Path -LiteralPath $testsDir)) {
    Exit-GenError "Required directory missing: tests/"
}

$outputs = @(
    (Join-Path $candidateDir "CANDIDATE_TOOL.py"),
    (Join-Path $candidateDir "TOOL_SCHEMA.json"),
    (Join-Path $candidateDir "CANDIDATE_NOTES.md"),
    (Join-Path $candidateDir "RISK_NOTES.md"),
    (Join-Path $testsDir "TEST_PLAN.md")
)
foreach ($out in $outputs) {
    if (Test-Path -LiteralPath $out) {
        Exit-GenError "Candidate outputs already exist; refusing to overwrite: $(Split-Path -Leaf $out)"
    }
}

$bi = Read-JsonObject -Path $indexPath
if ($bi.install_allowed -ne $false) {
    Exit-GenError "BUILD_INDEX.json install_allowed must be false for candidate generation."
}
if ($bi.execution_allowed -ne $false) {
    Exit-GenError "BUILD_INDEX.json execution_allowed must be false for candidate generation."
}

$proposalText = Get-Content -Raw -LiteralPath $proposalPath -Encoding UTF8
if (-not $proposalText) {
    $proposalText = ""
}

$capLine = "unknown_capability"
if ($bi.capability_ids -and @($bi.capability_ids).Count -gt 0) {
    $capLine = [string]$bi.capability_ids[0]
}

$primaryOutcome = ""
if ($null -ne $bi.primary_capability_outcome) {
    $primaryOutcome = [string]$bi.primary_capability_outcome
}

$proposalSnippet = $proposalText.Trim()
if ($proposalSnippet.Length -gt 400) {
    $proposalSnippet = $proposalSnippet.Substring(0, 400) + "`n... (truncated for deterministic draft notes)"
}

$candidatePy = @"
"""Review-only generated draft (not installed, not registry-backed).

This module is a planning skeleton for human review only. It must not be run
against production services, must not be executed through the gateway, and is
not an installed tool. No network, subprocess, filesystem writes, or registry
integration is defined here.

Build / proposal context (evidence only):
- tool_build_id: $buildId
- primary_capability_outcome: $primaryOutcome
- first capability id (hint): $capLine

TODO: Replace with a real design after review and a separate registration path.
"""

from typing import Any, Dict


def proposed_tool_placeholder(*, limit: int = 10) -> Dict[str, Any]:
    """Typed stub only; implementation intentionally omitted."""
    raise NotImplementedError(
        "Candidate stub for review — not a working integration."
    )

"@

$toolSchemaObj = [ordered]@{
    schema_kind              = "proposed_tool_interface"
    review_only                = $true
    advisory                   = $true
    not_registry_installation  = $true
    tool_build_id              = $buildId
    proposed_inputs            = @{
        type       = "object"
        properties = @{
            limit = @{
                type        = "integer"
                minimum     = 1
                maximum     = 100
                description = "Example bound for review; not enforced at runtime."
            }
        }
        required   = @("limit")
    }
    proposed_outputs           = @{
        type        = "object"
        description = "Placeholder result envelope for review."
        properties  = @{
            items = @{ type = "array"; items = @{ type = "string" } }
        }
    }
}
$toolSchemaJson = $toolSchemaObj | ConvertTo-Json -Depth 12

$candidateNotes = @"
# Candidate notes (review-only)

**Generated review draft** — not installed, not executable through the gateway, not registry-backed.

- **tool_build_id:** ``$buildId``
- **Source:** ``source_automation_lab/TOOL_PROPOSAL.md`` (excerpt below for traceability only)

## Excerpt from TOOL_PROPOSAL.md

$proposalSnippet

## Deterministic template limits

This file was produced by a template from BUILD_INDEX + proposal text only (no model). Replace all stubs after human review.
"@

$riskNotes = @"
# Risk notes (review-only)

**Advisory only** — not an authorization or risk sign-off.

- **Network:** No integration code is present in the candidate stub; future real implementations must declare explicit network scope.
- **Data:** Proposal may imply access to user or service data; treat as unvalidated intent until reviewed.
- **Credentials:** No secrets belong in ``candidate/``; never commit credentials.

Do not run draft code against real Navidrome, Radarr, Sonarr, or other services until reviewed and installed through normal gateway/registry flows.
"@

$testPlan = @"
# Test plan (future only)

**Planning document only** — no executable tests are included. The ``generated-tool-test-harness`` branch will add runnable tests later.

## Future unit tests (not implemented)

- [ ] Stub contract: ``proposed_tool_placeholder`` raises ``NotImplementedError`` until replaced.
- [ ] Input validation against a finalized schema (after human review).

## Future integration tests (not implemented)

- [ ] None in this workspace; gateway/sandbox tests live in the main repo test suite after install.

## Explicit non-goals for this artifact

- Do not execute ``CANDIDATE_TOOL.py`` from this document.
- Do not treat this plan as approval to install or run the tool.
"@

try {
    Set-Content -LiteralPath $outputs[0] -Value $candidatePy.TrimEnd() -Encoding UTF8
    Set-Content -LiteralPath $outputs[1] -Value $toolSchemaJson.TrimEnd() -Encoding UTF8
    Set-Content -LiteralPath $outputs[2] -Value $candidateNotes.TrimEnd() -Encoding UTF8
    Set-Content -LiteralPath $outputs[3] -Value $riskNotes.TrimEnd() -Encoding UTF8
    Set-Content -LiteralPath $outputs[4] -Value $testPlan.TrimEnd() -Encoding UTF8

    $bi | Add-Member -NotePropertyName generated_code_present -NotePropertyValue $true -Force
    $bi | Add-Member -NotePropertyName candidate_generation_completed -NotePropertyValue $true -Force
    $bi | Add-Member -NotePropertyName candidate_files -NotePropertyValue @(
        "candidate/CANDIDATE_TOOL.py",
        "candidate/TOOL_SCHEMA.json",
        "candidate/CANDIDATE_NOTES.md",
        "candidate/RISK_NOTES.md"
    ) -Force
    $bi | Add-Member -NotePropertyName tests_generated -NotePropertyValue $false -Force
    $bi | Add-Member -NotePropertyName install_allowed -NotePropertyValue $false -Force
    $bi | Add-Member -NotePropertyName execution_allowed -NotePropertyValue $false -Force
    $bi | Add-Member -NotePropertyName registry_modified -NotePropertyValue $false -Force
    $bi | Add-Member -NotePropertyName tools_executed -NotePropertyValue $false -Force
    $bi | Add-Member -NotePropertyName sandbox_worker_invoked -NotePropertyValue $false -Force
    $bi | Add-Member -NotePropertyName review_evidence_only -NotePropertyValue $true -Force
    $bi | Add-Member -NotePropertyName authority -NotePropertyValue $false -Force
    if ($bi.PSObject.Properties.Name -contains "automatic_registry_installation_allowed") {
        $bi.automatic_registry_installation_allowed = $false
    }

    ($bi | ConvertTo-Json -Depth 25) | Set-Content -LiteralPath $indexPath -Encoding UTF8

    Write-Host "Wrote review-only candidate artifacts under data/tool_builds/$buildId"
} catch {
    Remove-CandidateOutputsIfPresent -CandidateDir $candidateDir -TestsDir $testsDir
    throw
}
