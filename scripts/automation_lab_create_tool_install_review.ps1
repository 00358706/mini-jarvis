# Package review-only install evidence from a tool build workspace (no install, no registry, no execution).

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

function Exit-InstallReviewError {
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
        Exit-InstallReviewError "$Label path escapes expected root."
    }
}

function Remove-InstallReviewOutputs {
    param(
        [string]$ManifestPath,
        [string]$ReviewPath
    )

    foreach ($p in @($ManifestPath, $ReviewPath)) {
        if (Test-Path -LiteralPath $p) {
            Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-BuildIndexForInstallReview {
    param($Index)

    $rules = @(
        @{ Name = "authority"; Expected = $false }
        @{ Name = "review_evidence_only"; Expected = $true }
        @{ Name = "generated_code_present"; Expected = $true }
        @{ Name = "candidate_generation_completed"; Expected = $true }
        @{ Name = "test_harness_completed"; Expected = $true }
        @{ Name = "static_validation_completed"; Expected = $true }
        @{ Name = "candidate_code_executed"; Expected = $false }
        @{ Name = "install_allowed"; Expected = $false }
        @{ Name = "execution_allowed"; Expected = $false }
        @{ Name = "registry_modified"; Expected = $false }
        @{ Name = "tools_executed"; Expected = $false }
        @{ Name = "sandbox_worker_invoked"; Expected = $false }
    )
    foreach ($r in $rules) {
        $n = $r.Name
        $actual = $Index.$n
        if ($actual -ne $r.Expected) {
            return "BUILD_INDEX.json gate failed: '$n' must be $($r.Expected) (got $actual)."
        }
    }
    return $null
}

function Test-TestResultsForInstallReview {
    param($Results)

    if ($null -eq $Results) {
        return "TEST_RESULTS.json is empty or invalid."
    }
    if ($Results.schema_version -ne "generated-tool-test-results.v1") {
        return "TEST_RESULTS.json schema_version must be generated-tool-test-results.v1."
    }
    if ($Results.overall_status -ne "passed") {
        return "TEST_RESULTS.json overall_status must be passed."
    }
    if ($Results.test_harness_kind -ne "static_review") {
        return "TEST_RESULTS.json test_harness_kind must be static_review."
    }

    $boolRules = @(
        "candidate_code_executed",
        "sandbox_worker_invoked",
        "registry_modified",
        "tools_executed",
        "install_allowed",
        "execution_allowed",
        "real_service_calls"
    )
    foreach ($n in $boolRules) {
        if ($Results.$n -ne $false) {
            return "TEST_RESULTS.json '$n' must be false (got $($Results.$n))."
        }
    }
    return $null
}

$RepoRoot = Resolve-RepoRoot
$buildId = $ToolBuildId.Trim()
if (-not $buildId) {
    Exit-InstallReviewError "ToolBuildId must not be empty."
}
if ($buildId -notmatch '^[A-Za-z0-9_-]{8,80}$') {
    Exit-InstallReviewError "ToolBuildId must match ^[A-Za-z0-9_-]{8,80}$."
}

$toolBuildsRoot = Join-Path (Join-Path $RepoRoot "data") "tool_builds"
$buildRoot = Join-Path $toolBuildsRoot $buildId

Assert-PathUnderRoot -Path $buildRoot -Root $toolBuildsRoot -Label "Tool build workspace"

if (-not (Test-Path -LiteralPath $buildRoot)) {
    Exit-InstallReviewError "Tool build workspace not found: data/tool_builds/$buildId"
}

$indexPath = Join-Path $buildRoot "BUILD_INDEX.json"
$proposalPath = Join-Path $buildRoot "source_automation_lab\TOOL_PROPOSAL.md"
$candidateDir = Join-Path $buildRoot "candidate"
$testsDir = Join-Path $buildRoot "tests"
$candidatePy = Join-Path $candidateDir "CANDIDATE_TOOL.py"
$toolSchema = Join-Path $candidateDir "TOOL_SCHEMA.json"
$candidateNotes = Join-Path $candidateDir "CANDIDATE_NOTES.md"
$riskNotes = Join-Path $candidateDir "RISK_NOTES.md"
$testPlan = Join-Path $testsDir "TEST_PLAN.md"
$resultsPath = Join-Path $buildRoot "TEST_RESULTS.json"
$summaryPath = Join-Path $buildRoot "TEST_SUMMARY.md"
$manifestPath = Join-Path $buildRoot "INSTALL_MANIFEST.json"
$installReviewPath = Join-Path $buildRoot "INSTALL_REVIEW.md"

$required = @(
    @{ Path = $indexPath; Label = "BUILD_INDEX.json" },
    @{ Path = $proposalPath; Label = "source_automation_lab/TOOL_PROPOSAL.md" },
    @{ Path = $candidatePy; Label = "candidate/CANDIDATE_TOOL.py" },
    @{ Path = $toolSchema; Label = "candidate/TOOL_SCHEMA.json" },
    @{ Path = $candidateNotes; Label = "candidate/CANDIDATE_NOTES.md" },
    @{ Path = $riskNotes; Label = "candidate/RISK_NOTES.md" },
    @{ Path = $testPlan; Label = "tests/TEST_PLAN.md" },
    @{ Path = $resultsPath; Label = "TEST_RESULTS.json" },
    @{ Path = $summaryPath; Label = "TEST_SUMMARY.md" }
)

foreach ($item in $required) {
    if (-not (Test-Path -LiteralPath $item.Path)) {
        Exit-InstallReviewError "Required path missing: $($item.Label)"
    }
}

if (Test-Path -LiteralPath $manifestPath) {
    Exit-InstallReviewError "INSTALL_MANIFEST.json already exists; refusing to overwrite."
}
if (Test-Path -LiteralPath $installReviewPath) {
    Exit-InstallReviewError "INSTALL_REVIEW.md already exists; refusing to overwrite."
}

$bi = Read-JsonObject -Path $indexPath
$gate = Test-BuildIndexForInstallReview -Index $bi
if ($null -ne $gate) {
    Exit-InstallReviewError $gate
}

$testResults = Read-JsonObject -Path $resultsPath
$trGate = Test-TestResultsForInstallReview -Results $testResults
if ($null -ne $trGate) {
    Exit-InstallReviewError $trGate
}

$capIds = @()
if ($bi.capability_ids) {
    $capIds = @($bi.capability_ids | ForEach-Object { [string]$_ })
}

$toolNamePreview = $null
if ($capIds.Count -gt 0) {
    $raw = $capIds[0] -replace '[^a-zA-Z0-9_]', '_'
    if ($raw.Length -gt 64) {
        $raw = $raw.Substring(0, 64)
    }
    if ($raw) {
        $toolNamePreview = $raw
    }
}

$createdAt = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")

$sourcePaths = @(
    "source_automation_lab/TOOL_PROPOSAL.md",
    "candidate/CANDIDATE_TOOL.py",
    "candidate/TOOL_SCHEMA.json",
    "candidate/CANDIDATE_NOTES.md",
    "candidate/RISK_NOTES.md",
    "TEST_RESULTS.json",
    "TEST_SUMMARY.md"
)

$requiredFutureSteps = @(
    "human install review",
    "explicit registry install branch/action",
    "registry schema validation",
    "normal plan/policy/approval/sandbox execution path after install"
)

$preview = [ordered]@{
    status                   = "proposed_review_only"
    tool_name                = $toolNamePreview
    capability_ids           = $capIds
    schema_source            = "candidate/TOOL_SCHEMA.json"
    implementation_source    = "candidate/CANDIDATE_TOOL.py"
    install_target           = $null
    advisory_only            = $true
}

$manifest = [ordered]@{
    schema_version               = "tool-install-review-manifest.v1"
    tool_build_id                = $buildId
    created_at                   = $createdAt
    review_only                  = $true
    authority                    = $false
    install_performed            = $false
    install_allowed              = $false
    execution_allowed            = $false
    registry_modified            = $false
    tools_executed               = $false
    sandbox_worker_invoked       = $false
    candidate_code_executed      = $false
    source_paths                 = $sourcePaths
    proposed_registry_entry_preview = $preview
    required_future_steps        = $requiredFutureSteps
}

$indexBackup = Get-Content -Raw -LiteralPath $indexPath -Encoding UTF8

$reviewBody = @"
# Install review package (evidence only)

## What this is

- This folder contains **review packaging only** for a proposed tool. It does **not** install, approve, authorize, or execute anything.
- **Approval for install is not approval for execution.** Execution remains gated by normal plan/policy/approval/registry/schema/sandbox paths after any future install.
- `registry-install-review` and real registry lifecycle work remain **out of scope** for this artifact; use an explicit registry install branch when ready.

## Review checklist

- [ ] Read `source_automation_lab/TOOL_PROPOSAL.md` and `BUILD_INDEX.json` capability context.
- [ ] Read `candidate/CANDIDATE_TOOL.py` and `candidate/TOOL_SCHEMA.json` (advisory drafts only).
- [ ] Read `TEST_RESULTS.json` and `TEST_SUMMARY.md` - static harness only; candidate code was **not** executed by that harness.
- [ ] Read `INSTALL_MANIFEST.json` - `install_performed` must remain false until a separate human-driven install process.
- [ ] Confirm no expectation of automatic registry mutation, sandbox runs, or gateway shortcuts from this package.

## Evidence summary

- **Tool build id:** ``$buildId``
- **Static test:** ``passed`` (``static_review``) per ``TEST_RESULTS.json``.
- **Manifest:** ``INSTALL_MANIFEST.json`` (schema ``tool-install-review-manifest.v1``).

## Candidate files (paths)

- ``candidate/CANDIDATE_TOOL.py``
- ``candidate/TOOL_SCHEMA.json``
- ``candidate/CANDIDATE_NOTES.md``
- ``candidate/RISK_NOTES.md``
- ``tests/TEST_PLAN.md``

## Proposed registry entry preview (non-binding)

- **Status:** ``proposed_review_only``
- **Tool name (placeholder):** ``$(if ($null -eq $toolNamePreview) { 'null' } else { $toolNamePreview })``
- **Capability ids:** see ``INSTALL_MANIFEST.json`` ``proposed_registry_entry_preview.capability_ids``.
- **Schema / implementation sources:** paths only; not installed.

## Explicit non-authority

This package does **not** install, approve, authorize, or execute anything. Registry ``status=installed`` remains execution truth only after normal gateway flows.
"@

try {
    ($manifest | ConvertTo-Json -Depth 20) | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    Set-Content -LiteralPath $installReviewPath -Value $reviewBody.TrimEnd() -Encoding UTF8

    $bi | Add-Member -NotePropertyName install_review_created -NotePropertyValue $true -Force
    $bi | Add-Member -NotePropertyName install_review_manifest_path -NotePropertyValue "INSTALL_MANIFEST.json" -Force
    $bi | Add-Member -NotePropertyName install_review_path -NotePropertyValue "INSTALL_REVIEW.md" -Force
    $bi | Add-Member -NotePropertyName install_performed -NotePropertyValue $false -Force
    $bi | Add-Member -NotePropertyName install_allowed -NotePropertyValue $false -Force
    $bi | Add-Member -NotePropertyName execution_allowed -NotePropertyValue $false -Force
    $bi | Add-Member -NotePropertyName registry_modified -NotePropertyValue $false -Force
    $bi | Add-Member -NotePropertyName tools_executed -NotePropertyValue $false -Force
    $bi | Add-Member -NotePropertyName sandbox_worker_invoked -NotePropertyValue $false -Force
    $bi | Add-Member -NotePropertyName authority -NotePropertyValue $false -Force
    $bi | Add-Member -NotePropertyName review_evidence_only -NotePropertyValue $true -Force

    ($bi | ConvertTo-Json -Depth 25) | Set-Content -LiteralPath $indexPath -Encoding UTF8

    Write-Host "Created install review package under data/tool_builds/$buildId"
}
catch {
    Remove-InstallReviewOutputs -ManifestPath $manifestPath -ReviewPath $installReviewPath
    Set-Content -LiteralPath $indexPath -Value $indexBackup -Encoding UTF8 -Force
    Write-Host "Install review packaging failed; rolled back outputs and BUILD_INDEX.json." -ForegroundColor Red
    exit 4
}

exit 0
