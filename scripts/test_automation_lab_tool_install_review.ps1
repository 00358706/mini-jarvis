# Tests for review-only install packaging (no install, no execution, no registry).

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

function Invoke-InstallReview {
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

function New-PassingTestResultsJson {
    param([string]$BuildId)

    $obj = [ordered]@{
        schema_version             = "generated-tool-test-results.v1"
        tool_build_id              = $BuildId
        created_at                 = "2026-05-12T00:00:00Z"
        test_harness_kind          = "static_review"
        candidate_code_executed    = $false
        sandbox_worker_invoked       = $false
        registry_modified            = $false
        tools_executed               = $false
        install_allowed              = $false
        execution_allowed            = $false
        real_service_calls           = $false
        overall_status               = "passed"
        checks                       = @()
    }
    return $obj | ConvertTo-Json -Depth 10
}

function New-InstallReviewFixture {
    param(
        [string]$BuildRoot,
        [string]$BuildId,
        [hashtable]$IndexOverrides,
        [string]$TestResultsJson,
        [bool]$OmitTestResults
    )

    New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
    $src = Join-Path $BuildRoot "source_automation_lab"
    New-Item -ItemType Directory -Path $src -Force | Out-Null
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
        test_harness_completed          = $true
        static_validation_completed     = $true
        candidate_code_executed         = $false
        install_allowed                 = $false
        execution_allowed               = $false
        registry_modified               = $false
        tools_executed                  = $false
        sandbox_worker_invoked          = $false
        capability_ids                  = @("fixture.cap.example")
    }
    if ($IndexOverrides) {
        foreach ($k in $IndexOverrides.Keys) {
            $idx[$k] = $IndexOverrides[$k]
        }
    }
    ($idx | ConvertTo-Json -Depth 12) | Set-Content -LiteralPath (Join-Path $BuildRoot "BUILD_INDEX.json") -Encoding UTF8

    Set-Content -LiteralPath (Join-Path $src "TOOL_PROPOSAL.md") -Value "# Proposal`ngenerated_tool_execution_allowed: false`n" -Encoding UTF8
    $pyBody = @'
"""Review-only stub."""
raise NotImplementedError
'@
    Set-Content -LiteralPath (Join-Path $candidateDir "CANDIDATE_TOOL.py") -Value $pyBody.TrimEnd() -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $candidateDir "TOOL_SCHEMA.json") -Value '{"review_only":true,"advisory":true}' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $candidateDir "CANDIDATE_NOTES.md") -Value "# n`n" -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $candidateDir "RISK_NOTES.md") -Value "# r`n" -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $testsDir "TEST_PLAN.md") -Value "# p`n" -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $BuildRoot "TEST_SUMMARY.md") -Value "# Static summary`n" -Encoding UTF8

    if (-not $OmitTestResults) {
        Set-Content -LiteralPath (Join-Path $BuildRoot "TEST_RESULTS.json") -Value $TestResultsJson -Encoding UTF8
    }
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$guardBefore = Get-GuardHashes -RepoRoot $RepoRoot
$toolsPyBefore = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8

$scriptPath = Join-Path $RepoRoot "scripts\automation_lab_create_tool_install_review.ps1"
$srcScan = Get-Content -Raw -LiteralPath $scriptPath
Assert-True ($srcScan -notmatch '(?i)python\s+-c|python\.exe\s+-c') "Script must not invoke Python."
Assert-True ($srcScan -notmatch '(?i)\bfrom\s+registry\b') "Script must not import registry."

$buildsRoot = Join-Path $RepoRoot "data\tool_builds"
if (-not (Test-Path -LiteralPath $buildsRoot)) {
    New-Item -ItemType Directory -Path $buildsRoot -Force | Out-Null
}

$goodId = "tb_inst_$([Guid]::NewGuid().ToString('N').Substring(0, 12))"
$missTrId = "tb_inst_notr_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$failTrId = "tb_inst_fail_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$unsafeId = "tb_inst_bad_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$dupId = "tb_inst_dup_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
$rollId = "tb_inst_roll_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"

$goodRoot = Join-Path $buildsRoot $goodId
$missRoot = Join-Path $buildsRoot $missTrId
$failRoot = Join-Path $buildsRoot $failTrId
$unsafeRoot = Join-Path $buildsRoot $unsafeId
$dupRoot = Join-Path $buildsRoot $dupId
$rollRoot = Join-Path $buildsRoot $rollId

$passingTr = New-PassingTestResultsJson -BuildId $goodId

try {
    # --- Positive ---
    New-InstallReviewFixture -BuildRoot $goodRoot -BuildId $goodId -IndexOverrides $null -TestResultsJson $passingTr -OmitTestResults $false

    $r1 = Invoke-InstallReview -ScriptPath $scriptPath -ToolBuildId $goodId
    Assert-True ($r1.Code -eq 0) "Positive run expected 0, got $($r1.Code). $($r1.Output)"

    $mf = Join-Path $goodRoot "INSTALL_MANIFEST.json"
    $rv = Join-Path $goodRoot "INSTALL_REVIEW.md"
    Assert-True (Test-Path -LiteralPath $mf) "INSTALL_MANIFEST.json missing."
    Assert-True (Test-Path -LiteralPath $rv) "INSTALL_REVIEW.md missing."

    $man = Read-JsonFile -Path $mf
    Assert-True ($man.schema_version -eq "tool-install-review-manifest.v1") "manifest schema"
    Assert-True ($man.install_performed -eq $false) "install_performed"
    Assert-True ($man.registry_modified -eq $false) "registry_modified"
    Assert-True ($man.execution_allowed -eq $false) "execution_allowed"
    Assert-True ($man.authority -eq $false) "authority"
    Assert-True ($man.review_only -eq $true) "review_only"
    Assert-True ($man.proposed_registry_entry_preview.status -eq "proposed_review_only") "preview status"

    $biGood = Read-JsonFile -Path (Join-Path $goodRoot "BUILD_INDEX.json")
    Assert-True ($biGood.install_review_created -eq $true) "install_review_created"
    Assert-True ($biGood.install_review_manifest_path -eq "INSTALL_MANIFEST.json") "manifest path"
    Assert-True ($biGood.install_review_path -eq "INSTALL_REVIEW.md") "review path"
    Assert-True ($biGood.install_allowed -eq $false) "install_allowed stays false"
    Assert-True ($biGood.execution_allowed -eq $false) "execution_allowed stays false"

    # --- Missing TEST_RESULTS ---
    New-InstallReviewFixture -BuildRoot $missRoot -BuildId $missTrId -IndexOverrides $null -TestResultsJson "" -OmitTestResults $true
    $rMiss = Invoke-InstallReview -ScriptPath $scriptPath -ToolBuildId $missTrId
    Assert-True ($rMiss.Code -eq 1) "Missing TEST_RESULTS must fail."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $missRoot "INSTALL_MANIFEST.json"))) "No manifest on missing TR."

    # --- Failed overall_status ---
    $failTrObj = (New-PassingTestResultsJson -BuildId $failTrId) | ConvertFrom-Json
    $failTrObj.overall_status = "failed"
    $failTrJson = $failTrObj | ConvertTo-Json -Depth 10
    New-InstallReviewFixture -BuildRoot $failRoot -BuildId $failTrId -IndexOverrides $null -TestResultsJson $failTrJson -OmitTestResults $false
    $rFail = Invoke-InstallReview -ScriptPath $scriptPath -ToolBuildId $failTrId
    Assert-True ($rFail.Code -eq 1) "Failed TEST_RESULTS must fail closed."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $failRoot "INSTALL_MANIFEST.json"))) "No manifest when TR failed."

    # --- Unsafe BUILD_INDEX ---
    $badIdx = @{
        authority            = $true
        install_allowed      = $true
        execution_allowed    = $true
        registry_modified    = $true
    }
    New-InstallReviewFixture -BuildRoot $unsafeRoot -BuildId $unsafeId -IndexOverrides $badIdx -TestResultsJson (New-PassingTestResultsJson -BuildId $unsafeId) -OmitTestResults $false
    $rUnsafe = Invoke-InstallReview -ScriptPath $scriptPath -ToolBuildId $unsafeId
    Assert-True ($rUnsafe.Code -eq 1) "Unsafe BUILD_INDEX must fail."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $unsafeRoot "INSTALL_MANIFEST.json"))) "No manifest on unsafe index."

    # --- Duplicate ---
    New-InstallReviewFixture -BuildRoot $dupRoot -BuildId $dupId -IndexOverrides $null -TestResultsJson (New-PassingTestResultsJson -BuildId $dupId) -OmitTestResults $false
    $rDup1 = Invoke-InstallReview -ScriptPath $scriptPath -ToolBuildId $dupId
    Assert-True ($rDup1.Code -eq 0) "First duplicate fixture run should pass."
    $rDup2 = Invoke-InstallReview -ScriptPath $scriptPath -ToolBuildId $dupId
    Assert-True ($rDup2.Code -eq 1) "Second run must refuse overwrite."
    Assert-True ($rDup2.Output -match "already exists|refusing") "Expected overwrite message."

    # --- Rollback (BUILD_INDEX read-only blocks final write) ---
    New-InstallReviewFixture -BuildRoot $rollRoot -BuildId $rollId -IndexOverrides $null -TestResultsJson (New-PassingTestResultsJson -BuildId $rollId) -OmitTestResults $false
    $idxRoll = Join-Path $rollRoot "BUILD_INDEX.json"
    [System.IO.File]::SetAttributes($idxRoll, [System.IO.FileAttributes]::ReadOnly)

    $rRoll = Invoke-InstallReview -ScriptPath $scriptPath -ToolBuildId $rollId
    Assert-True ($rRoll.Code -eq 4) "Rollback path should exit 4 (got $($rRoll.Code)). $($rRoll.Output)"

    [System.IO.File]::SetAttributes($idxRoll, [System.IO.FileAttributes]::Normal)
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $rollRoot "INSTALL_MANIFEST.json"))) "Manifest removed on rollback."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $rollRoot "INSTALL_REVIEW.md"))) "Review removed on rollback."
    $biRoll = Read-JsonFile -Path $idxRoll
    Assert-True ($biRoll.PSObject.Properties.Name -notcontains "install_review_created") "BUILD_INDEX must not record install review after failed finalize."

    # --- Invalid ids ---
    foreach ($bad in @("short", "has/slash", "..\\trav")) {
        $rb = Invoke-InstallReview -ScriptPath $scriptPath -ToolBuildId $bad
        Assert-True ($rb.Code -eq 1) "Invalid id must fail: $bad"
    }

    $toolsPyAfter = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8
    Assert-True ($toolsPyAfter -eq $toolsPyBefore) "tools.py unchanged."
    Assert-True ($toolsPyAfter -notmatch "proposed_tool_placeholder") "tools.py must not contain candidate stub."

    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore
    Write-Host "OK: tool install review packaging tests passed."
} finally {
    foreach ($p in @($goodRoot, $missRoot, $failRoot, $unsafeRoot, $dupRoot, $rollRoot)) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            Get-ChildItem -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
                $_.Attributes = 'Normal'
            }
            Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
