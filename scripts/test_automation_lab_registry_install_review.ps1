# Tests for persistent generated registry install (manual confirmation only).

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

function Select-Python {
    param([string]$RepoRoot)

    $candidates = @()
    if ($env:PYTHON -and $env:PYTHON.Trim()) {
        $candidates += $env:PYTHON.Trim()
    }
    $venvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        $candidates += $venvPy
    }
    $candidates += @("python", "py")

    foreach ($c in $candidates) {
        try {
            & $c -c "import sys" *> $null
            if ($LASTEXITCODE -eq 0) {
                return $c
            }
        } catch {
            continue
        }
    }
    throw "Could not find a working Python interpreter."
}

function Invoke-RegistryInstall {
    param(
        [string]$Py,
        [string]$RepoRoot,
        [string]$InstallPs1,
        [string]$ToolBuildId,
        [string]$Confirm
    )

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & powershell -ExecutionPolicy Bypass -File $InstallPs1 `
            -ToolBuildId $ToolBuildId `
            -ConfirmReviewedInstall $Confirm 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return [pscustomobject]@{ Code = $code; Output = $out }
}

function New-FullRegistryInstallFixture {
    param(
        [string]$BuildRoot,
        [string]$BuildId,
        [hashtable]$IndexOverrides
    )

    New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
    $src = Join-Path $BuildRoot "source_automation_lab"
    $candidateDir = Join-Path $BuildRoot "candidate"
    $testsDir = Join-Path $BuildRoot "tests"
    New-Item -ItemType Directory -Path $src -Force | Out-Null
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
        install_review_created          = $true
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

    Set-Content -LiteralPath (Join-Path $src "TOOL_PROPOSAL.md") -Value "# P`n" -Encoding UTF8
    $pyStub = @'
"""Review-only stub."""
raise NotImplementedError
'@
    Set-Content -LiteralPath (Join-Path $candidateDir "CANDIDATE_TOOL.py") -Value $pyStub.TrimEnd() -Encoding UTF8
    $schema = @{
        schema_kind     = "proposed_tool_interface"
        review_only     = $true
        advisory        = $true
        proposed_inputs = @{
            type       = "object"
            properties = @{
                limit = @{ type = "integer"; required = $false }
            }
            required   = @()
        }
    }
    ($schema | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath (Join-Path $candidateDir "TOOL_SCHEMA.json") -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $candidateDir "CANDIDATE_NOTES.md") -Value "# n`n" -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $candidateDir "RISK_NOTES.md") -Value "# r`n" -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $testsDir "TEST_PLAN.md") -Value "# p`n" -Encoding UTF8

    $tr = [ordered]@{
        schema_version             = "generated-tool-test-results.v1"
        tool_build_id              = $BuildId
        overall_status             = "passed"
        test_harness_kind          = "static_review"
        candidate_code_executed    = $false
        sandbox_worker_invoked       = $false
        registry_modified            = $false
        tools_executed               = $false
        install_allowed              = $false
        execution_allowed            = $false
        real_service_calls           = $false
    }
    ($tr | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath (Join-Path $BuildRoot "TEST_RESULTS.json") -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $BuildRoot "TEST_SUMMARY.md") -Value "# summary`n" -Encoding UTF8

    $manifest = [ordered]@{
        schema_version               = "tool-install-review-manifest.v1"
        tool_build_id                = $BuildId
        review_only                  = $true
        authority                    = $false
        install_performed            = $false
        install_allowed              = $false
        execution_allowed            = $false
        registry_modified            = $false
        tools_executed               = $false
        sandbox_worker_invoked       = $false
        candidate_code_executed      = $false
    }
    ($manifest | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath (Join-Path $BuildRoot "INSTALL_MANIFEST.json") -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $BuildRoot "INSTALL_REVIEW.md") -Value "# install review`n" -Encoding UTF8
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$Py = Select-Python -RepoRoot $RepoRoot
$guardBefore = Get-GuardHashes -RepoRoot $RepoRoot
$toolsPyBefore = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8

$genRegPath = Join-Path $RepoRoot "data\registry\generated_installed_tools.json"
$genBackup = Get-Content -Raw -LiteralPath $genRegPath -Encoding UTF8

$installPs1 = Join-Path $RepoRoot "scripts\automation_lab_install_reviewed_tool.ps1"
$helperPy = Join-Path $RepoRoot "scripts\registry_append_reviewed_generated_tool.py"
$helperSrc = Get-Content -Raw -LiteralPath $helperPy
$installSrc = Get-Content -Raw -LiteralPath $installPs1

Assert-True ($helperSrc -notmatch 'run_tool_by_name') "Helper must not call run_tool_by_name."
Assert-True ($helperSrc -notmatch '(?i)\bimport\s+sandbox\b') "Helper must not import sandbox."
Assert-True ($helperSrc -notmatch '(?i)import\s+candidate') "Helper must not import candidate."
Assert-True ($helperSrc -notmatch '_registry\s*\[') "Helper must not assign _registry directly."
Assert-True ($installSrc -notmatch 'run_tool_by_name') "Install script must not call run_tool_by_name."

$buildsRoot = Join-Path $RepoRoot "data\tool_builds"
if (-not (Test-Path -LiteralPath $buildsRoot)) {
    New-Item -ItemType Directory -Path $buildsRoot -Force | Out-Null
}

$goodId = "tb_reg_$([Guid]::NewGuid().ToString('N').Substring(0, 12))"
$dupId = "tb_regdup_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
$unsafeId = "tb_regbad_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
$rollId = "tb_regroll_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"

$goodRoot = Join-Path $buildsRoot $goodId
$dupRoot = Join-Path $buildsRoot $dupId
$unsafeRoot = Join-Path $buildsRoot $unsafeId
$rollRoot = Join-Path $buildsRoot $rollId

$expectedName = "generated_$($goodId -replace '[^a-zA-Z0-9_]', '_')"

try {
    # --- Wrong confirmation ---
    New-FullRegistryInstallFixture -BuildRoot $goodRoot -BuildId $goodId -IndexOverrides $null
    $hashBeforeBad = (Get-FileHash -Algorithm SHA256 -LiteralPath $genRegPath).Hash
    $rBad = Invoke-RegistryInstall -Py $Py -RepoRoot $RepoRoot -InstallPs1 $installPs1 -ToolBuildId $goodId -Confirm "WRONG"
    Assert-True ($rBad.Code -eq 1) "Wrong phrase must fail."
    $hashAfterBad = (Get-FileHash -Algorithm SHA256 -LiteralPath $genRegPath).Hash
    Assert-True ($hashAfterBad -eq $hashBeforeBad) "Registry JSON unchanged on bad phrase."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $goodRoot "REGISTRY_INSTALL_RECORD.json"))) "No record on bad phrase."

    # --- Positive install ---
    $rOk = Invoke-RegistryInstall -Py $Py -RepoRoot $RepoRoot -InstallPs1 $installPs1 -ToolBuildId $goodId -Confirm "INSTALL_REVIEWED_TOOL"
    Assert-True ($rOk.Code -eq 0) "Install should succeed. $($rOk.Output)"

    $rec = Join-Path $goodRoot "REGISTRY_INSTALL_RECORD.json"
    $sum = Join-Path $goodRoot "REGISTRY_INSTALL_SUMMARY.md"
    Assert-True (Test-Path -LiteralPath $rec) "REGISTRY_INSTALL_RECORD.json missing."
    Assert-True (Test-Path -LiteralPath $sum) "REGISTRY_INSTALL_SUMMARY.md missing."

    $pyVerify = "import sys; from pathlib import Path; sys.path.insert(0, r'$RepoRoot'); import registry as r; e=r.get('$expectedName','v1'); assert e is not None and e.status=='installed' and e.endpoint.startswith('internal://generated/')"
    & $Py -c $pyVerify
    if ($LASTEXITCODE -ne 0) {
        throw "Fresh Python import must see generated tool metadata."
    }

    $bi = Read-JsonFile -Path (Join-Path $goodRoot "BUILD_INDEX.json")
    Assert-True ($bi.registry_install_review_completed -eq $true) "registry_install_review_completed"
    Assert-True ($bi.registry_modified -eq $true) "registry_modified on BUILD_INDEX"
    Assert-True ($bi.install_performed -eq $true) "install_performed"
    Assert-True ($bi.execution_allowed -eq $false) "execution_allowed stays false"

    # --- Duplicate install (same goodId, evidence already exists) ---
    $rDup2 = Invoke-RegistryInstall -Py $Py -RepoRoot $RepoRoot -InstallPs1 $installPs1 -ToolBuildId $goodId -Confirm "INSTALL_REVIEWED_TOOL"
    Assert-True ($rDup2.Code -ne 0) "Duplicate install must fail."

    # --- Unsafe BUILD_INDEX ---
    New-FullRegistryInstallFixture -BuildRoot $unsafeRoot -BuildId $unsafeId -IndexOverrides @{ authority = $true }
    $rUnsafe = Invoke-RegistryInstall -Py $Py -RepoRoot $RepoRoot -InstallPs1 $installPs1 -ToolBuildId $unsafeId -Confirm "INSTALL_REVIEWED_TOOL"
    Assert-True ($rUnsafe.Code -ne 0) "Unsafe BUILD_INDEX must fail."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $unsafeRoot "REGISTRY_INSTALL_RECORD.json"))) "No record for unsafe."

    # --- Duplicate install (same tool_build twice) ---
    New-FullRegistryInstallFixture -BuildRoot $dupRoot -BuildId $dupId -IndexOverrides $null
    $rD1 = Invoke-RegistryInstall -Py $Py -RepoRoot $RepoRoot -InstallPs1 $installPs1 -ToolBuildId $dupId -Confirm "INSTALL_REVIEWED_TOOL"
    Assert-True ($rD1.Code -eq 0) "First dup fixture install ok."
    $rD2 = Invoke-RegistryInstall -Py $Py -RepoRoot $RepoRoot -InstallPs1 $installPs1 -ToolBuildId $dupId -Confirm "INSTALL_REVIEWED_TOOL"
    Assert-True ($rD2.Code -ne 0) "Second install same id must fail."

    # --- Rollback (read-only BUILD_INDEX blocks final write) ---
    New-FullRegistryInstallFixture -BuildRoot $rollRoot -BuildId $rollId -IndexOverrides $null
    $idxRoll = Join-Path $rollRoot "BUILD_INDEX.json"
    [System.IO.File]::SetAttributes($idxRoll, [System.IO.FileAttributes]::ReadOnly)
    $hashRegBeforeRoll = (Get-FileHash -Algorithm SHA256 -LiteralPath $genRegPath).Hash
    $rRoll = Invoke-RegistryInstall -Py $Py -RepoRoot $RepoRoot -InstallPs1 $installPs1 -ToolBuildId $rollId -Confirm "INSTALL_REVIEWED_TOOL"
    [System.IO.File]::SetAttributes($idxRoll, [System.IO.FileAttributes]::Normal)
    Assert-True ($rRoll.Code -ne 0) "Rollback scenario should fail (exit $($rRoll.Code))."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $rollRoot "REGISTRY_INSTALL_RECORD.json"))) "No install record after rollback failure."
    $hashRegAfterRoll = (Get-FileHash -Algorithm SHA256 -LiteralPath $genRegPath).Hash
    Assert-True ($hashRegAfterRoll -eq $hashRegBeforeRoll) "generated_installed_tools.json stable after failed finalize."
    $biRollAfter = Read-JsonFile -Path $idxRoll
    Assert-True ($biRollAfter.PSObject.Properties.Name -notcontains "registry_install_review_completed") "BUILD_INDEX not updated after rollback failure."

    foreach ($bad in @("short", "has/slash", "..\\trav")) {
        $rb = Invoke-RegistryInstall -Py $Py -RepoRoot $RepoRoot -InstallPs1 $installPs1 -ToolBuildId $bad -Confirm "INSTALL_REVIEWED_TOOL"
        Assert-True ($rb.Code -ne 0) "Invalid id must fail: $bad"
    }

    $toolsPyAfter = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8
    Assert-True ($toolsPyAfter -eq $toolsPyBefore) "tools.py unchanged."
    Assert-True ($toolsPyAfter -notmatch "proposed_tool_placeholder") "No candidate stub in tools.py."

    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore
    Write-Host "OK: registry install review tests passed."
} finally {
    Set-Content -LiteralPath $genRegPath -Value $genBackup -Encoding UTF8
    foreach ($p in @($goodRoot, $dupRoot, $unsafeRoot, $rollRoot)) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
