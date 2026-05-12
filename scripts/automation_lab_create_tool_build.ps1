# Create a review-only tool build workspace from an existing Automation Lab run.
# Copies proposal artifacts only. No registry mutation, sandbox, installs, or code generation.

param(
    [Parameter(Mandatory = $true)]
    [string]$AutomationLabRequestId
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $root = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $root "README.md"))) {
        throw "Could not find repo root (README.md missing) at: $root"
    }
    return $root
}

function Exit-BuildError {
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
        Exit-BuildError "$Label path escapes expected root."
    }
}

$RepoRoot = Resolve-RepoRoot
$requestId = $AutomationLabRequestId.Trim()
if (-not $requestId) {
    Exit-BuildError "AutomationLabRequestId must not be empty."
}
if ($requestId -notmatch '^[A-Za-z0-9_-]{8,80}$') {
    Exit-BuildError "AutomationLabRequestId contains invalid characters. Expected ^[A-Za-z0-9_-]{8,80}$."
}

$automationLabRoot = Join-Path (Join-Path $RepoRoot "data") "automation_lab"
$toolBuildRoot = Join-Path (Join-Path $RepoRoot "data") "tool_builds"
$sourceDir = Join-Path $automationLabRoot $requestId
$buildRoot = Join-Path $toolBuildRoot $requestId
$destSourceDir = "source_automation_lab"

Assert-PathUnderRoot -Path $sourceDir -Root $automationLabRoot -Label "Automation Lab source"
Assert-PathUnderRoot -Path $buildRoot -Root $toolBuildRoot -Label "Tool build workspace"

if (-not (Test-Path -LiteralPath $sourceDir)) {
    Exit-BuildError "Automation Lab run directory not found: data/automation_lab/$requestId"
}

$required = @(
    @{ Name = "INDEX.json"; Path = (Join-Path $sourceDir "INDEX.json") },
    @{ Name = "CAPABILITY_MATCHES.json"; Path = (Join-Path $sourceDir "CAPABILITY_MATCHES.json") },
    @{ Name = "TOOL_PROPOSAL.md"; Path = (Join-Path $sourceDir "TOOL_PROPOSAL.md") }
)

foreach ($item in $required) {
    if (-not (Test-Path -LiteralPath $item.Path)) {
        if ($item.Name -eq "TOOL_PROPOSAL.md") {
            Exit-BuildError "TOOL_PROPOSAL.md is missing; this run is not a tool proposal build source."
        }
        Exit-BuildError "Required source file missing: $($item.Name)"
    }
}

if (Test-Path -LiteralPath $buildRoot) {
    Exit-BuildError "Build workspace already exists (refusing to overwrite): data/tool_builds/$requestId"
}

$index = Read-JsonObject -Path (Join-Path $sourceDir "INDEX.json")
$capabilities = Read-JsonObject -Path (Join-Path $sourceDir "CAPABILITY_MATCHES.json")

if ($index.request_id -and [string]$index.request_id -ne $requestId) {
    Exit-BuildError "INDEX.json request_id '$($index.request_id)' does not match AutomationLabRequestId '$requestId'."
}

$optionalCopies = @(
    "REQUEST.json",
    "CLASSIFICATION.json",
    "REVIEW_SUMMARY.md"
)

try {
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
$copyTargetRoot = Join-Path $buildRoot $destSourceDir
New-Item -ItemType Directory -Path $copyTargetRoot -Force | Out-Null

$artifactsCopied = @()
foreach ($name in @("INDEX.json", "CAPABILITY_MATCHES.json", "TOOL_PROPOSAL.md")) {
    $src = Join-Path $sourceDir $name
    Copy-Item -LiteralPath $src -Destination (Join-Path $copyTargetRoot $name) -Force
    $artifactsCopied += "$destSourceDir/$name"
}

foreach ($name in $optionalCopies) {
    $src = Join-Path $sourceDir $name
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $copyTargetRoot $name) -Force
        $artifactsCopied += "$destSourceDir/$name"
    }
}

$candidateDir = Join-Path $buildRoot "candidate"
$testsDir = Join-Path $buildRoot "tests"
New-Item -ItemType Directory -Path $candidateDir -Force | Out-Null
New-Item -ItemType Directory -Path $testsDir -Force | Out-Null

$candidateReadme = @"
# candidate

This directory is reserved for a future tool implementation (see branch ``tool-candidate-generation``).

**No generated implementation code is present in this workspace.**
"@
Set-Content -LiteralPath (Join-Path $candidateDir "README.md") -Value $candidateReadme -Encoding UTF8

$testsReadme = @"
# tests

This directory is reserved for future tests for the proposed tool.

**No executable tests or generated code are present in this workspace.**
"@
Set-Content -LiteralPath (Join-Path $testsDir "README.md") -Value $testsReadme -Encoding UTF8

$primaryOutcome = $null
if ($null -ne $index.primary_capability_outcome) {
    $primaryOutcome = [string]$index.primary_capability_outcome
}
elseif ($null -ne $capabilities.primary_outcome) {
    $primaryOutcome = [string]$capabilities.primary_outcome
}

$proposalKind = if ($null -ne $index.proposal_kind) { [string]$index.proposal_kind } else { "tool_proposal" }

$capIds = @()
if ($capabilities.capability_ids) {
    $capIds = @($capabilities.capability_ids | ForEach-Object { [string]$_ })
}

$evidenceSources = @()
if ($capabilities.evidence_sources) {
    $evidenceSources = @($capabilities.evidence_sources | ForEach-Object { [string]$_ })
}

$primaryOutcomeSource = $null
if ($null -ne $capabilities.primary_outcome_source) {
    $primaryOutcomeSource = [string]$capabilities.primary_outcome_source
}

$score = $null
if ($capabilities.PSObject.Properties.Name -contains "score") {
    $score = $capabilities.score
}
$precedenceApplied = $null
if ($capabilities.PSObject.Properties.Name -contains "precedence_applied") {
    $precedenceApplied = $capabilities.precedence_applied
}

$conflictsCount = $null
if ($capabilities.PSObject.Properties.Name -contains "conflicts") {
    $conflictsCount = @($capabilities.conflicts).Count
}

$createdAt = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")

$buildIndex = [ordered]@{
    schema_version                    = "tool-build-index.v1"
    build_id                          = $requestId
    source_request_id                 = $requestId
    source_automation_lab_dir         = "data/automation_lab/$requestId"
    source_tool_proposal              = "$destSourceDir/TOOL_PROPOSAL.md"
    created_at                        = $createdAt
    proposal_kind                     = $proposalKind
    capability_ids                    = $capIds
    primary_capability_outcome        = $primaryOutcome
    primary_outcome_source            = $primaryOutcomeSource
    evidence_sources                  = $evidenceSources
    score                             = $score
    precedence_applied                = $precedenceApplied
    conflicts_count                   = $conflictsCount
    authority                         = $false
    review_evidence_only              = $true
    generated_code_present            = $false
    install_allowed                   = $false
    execution_allowed                 = $false
    registry_modified                 = $false
    tools_executed                    = $false
    sandbox_worker_invoked            = $false
    automatic_registry_installation_allowed = $false
    artifacts_copied                  = $artifactsCopied
}

$buildIndexJson = $buildIndex | ConvertTo-Json -Depth 20
Set-Content -LiteralPath (Join-Path $buildRoot "BUILD_INDEX.json") -Value $buildIndexJson -Encoding UTF8

$implPlan = @"
# Implementation plan (stub)

## Purpose

Planning shell for a proposed tool derived from Automation Lab review artifacts. This file is **not** an executable specification and does not authorize implementation, installation, or execution.

## Source proposal

- Automation Lab request: ``$requestId``
- Copied proposal: ``$destSourceDir/TOOL_PROPOSAL.md``

## Boundaries

- **Review evidence only** — same non-authority rules as Automation Lab proposal artifacts.
- Registry ``status=installed`` remains execution truth for any future runtime.
- No registry mutation, sandbox invocation, tool execution, or installation from this workspace.

## Future implementation checklist

- [ ] Human review of ``TOOL_PROPOSAL.md`` and capability evidence.
- [ ] Design tool surface (inputs, outputs, side effects) against gateway policy.
- [ ] Implement in ``candidate/`` only after explicit ``tool-candidate-generation`` work.

## Future test checklist

- [ ] Unit tests for proposed behavior (to live under ``tests/`` when added).
- [ ] Policy and schema alignment before any registry proposal.

## No generated code is present in this workspace.

This workspace contains only copied lab artifacts, indexes, and stubs. There is **no** generated tool source here yet.
"@
Set-Content -LiteralPath (Join-Path $buildRoot "IMPLEMENTATION_PLAN.md") -Value $implPlan.TrimEnd() -Encoding UTF8

$buildReview = @"
# Build review (non-authority checklist)

**This checklist is review evidence only.** It does not approve execution, installation, or registry changes.

- [ ] Confirmed ``BUILD_INDEX.json`` marks ``authority: false`` and boundary flags are correct.
- [ ] Read ``source_automation_lab/TOOL_PROPOSAL.md`` and ``CAPABILITY_MATCHES.json`` for consistency.
- [ ] Verified no generated implementation files were added under ``candidate/`` or ``tests/`` beyond stubs.
- [ ] Confirmed no expectation of automatic install or sandbox execution from this folder.

Registry remains execution truth; gateway remains authority for any future runtime.
"@
Set-Content -LiteralPath (Join-Path $buildRoot "BUILD_REVIEW.md") -Value $buildReview.TrimEnd() -Encoding UTF8

Write-Host "Created tool build workspace: data/tool_builds/$requestId"
} catch {
    if ((Test-PathUnderRoot -Path $buildRoot -Root $toolBuildRoot) -and (Test-Path -LiteralPath $buildRoot)) {
        Remove-Item -LiteralPath $buildRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}
