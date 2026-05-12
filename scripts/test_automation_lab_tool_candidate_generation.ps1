# Tests for review-only tool candidate generation (filesystem only; no execution).

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

function Invoke-CandidateGenerator {
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

function New-MinimalToolBuildWorkspace {
    param(
        [string]$BuildRoot,
        [string]$BuildId,
        [bool]$BadBoundary,
        [bool]$Authority = $false,
        [bool]$ReviewEvidenceOnly = $true
    )

    New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
    $src = Join-Path $BuildRoot "source_automation_lab"
    New-Item -ItemType Directory -Path $src -Force | Out-Null
    $candidateDir = Join-Path $BuildRoot "candidate"
    $testsDir = Join-Path $BuildRoot "tests"
    New-Item -ItemType Directory -Path $candidateDir -Force | Out-Null
    New-Item -ItemType Directory -Path $testsDir -Force | Out-Null

    Set-Content -LiteralPath (Join-Path $candidateDir "README.md") -Value "# candidate`n" -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $testsDir "README.md") -Value "# tests`n" -Encoding UTF8

    $installAllowed = $BadBoundary
    $executionAllowed = $BadBoundary

    $idx = [ordered]@{
        schema_version             = "tool-build-index.v1"
        build_id                   = $BuildId
        source_request_id          = $BuildId
        authority                  = $Authority
        review_evidence_only       = $ReviewEvidenceOnly
        generated_code_present     = $false
        install_allowed            = $installAllowed
        execution_allowed          = $executionAllowed
        registry_modified          = $false
        tools_executed             = $false
        sandbox_worker_invoked     = $false
        capability_ids             = @("fixture.capability.example")
        primary_capability_outcome = "propose_new"
    }
    ($idx | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath (Join-Path $BuildRoot "BUILD_INDEX.json") -Encoding UTF8

    $proposal = @"
# Fixture proposal

generated_tool_execution_allowed: false

Proposed tool for listing example items (fixture text only).
"@
    Set-Content -LiteralPath (Join-Path $src "TOOL_PROPOSAL.md") -Value $proposal.TrimEnd() -Encoding UTF8
}

function Assert-CandidatePyStaticSafety {
    param([string]$Path)

    $text = Get-Content -Raw -LiteralPath $Path -Encoding UTF8
    Assert-True ($text -match "Review-only generated draft") "Expected review-only docstring."
    Assert-True ($text -notmatch '__name__') "Must not define __main__ entrypoint."
    Assert-True ($text -notmatch "(?i)\bimport\s+(requests|httpx|urllib)\b") "Must not import HTTP clients."
    Assert-True ($text -notmatch "(?i)\bimport\s+(registry|sandbox|tools|main)\b") "Must not import gateway/runtime modules."
    Assert-True ($text -notmatch "(?i)subprocess\.") "Must not use subprocess."
    Assert-True ($text -notmatch "(?i)\bopen\s*\(") "Must not call open()."
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$guardBefore = Get-GuardHashes -RepoRoot $RepoRoot
$toolsPyBefore = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8

$genPath = Join-Path $RepoRoot "scripts\automation_lab_generate_tool_candidate.ps1"
$genSrc = Get-Content -Raw -LiteralPath $genPath
Assert-True ($genSrc -notmatch '(?i)\bpython(\.exe)?\s') "Generator must not invoke Python interpreter."
Assert-True ($genSrc -notmatch '(?i)automation_lab\.py') "Generator must not invoke automation_lab.py."
Assert-True ($genSrc -notmatch '(?i)from\s+registry\b') "Generator must not import registry."
Assert-True ($genSrc -notmatch '(?i)from\s+sandbox\b') "Generator must not import sandbox."
Assert-True ($genSrc -match "authority must be false") "Generator must reject authority=true inputs."
Assert-True ($genSrc -match "review_evidence_only must be true") "Generator must reject non-review inputs."
Assert-True ($genSrc -match '\$originalIndexRaw\s*=\s*Get-Content -Raw -LiteralPath \$indexPath') "Generator must capture original BUILD_INDEX.json before mutation."
Assert-True ($genSrc -match 'Set-Content -LiteralPath \$indexPath -Value \$originalIndexRaw') "Generator must restore original BUILD_INDEX.json in catch."

$buildsRoot = Join-Path $RepoRoot "data\tool_builds"
if (-not (Test-Path -LiteralPath $buildsRoot)) {
    New-Item -ItemType Directory -Path $buildsRoot -Force | Out-Null
}

$positiveId = "tb_cand_$([Guid]::NewGuid().ToString('N').Substring(0, 12))"
$badBoundaryId = "tb_cand_bad_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
$badAuthorityId = "tb_cand_auth_$([Guid]::NewGuid().ToString('N').Substring(0, 9))"
$badReviewId = "tb_cand_rev_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
$rollbackId = "tb_cand_rb_$([Guid]::NewGuid().ToString('N').Substring(0, 11))"
$positiveRoot = Join-Path $buildsRoot $positiveId
$badBoundaryRoot = Join-Path $buildsRoot $badBoundaryId
$badAuthorityRoot = Join-Path $buildsRoot $badAuthorityId
$badReviewRoot = Join-Path $buildsRoot $badReviewId
$rollbackRoot = Join-Path $buildsRoot $rollbackId

try {
    New-MinimalToolBuildWorkspace -BuildRoot $positiveRoot -BuildId $positiveId -BadBoundary $false

    $r1 = Invoke-CandidateGenerator -ScriptPath $genPath -ToolBuildId $positiveId
    Assert-True ($r1.Code -eq 0) "Generator should succeed (exit $($r1.Code)). Output: $($r1.Output)"

    $candPy = Join-Path $positiveRoot "candidate\CANDIDATE_TOOL.py"
    $schema = Join-Path $positiveRoot "candidate\TOOL_SCHEMA.json"
    $notes = Join-Path $positiveRoot "candidate\CANDIDATE_NOTES.md"
    $risk = Join-Path $positiveRoot "candidate\RISK_NOTES.md"
    $testPlan = Join-Path $positiveRoot "tests\TEST_PLAN.md"

    foreach ($p in @($candPy, $schema, $notes, $risk, $testPlan)) {
        Assert-True (Test-Path -LiteralPath $p) "Missing output: $p"
    }

    Assert-CandidatePyStaticSafety -Path $candPy

    $schemaObj = Read-JsonFile -Path $schema
    Assert-True ($schemaObj.review_only -eq $true) "TOOL_SCHEMA.json review_only"
    Assert-True ($schemaObj.advisory -eq $true) "TOOL_SCHEMA.json advisory"

    $bi = Read-JsonFile -Path (Join-Path $positiveRoot "BUILD_INDEX.json")
    Assert-True ($bi.generated_code_present -eq $true) "generated_code_present"
    Assert-True ($bi.candidate_generation_completed -eq $true) "candidate_generation_completed"
    Assert-True ($bi.tests_generated -eq $false) "tests_generated must stay false"
    Assert-True ($bi.install_allowed -eq $false) "install_allowed"
    Assert-True ($bi.execution_allowed -eq $false) "execution_allowed"
    Assert-True ($bi.registry_modified -eq $false) "registry_modified"
    Assert-True ($bi.tools_executed -eq $false) "tools_executed"
    Assert-True ($bi.sandbox_worker_invoked -eq $false) "sandbox_worker_invoked"
    Assert-True ($bi.review_evidence_only -eq $true) "review_evidence_only"
    Assert-True ($bi.authority -eq $false) "authority"
    $cf = @($bi.candidate_files)
    Assert-True ($cf -contains "candidate/CANDIDATE_TOOL.py") "candidate_files list"
    Assert-True ($cf -contains "candidate/TOOL_SCHEMA.json") "candidate_files list"

    $r2 = Invoke-CandidateGenerator -ScriptPath $genPath -ToolBuildId $positiveId
    Assert-True ($r2.Code -ne 0) "Second run must fail (overwrite guard)."
    Assert-True ($r2.Output -match "refusing to overwrite") "Expected overwrite refusal message."

    # Bad boundary workspace
    New-MinimalToolBuildWorkspace -BuildRoot $badBoundaryRoot -BuildId $badBoundaryId -BadBoundary $true
    $rBad = Invoke-CandidateGenerator -ScriptPath $genPath -ToolBuildId $badBoundaryId
    Assert-True ($rBad.Code -ne 0) "Must reject when install/execution flags are not false."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $badBoundaryRoot "candidate\CANDIDATE_TOOL.py"))) "No candidate files on boundary failure."

    # Unsafe authority flags
    New-MinimalToolBuildWorkspace -BuildRoot $badAuthorityRoot -BuildId $badAuthorityId -BadBoundary $false -Authority $true
    $rAuth = Invoke-CandidateGenerator -ScriptPath $genPath -ToolBuildId $badAuthorityId
    Assert-True ($rAuth.Code -ne 0) "Must reject when authority is true."
    Assert-True ($rAuth.Output -match "authority must be false") "Expected authority rejection message."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $badAuthorityRoot "candidate\CANDIDATE_TOOL.py"))) "No candidate files on authority failure."

    New-MinimalToolBuildWorkspace -BuildRoot $badReviewRoot -BuildId $badReviewId -BadBoundary $false -ReviewEvidenceOnly $false
    $rReview = Invoke-CandidateGenerator -ScriptPath $genPath -ToolBuildId $badReviewId
    Assert-True ($rReview.Code -ne 0) "Must reject when review_evidence_only is false."
    Assert-True ($rReview.Output -match "review_evidence_only must be true") "Expected review_evidence_only rejection message."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $badReviewRoot "candidate\CANDIDATE_TOOL.py"))) "No candidate files on review_evidence_only failure."

    # Rollback on post-validation filesystem failure
    New-MinimalToolBuildWorkspace -BuildRoot $rollbackRoot -BuildId $rollbackId -BadBoundary $false
    $rollbackIndex = Join-Path $rollbackRoot "BUILD_INDEX.json"
    $rollbackOriginal = Get-Content -Raw -LiteralPath $rollbackIndex -Encoding UTF8
    try {
        Set-ItemProperty -LiteralPath $rollbackIndex -Name IsReadOnly -Value $true
        $rRollback = Invoke-CandidateGenerator -ScriptPath $genPath -ToolBuildId $rollbackId
    } finally {
        Set-ItemProperty -LiteralPath $rollbackIndex -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue
    }
    Assert-True ($rRollback.Code -ne 0) "Read-only BUILD_INDEX.json should force post-validation failure."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $rollbackRoot "candidate\CANDIDATE_TOOL.py"))) "Rollback must remove candidate output after failure."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $rollbackRoot "tests\TEST_PLAN.md"))) "Rollback must remove test plan after failure."
    $rollbackAfter = Get-Content -Raw -LiteralPath $rollbackIndex -Encoding UTF8
    Assert-True ($rollbackAfter -eq $rollbackOriginal) "Rollback must leave original BUILD_INDEX.json content intact."

    # Missing workspace
    $ghostId = "tb_cand_xx_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
    $rGhost = Invoke-CandidateGenerator -ScriptPath $genPath -ToolBuildId $ghostId
    Assert-True ($rGhost.Code -ne 0) "Missing workspace must fail."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $buildsRoot $ghostId))) "Must not create ghost workspace."

    # Invalid ids
    foreach ($bad in @("short", "has/slash", "..\\trav")) {
        $rb = Invoke-CandidateGenerator -ScriptPath $genPath -ToolBuildId $bad
        Assert-True ($rb.Code -ne 0) "Invalid ToolBuildId must fail: $bad"
    }

    $toolsPyAfter = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8
    Assert-True ($toolsPyAfter -eq $toolsPyBefore) "tools.py must not change (no copy into tools module)."
    Assert-True ($toolsPyAfter -notmatch "proposed_tool_placeholder") "tools.py must not contain candidate stub."

    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore
    Write-Host "OK: tool candidate generation tests passed."
} finally {
    foreach ($p in @($positiveRoot, $badBoundaryRoot, $badAuthorityRoot, $badReviewRoot, $rollbackRoot)) {
        $idx = Join-Path $p "BUILD_INDEX.json"
        if ($idx -and (Test-Path -LiteralPath $idx)) {
            Set-ItemProperty -LiteralPath $idx -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue
        }
        if ($p -and (Test-Path -LiteralPath $p)) {
            Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
