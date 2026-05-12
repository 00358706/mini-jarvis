# Tests for generated-tool dry-run (review evidence only; no execution, no registry mutation).

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

function Get-DryRunDirCount {
    param([string]$DryRoot)
    if (-not (Test-Path -LiteralPath $DryRoot)) {
        return 0
    }
    return (Get-ChildItem -LiteralPath $DryRoot -Directory -ErrorAction SilentlyContinue | Measure-Object).Count
}

function Invoke-DryRun {
    param(
        [string]$RepoRoot,
        [string]$DryRunPs1,
        [string]$ToolName,
        [string]$Version
    )

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $psiArgs = @(
            '-ExecutionPolicy', 'Bypass',
            '-File', $DryRunPs1,
            '-ToolName', $ToolName,
            '-Version', $Version
        )
        $out = & powershell.exe @psiArgs 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return [pscustomobject]@{ Code = $code; Output = $out }
}

function Merge-GeneratedRegistryRows {
    param(
        [string]$GenRegPath,
        [object[]]$ExtraRows
    )

    $raw = Get-Content -Raw -LiteralPath $GenRegPath -Encoding UTF8
    $arr = $raw | ConvertFrom-Json
    if ($null -eq $arr) {
        $arr = @()
    }
    if ($arr -isnot [System.Array]) {
        $arr = @($arr)
    }
    foreach ($row in $ExtraRows) {
        $arr += $row
    }
    $json = $arr | ConvertTo-Json -Depth 20 -Compress
    Set-Content -LiteralPath $GenRegPath -Value $json -Encoding UTF8
}

function Get-NewestDryRunEvidenceDir {
    param(
        [string]$DryRoot,
        [string[]]$SnapshotBefore
    )

    if (-not (Test-Path -LiteralPath $DryRoot)) {
        return $null
    }
    $candidates = Get-ChildItem -LiteralPath $DryRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $SnapshotBefore -notcontains $_.FullName }
    if (-not $candidates) {
        return $null
    }
    return ($candidates | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).FullName
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$Py = Select-Python -RepoRoot $RepoRoot
$guardBefore = Get-GuardHashes -RepoRoot $RepoRoot
$toolsPyBefore = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8

$genRegPath = Join-Path $RepoRoot "data\registry\generated_installed_tools.json"
$genBackup = Get-Content -Raw -LiteralPath $genRegPath -Encoding UTF8

$dryRunPs1 = Join-Path $RepoRoot "scripts\automation_lab_generated_tool_dry_run.ps1"
$helperPy = Join-Path $RepoRoot "scripts\generated_tool_dry_run.py"
$helperSrc = Get-Content -Raw -LiteralPath $helperPy -Encoding UTF8
$dryPsSrc = Get-Content -Raw -LiteralPath $dryRunPs1 -Encoding UTF8

Assert-True ($helperSrc -notmatch '(?i)\bimport\s+sandbox\b') "Dry-run helper must not import sandbox."
Assert-True ($helperSrc -notmatch '(?im)^\s*from\s+sandbox\s+import\b') "Dry-run helper must not import from sandbox."
Assert-True ($helperSrc -notmatch '(?im)^\s*from\s+tools\s+import\b') "Dry-run helper must not import from tools."
Assert-True ($helperSrc -notmatch '(?im)^\s*import\s+tools\b') "Dry-run helper must not import tools."
Assert-True ($helperSrc -notmatch '(?im)^\s*from\s+tools\s+import\s+.*_TOOL_FUNCS') "Dry-run helper must not import _TOOL_FUNCS."
Assert-True ($helperSrc -notmatch '(?i)run_tool_by_name') "Dry-run helper must not call run_tool_by_name."
Assert-True ($helperSrc -notmatch '(?i)import\s+candidate') "Dry-run helper must not import candidate."
Assert-True ($dryPsSrc -notmatch '(?i)run_tool_by_name') "Dry-run PS1 must not call run_tool_by_name."

$suffix = [Guid]::NewGuid().ToString("N").Substring(0, 10)
$okName = "generated_dryrun_ok_$suffix"
$missingName = "generated_dryrun_missing_$suffix"
$badEpName = "generated_dryrun_badendpoint_$suffix"
$proposedName = "generated_dryrun_proposedonly_$suffix"

$dryRoot = Join-Path $RepoRoot "data\generated_tool_dry_runs"

try {
    # --- Malformed CLI: no new dry-run directories ---
    $countBeforeBad = Get-DryRunDirCount -DryRoot $dryRoot
    foreach ($bad in @(
            @{ n = "radarr_search"; v = "v1" },
            @{ n = "generated_BADCASE_$suffix"; v = "v1" },
            @{ n = "generated_/slash_$suffix"; v = "v1" },
            @{ n = "generated_has space_$suffix"; v = "v1" },
            @{ n = $okName; v = "v1.0" }
        )) {
        $r = Invoke-DryRun -RepoRoot $RepoRoot -DryRunPs1 $dryRunPs1 -ToolName $bad.n -Version $bad.v
        Assert-True ($r.Code -eq 1) "Malformed CLI must exit 1 for $($bad.n) / $($bad.v)."
    }
    $countAfterBad = Get-DryRunDirCount -DryRoot $dryRoot
    Assert-True ($countAfterBad -eq $countBeforeBad) "Malformed CLI must not create dry-run evidence dirs."

    # --- Fixture rows in persistent generated registry JSON ---
    $fixtureRows = @(
        [ordered]@{
            name         = $okName
            version      = "v1"
            endpoint     = "internal://generated/$okName"
            input_schema = @{}
            permissions  = @()
            description  = "dry-run test fixture"
            status       = "installed"
        },
        [ordered]@{
            name         = $badEpName
            version      = "v1"
            endpoint     = "internal://tools/inspect_file"
            input_schema = @{}
            permissions  = @()
            description  = "wrong endpoint fixture"
            status       = "installed"
        },
        [ordered]@{
            name         = $proposedName
            version      = "v1"
            endpoint     = "internal://generated/$proposedName"
            input_schema = @{}
            permissions  = @()
            description  = "not installed status"
            status       = "proposed"
        }
    )
    Merge-GeneratedRegistryRows -GenRegPath $genRegPath -ExtraRows $fixtureRows

    $pyVerify = "import sys; sys.path.insert(0, r'$RepoRoot'); import registry as r; e=r.get('$okName','v1'); assert e and e.status=='installed'"
    & $Py -c $pyVerify
    Assert-True ($LASTEXITCODE -eq 0) "Fresh registry import must see fixture metadata."

    # --- Successful dry-run ---
    $snapOk = @()
    if (Test-Path -LiteralPath $dryRoot) {
        $snapOk = @(Get-ChildItem -LiteralPath $dryRoot -Directory | ForEach-Object { $_.FullName })
    }
    $rOk = Invoke-DryRun -RepoRoot $RepoRoot -DryRunPs1 $dryRunPs1 -ToolName $okName -Version "v1"
    Assert-True ($rOk.Code -eq 0) "Dry-run must pass for installed generated metadata. $($rOk.Output)"
    $evDir = Get-NewestDryRunEvidenceDir -DryRoot $dryRoot -SnapshotBefore $snapOk
    Assert-True ($null -ne $evDir) "Successful dry-run must create a directory."
    $resultPath = Join-Path $evDir "DRY_RUN_RESULT.json"
    $summaryPath = Join-Path $evDir "DRY_RUN_SUMMARY.md"
    Assert-True (Test-Path -LiteralPath $resultPath) "DRY_RUN_RESULT.json missing."
    Assert-True (Test-Path -LiteralPath $summaryPath) "DRY_RUN_SUMMARY.md missing."

    $ev = Read-JsonFile -Path $resultPath
    Assert-True ($ev.schema_version -eq "generated-tool-dry-run.v1") "schema_version"
    Assert-True ($ev.overall_status -eq "passed") "overall_status passed"
    Assert-True ($ev.callable_dispatch_present -eq $false) "no dispatch"
    Assert-True ($ev.candidate_code_executed -eq $false) "no candidate execution"
    Assert-True ($ev.sandbox_worker_invoked -eq $false) "no sandbox"
    Assert-True ($ev.tools_executed -eq $false) "tools_executed"
    Assert-True ($ev.real_service_calls -eq $false) "real_service_calls"
    Assert-True ($ev.execution_allowed -eq $false) "execution_allowed"
    Assert-True ($ev.dry_run_only -eq $true) "dry_run_only"
    $summaryText = Get-Content -Raw -LiteralPath $summaryPath -Encoding UTF8
    Assert-True ($summaryText -match '`callable_dispatch_present`: false') "summary includes callable_dispatch_present false"

    # --- run_tool_by_name safe failure (no sandbox) ---
    $pyRun = "import sys,asyncio; sys.path.insert(0, r'$RepoRoot'); from tools import run_tool_by_name; r=asyncio.run(run_tool_by_name('$okName', {})); assert not r.success and r.error and 'Unknown tool implementation' in r.error"
    & $Py -c $pyRun
    Assert-True ($LASTEXITCODE -eq 0) "run_tool_by_name must fail safely without executing candidate code."

    # --- Not in registry ---
    $snapMiss = @(Get-ChildItem -LiteralPath $dryRoot -Directory | ForEach-Object { $_.FullName })
    $rMiss = Invoke-DryRun -RepoRoot $RepoRoot -DryRunPs1 $dryRunPs1 -ToolName $missingName -Version "v1"
    Assert-True ($rMiss.Code -ne 0) "Missing tool dry-run must be nonzero."
    $missDir = Get-NewestDryRunEvidenceDir -DryRoot $dryRoot -SnapshotBefore $snapMiss
    Assert-True ($null -ne $missDir) "Failed dry-run must write evidence directory."
    $missEv = Join-Path $missDir "DRY_RUN_RESULT.json"
    $missJson = Read-JsonFile -Path $missEv
    Assert-True ($missJson.overall_status -eq "failed") "Missing tool must write failed evidence."

    # --- Version mismatch ---
    $snapVer = @(Get-ChildItem -LiteralPath $dryRoot -Directory | ForEach-Object { $_.FullName })
    $rVer = Invoke-DryRun -RepoRoot $RepoRoot -DryRunPs1 $dryRunPs1 -ToolName $okName -Version "v99"
    Assert-True ($rVer.Code -ne 0) "Version mismatch must fail."
    $verDir = Get-NewestDryRunEvidenceDir -DryRoot $dryRoot -SnapshotBefore $snapVer
    $verJson = Read-JsonFile -Path (Join-Path $verDir "DRY_RUN_RESULT.json")
    Assert-True ($verJson.overall_status -eq "failed") "Version mismatch evidence failed."

    # --- Status not installed (on disk only) ---
    $snapProp = @(Get-ChildItem -LiteralPath $dryRoot -Directory | ForEach-Object { $_.FullName })
    $rProp = Invoke-DryRun -RepoRoot $RepoRoot -DryRunPs1 $dryRunPs1 -ToolName $proposedName -Version "v1"
    Assert-True ($rProp.Code -ne 0) "Proposed-only row must fail dry-run."
    $propDir = Get-NewestDryRunEvidenceDir -DryRoot $dryRoot -SnapshotBefore $snapProp
    $propJson = Read-JsonFile -Path (Join-Path $propDir "DRY_RUN_RESULT.json")
    Assert-True ($propJson.overall_status -eq "failed") "Proposed row evidence failed."
    Assert-True ($propJson.notes -match "status") "Notes should mention status."

    # --- Wrong endpoint (loaded into registry) ---
    $snapBad = @(Get-ChildItem -LiteralPath $dryRoot -Directory | ForEach-Object { $_.FullName })
    $rBadEp = Invoke-DryRun -RepoRoot $RepoRoot -DryRunPs1 $dryRunPs1 -ToolName $badEpName -Version "v1"
    Assert-True ($rBadEp.Code -ne 0) "Wrong endpoint must fail."
    $badDir = Get-NewestDryRunEvidenceDir -DryRoot $dryRoot -SnapshotBefore $snapBad
    $badJson = Read-JsonFile -Path (Join-Path $badDir "DRY_RUN_RESULT.json")
    Assert-True ($badJson.overall_status -eq "failed") "Wrong endpoint evidence failed."
    Assert-True ($badJson.notes -match "internal://generated") "Notes should mention endpoint prefix."

    $toolsPyAfter = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8
    Assert-True ($toolsPyAfter -eq $toolsPyBefore) "tools.py unchanged."

    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore
    Write-Host "OK: generated tool dry-run tests passed."
} finally {
    Set-Content -LiteralPath $genRegPath -Value $genBackup -Encoding UTF8
}
