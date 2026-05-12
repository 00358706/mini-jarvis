# Tests for static generated-tool test harness (no candidate execution).

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $root = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $root "README.md"))) {
        throw "Could not find repo root (README.md missing) at: $root"
    }
    return $root
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Read-JsonFile {
    param([string]$Path)
    return Get-Content -Raw -LiteralPath $Path -Encoding UTF8 | ConvertFrom-Json
}

function Get-GuardHashes {
    param([string]$RepoRoot)

    $guarded = @(
        "registry.py",
        "tools.py",
        "sandbox.py",
        "sandbox_worker.py",
        "main.py",
        "ingestion.py"
    )

    $hashes = @{}
    foreach ($rel in $guarded) {
        $path = Join-Path $RepoRoot $rel
        $hashes[$rel] = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash
    }
    return $hashes
}

function Assert-GuardHashesUnchanged {
    param(
        [string]$RepoRoot,
        [hashtable]$Before
    )

    foreach ($rel in $Before.Keys) {
        $path = Join-Path $RepoRoot $rel
        $after = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash
        Assert-True ($after -eq $Before[$rel]) "Guarded runtime file changed unexpectedly: $rel"
    }
}

function Invoke-Harness {
    param(
        [string]$ScriptPath,
        [string]$ToolBuildId
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & powershell -ExecutionPolicy Bypass -File $ScriptPath `
            -ToolBuildId $ToolBuildId 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return [pscustomobject]@{
        Code   = $code
        Output = $output
    }
}

function New-ToolBuildHarnessFixture {
    param(
        [string]$BuildRoot,
        [string]$BuildId,
        [hashtable]$IndexOverrides,
        [string]$CandidatePyContent
    )

    New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
    $candidateDir = Join-Path $BuildRoot "candidate"
    $testsDir = Join-Path $BuildRoot "tests"
    New-Item -ItemType Directory -Path $candidateDir -Force | Out-Null
    New-Item -ItemType Directory -Path $testsDir -Force | Out-Null

    $idx = [ordered]@{
        schema_version                  = "tool-build-index.v1"
        build_id                        = $BuildId
        source_request_id               = $BuildId
        authority                       = $false
        review_evidence_only            = $true
        generated_code_present          = $true
        candidate_generation_completed  = $true
        install_allowed                 = $false
        execution_allowed               = $false
        registry_modified               = $false
        tools_executed                  = $false
        sandbox_worker_invoked          = $false
        capability_ids                  = @("fixture.cap.example")
        primary_capability_outcome      = "propose_new"
    }
    if ($IndexOverrides) {
        foreach ($k in $IndexOverrides.Keys) {
            $idx[$k] = $IndexOverrides[$k]
        }
    }
    ($idx | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath (Join-Path $BuildRoot "BUILD_INDEX.json") -Encoding UTF8

    $schema = [ordered]@{
        schema_kind                 = "proposed_tool_interface"
        review_only                   = $true
        advisory                      = $true
        not_registry_installation     = $true
        tool_build_id                 = $BuildId
    }
    ($schema | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath (Join-Path $candidateDir "TOOL_SCHEMA.json") -Encoding UTF8

    Set-Content -LiteralPath (Join-Path $candidateDir "CANDIDATE_TOOL.py") -Value $CandidatePyContent.TrimEnd() -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $candidateDir "CANDIDATE_NOTES.md") -Value "# Notes`nReview-only fixture." -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $candidateDir "RISK_NOTES.md") -Value "# Risks`nAdvisory fixture." -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $testsDir "TEST_PLAN.md") -Value "# Plan`nFuture tests only." -Encoding UTF8
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$guardBefore = Get-GuardHashes -RepoRoot $RepoRoot
$toolsPyBefore = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8

$harnessPath = Join-Path $RepoRoot "scripts\automation_lab_test_tool_candidate.ps1"
$harnessSrc = Get-Content -Raw -LiteralPath $harnessPath
Assert-True ($harnessSrc -notmatch '(?i)python\s+-c|python\.exe\s+-c') "Harness must not invoke Python interpreter."
Assert-True ($harnessSrc -notmatch '(?i)automation_lab\.py') "Harness must not invoke automation lab generator."
Assert-True ($harnessSrc -notmatch '(?i)Import-Module') "Harness must not import modules for execution."

$buildsRoot = Join-Path $RepoRoot "data\tool_builds"
if (-not (Test-Path -LiteralPath $buildsRoot)) {
    New-Item -ItemType Directory -Path $buildsRoot -Force | Out-Null
}

$goodPy = @'
"""Review-only generated draft (not installed).

Stub for harness positive fixture.
"""

from typing import Any, Dict


def proposed_tool_placeholder(*, limit: int = 10) -> Dict[str, Any]:
    raise NotImplementedError("stub")
'@

$badPy = @'
"""Review-only generated draft (not installed).

Bad fixture with forbidden import.
"""
import subprocess

from typing import Any, Dict

def x() -> None:
    pass
'@

$positiveId = "tb_harn_$([Guid]::NewGuid().ToString('N').Substring(0, 12))"
$unsafeIdxId = "tb_harn_badidx_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$unsafeCandId = "tb_harn_badpy_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$rollbackId = "tb_harn_rb_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
$positiveRoot = Join-Path $buildsRoot $positiveId
$unsafeIdxRoot = Join-Path $buildsRoot $unsafeIdxId
$unsafeCandRoot = Join-Path $buildsRoot $unsafeCandId
$rollbackRoot = Join-Path $buildsRoot $rollbackId

try {
    # --- Positive ---
    New-ToolBuildHarnessFixture -BuildRoot $positiveRoot -BuildId $positiveId -IndexOverrides $null -CandidatePyContent $goodPy

    $rPos = Invoke-Harness -ScriptPath $harnessPath -ToolBuildId $positiveId
    Assert-True ($rPos.Code -eq 0) "Harness should pass (code $($rPos.Code)). $($rPos.Output)"

    $resPath = Join-Path $positiveRoot "TEST_RESULTS.json"
    $sumPath = Join-Path $positiveRoot "TEST_SUMMARY.md"
    Assert-True (Test-Path -LiteralPath $resPath) "TEST_RESULTS.json missing."
    Assert-True (Test-Path -LiteralPath $sumPath) "TEST_SUMMARY.md missing."

    $res = Read-JsonFile -Path $resPath
    Assert-True ($res.schema_version -eq "generated-tool-test-results.v1") "results schema"
    Assert-True ($res.overall_status -eq "passed") "overall_status passed"
    Assert-True ($res.candidate_code_executed -eq $false) "candidate_code_executed"
    Assert-True ($res.sandbox_worker_invoked -eq $false) "sandbox_worker_invoked"
    Assert-True ($res.registry_modified -eq $false) "registry_modified"
    Assert-True ($res.tools_executed -eq $false) "tools_executed"
    Assert-True ($res.install_allowed -eq $false) "install_allowed"
    Assert-True ($res.execution_allowed -eq $false) "execution_allowed"
    Assert-True ($res.real_service_calls -eq $false) "real_service_calls"

    $sumText = Get-Content -Raw -LiteralPath $sumPath -Encoding UTF8
    Assert-True ($sumText -match "static review") "summary should mention static review."
    Assert-True ($sumText -match "not executed|was not executed") "summary should state candidate not executed."

    $biPos = Read-JsonFile -Path (Join-Path $positiveRoot "BUILD_INDEX.json")
    Assert-True ($biPos.test_harness_completed -eq $true) "BUILD_INDEX test_harness_completed"
    Assert-True ($biPos.static_validation_completed -eq $true) "static_validation_completed"
    Assert-True ($biPos.test_results_path -eq "TEST_RESULTS.json") "test_results_path"
    Assert-True ($biPos.test_summary_path -eq "TEST_SUMMARY.md") "test_summary_path"
    Assert-True ($biPos.test_harness_kind -eq "static_review") "test_harness_kind"
    Assert-True ($biPos.candidate_code_executed -eq $false) "BUILD_INDEX candidate_code_executed"
    Assert-True ($biPos.authority -eq $false) "authority"
    Assert-True ($biPos.review_evidence_only -eq $true) "review_evidence_only"

    # --- Duplicate run ---
    $rDup = Invoke-Harness -ScriptPath $harnessPath -ToolBuildId $positiveId
    Assert-True ($rDup.Code -eq 1) "Second harness should refuse overwrite (exit $($rDup.Code))."
    Assert-True ($rDup.Output -match "refusing to overwrite|already exists") "Expected overwrite refusal."

    # --- Unsafe BUILD_INDEX ---
    $badIdx = @{
        authority              = $true
        review_evidence_only   = $false
        install_allowed        = $true
        execution_allowed      = $true
    }
    New-ToolBuildHarnessFixture -BuildRoot $unsafeIdxRoot -BuildId $unsafeIdxId -IndexOverrides $badIdx -CandidatePyContent $goodPy

    $rUnsafeIdx = Invoke-Harness -ScriptPath $harnessPath -ToolBuildId $unsafeIdxId
    Assert-True ($rUnsafeIdx.Code -eq 1) "Unsafe BUILD_INDEX must fail closed."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $unsafeIdxRoot "TEST_RESULTS.json"))) "No TEST_RESULTS on unsafe index."

    # --- Unsafe candidate (forbidden pattern) ---
    New-ToolBuildHarnessFixture -BuildRoot $unsafeCandRoot -BuildId $unsafeCandId -IndexOverrides $null -CandidatePyContent $badPy

    $rBadPy = Invoke-Harness -ScriptPath $harnessPath -ToolBuildId $unsafeCandId
    Assert-True ($rBadPy.Code -eq 2) "Unsafe candidate should exit 2 (got $($rBadPy.Code))."

    $resBad = Read-JsonFile -Path (Join-Path $unsafeCandRoot "TEST_RESULTS.json")
    Assert-True ($resBad.overall_status -eq "failed") "overall_status failed for bad candidate."
    $biBad = Read-JsonFile -Path (Join-Path $unsafeCandRoot "BUILD_INDEX.json")
    Assert-True ($biBad.PSObject.Properties.Name -notcontains "test_harness_completed") "BUILD_INDEX must not gain harness fields on failed static checks."

    # --- I/O failure rollback ---
    New-ToolBuildHarnessFixture -BuildRoot $rollbackRoot -BuildId $rollbackId -IndexOverrides $null -CandidatePyContent $goodPy
    $rollbackIndex = Join-Path $rollbackRoot "BUILD_INDEX.json"
    $rollbackOriginal = Get-Content -Raw -LiteralPath $rollbackIndex -Encoding UTF8
    try {
        Set-ItemProperty -LiteralPath $rollbackIndex -Name IsReadOnly -Value $true
        $rRollback = Invoke-Harness -ScriptPath $harnessPath -ToolBuildId $rollbackId
    } finally {
        Set-ItemProperty -LiteralPath $rollbackIndex -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue
    }
    Assert-True ($rRollback.Code -ne 0) "Read-only BUILD_INDEX.json should force rollback path."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $rollbackRoot "TEST_RESULTS.json"))) "Rollback must remove partial TEST_RESULTS.json."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $rollbackRoot "TEST_SUMMARY.md"))) "Rollback must remove partial TEST_SUMMARY.md."
    $rollbackAfter = Get-Content -Raw -LiteralPath $rollbackIndex -Encoding UTF8
    Assert-True ($rollbackAfter -eq $rollbackOriginal) "Rollback must leave BUILD_INDEX.json content unchanged."

    # --- Invalid ids / missing workspace ---
    foreach ($bad in @("short", "has/slash", "..\\trav")) {
        $rb = Invoke-Harness -ScriptPath $harnessPath -ToolBuildId $bad
        Assert-True ($rb.Code -eq 1) "Invalid id must fail: $bad"
    }

    $ghostId = "tb_nexist_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
    $rg = Invoke-Harness -ScriptPath $harnessPath -ToolBuildId $ghostId
    Assert-True ($rg.Code -eq 1) "Missing workspace must fail."

    $toolsPyAfter = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8
    Assert-True ($toolsPyAfter -eq $toolsPyBefore) "tools.py unchanged."
    Assert-True ($toolsPyAfter -notmatch "proposed_tool_placeholder") "tools.py must not contain candidate stub."

    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore
    Write-Host "OK: generated tool test harness tests passed."
} finally {
    foreach ($p in @($positiveRoot, $unsafeIdxRoot, $unsafeCandRoot, $rollbackRoot)) {
        $idx = Join-Path $p "BUILD_INDEX.json"
        if ($idx -and (Test-Path -LiteralPath $idx)) {
            Set-ItemProperty -LiteralPath $idx -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue
        }
        if ($p -and (Test-Path -LiteralPath $p)) {
            Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
