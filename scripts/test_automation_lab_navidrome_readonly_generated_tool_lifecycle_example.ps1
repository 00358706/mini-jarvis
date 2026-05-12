# Offline lifecycle EXAMPLE: Navidrome read-only generated-tool path through evidence, metadata install, and dry-run.
# This is NOT a Navidrome runtime integration test — execution remains unwired; no real Navidrome calls.

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

function Get-DeterministicGeneratedToolName {
    param([string]$ToolBuildId)

    $s = $ToolBuildId.Trim()
    $s = [regex]::Replace($s, '[^a-zA-Z0-9_]', '_')
    $s = [regex]::Replace($s, '_+', '_').Trim('_')
    if ([string]::IsNullOrWhiteSpace($s)) {
        throw "tool_build_id sanitizes to empty"
    }
    $n = "generated_$s"
    if ($n.Length -gt 120) {
        $n = $n.Substring(0, 120).TrimEnd('_')
    }
    return $n
}

function Get-DryRunDirSnapshot {
    param([string]$DryRoot)

    if (-not (Test-Path -LiteralPath $DryRoot)) {
        return @()
    }
    return @(Get-ChildItem -LiteralPath $DryRoot -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { $_.FullName })
}

function Compare-NewDryRunDirs {
    param(
        [string[]]$Before,
        [string[]]$After
    )

    $bSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($x in $Before) { [void]$bSet.Add($x) }
    return @($After | Where-Object { -not $bSet.Contains($_) })
}

function Invoke-ChildPs1 {
    param(
        [string]$ScriptPath,
        [string[]]$ArgumentList
    )

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $psiArgs = @('-ExecutionPolicy', 'Bypass', '-File', $ScriptPath) + $ArgumentList
        $out = & powershell.exe @psiArgs 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return [pscustomobject]@{ Code = $code; Output = $out }
}

function Assert-NavidromeReadonlyBoundaryText {
    param(
        [string]$Label,
        [string]$Text
    )

    if ([string]::IsNullOrWhiteSpace($Text)) {
        throw "$Label is empty."
    }
    Assert-True ($Text -cmatch 'read-only|read only') "$Label must document read-only scope."
    Assert-True ($Text -match '(?i)no\s+playlist') "$Label must state no playlist edits."
    Assert-True ($Text -match '(?i)no\s+downloads') "$Label must state no downloads."
    Assert-True ($Text -match '(?i)no\s+deletes') "$Label must state no deletes."
    Assert-True ($Text -match '(?i)no\s+playback') "$Label must state no playback control."
    Assert-True ($Text -match '(?i)no\s+real\s+service') "$Label must state no real service calls."
    Assert-True ($Text -match '(?i)NAVIDROME_URL') "$Label must document NAVIDROME_URL (name only)."
    Assert-True ($Text -match '(?i)NAVIDROME_TOKEN') "$Label must document NAVIDROME_TOKEN (name only)."
}

function New-NavidromeReadonlyLabFixture {
    param(
        [string]$SourceDir,
        [string]$RequestId
    )

    New-Item -ItemType Directory -Path $SourceDir -Force | Out-Null

    $indexObj = [ordered]@{
        schema_version             = "automation-lab-review-artifact-index.v1"
        authority                  = $false
        request_id                 = $RequestId
        proposal_kind              = "tool_proposal"
        primary_capability_outcome = "propose_new"
        created_at                 = "2026-05-11T12:00:00Z"
        authority_boundary         = @{
            proposal_only                   = $true
            registry_modified               = $false
            tools_executed                  = $false
            sandbox_worker_invoked          = $false
            registry_is_execution_truth     = $true
            generated_tool_execution_allowed = $false
        }
    }
    ($indexObj | ConvertTo-Json -Depth 12) | Set-Content -LiteralPath (Join-Path $SourceDir "INDEX.json") -Encoding UTF8

    $capObj = [ordered]@{
        schema_version         = "automation-lab-capability-matches.v3"
        authority              = $false
        request_id             = $RequestId
        capability_ids         = @("navidrome_recently_added_albums")
        primary_outcome        = "propose_new"
        primary_outcome_source = "deterministic_template"
        evidence_sources       = @("deterministic_template", "registry_readonly")
        score                  = 70
        precedence_applied     = "fixture_test_lane_merge"
        conflicts              = @()
        authority_boundary     = @{
            proposal_only     = $true
            registry_modified = $false
        }
    }
    ($capObj | ConvertTo-Json -Depth 12) | Set-Content -LiteralPath (Join-Path $SourceDir "CAPABILITY_MATCHES.json") -Encoding UTF8

    # First ~400 chars are embedded into CANDIDATE_NOTES by candidate generation — keep boundaries in the excerpt window.
    $proposal = @"
# navidrome_recently_added_albums (lifecycle example only — not a runnable integration)

read-only. No playlist edits. No downloads. No deletes. No playback control. No real service calls in this artifact.

Future config (environment variable names only — do not put secrets in repo): NAVIDROME_URL, NAVIDROME_TOKEN.

Capability id: navidrome_recently_added_albums — list recently added albums from Navidrome library metadata (read-only GET semantics). Network scope for a future implementation: Navidrome base URL only. Side effects: none. Risk: low / read-only.

generated_tool_execution_allowed: false

This proposal exists only to exercise the reviewed generated-tool lifecycle (build, static harness, install review packaging, metadata registry install, dry-run). Navidrome execution is not implemented on this branch.
"@
    Set-Content -LiteralPath (Join-Path $SourceDir "TOOL_PROPOSAL.md") -Value $proposal.TrimEnd() -Encoding UTF8
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$labRoot = Join-Path $RepoRoot "data\automation_lab"
$buildsRoot = Join-Path $RepoRoot "data\tool_builds"
$dryRunsRoot = Join-Path $RepoRoot "data\generated_tool_dry_runs"
$genRegPath = Join-Path $RepoRoot "data\registry\generated_installed_tools.json"

if (-not (Test-Path -LiteralPath $labRoot)) {
    New-Item -ItemType Directory -Path $labRoot -Force | Out-Null
}
if (-not (Test-Path -LiteralPath $buildsRoot)) {
    New-Item -ItemType Directory -Path $buildsRoot -Force | Out-Null
}

$requestId = "nv_ro_ex_$([Guid]::NewGuid().ToString('N').Substring(0, 12))"
Assert-True ($requestId -cmatch '^[A-Za-z0-9_-]{8,80}$') "requestId must match lifecycle id pattern."

$labSource = Join-Path $labRoot $requestId
$buildRoot = Join-Path $buildsRoot $requestId

$genBackupBytes = [System.IO.File]::ReadAllBytes($genRegPath)
$toolsPyBefore = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8
$guardBefore = Get-GuardHashes -RepoRoot $RepoRoot

$expectedGeneratedName = Get-DeterministicGeneratedToolName -ToolBuildId $requestId

$psCreateBuild = Join-Path $RepoRoot "scripts\automation_lab_create_tool_build.ps1"
$psGenCand = Join-Path $RepoRoot "scripts\automation_lab_generate_tool_candidate.ps1"
$psTestCand = Join-Path $RepoRoot "scripts\automation_lab_test_tool_candidate.ps1"
$psInstallReview = Join-Path $RepoRoot "scripts\automation_lab_create_tool_install_review.ps1"
$psRegistryInstall = Join-Path $RepoRoot "scripts\automation_lab_install_reviewed_tool.ps1"
$psDryRun = Join-Path $RepoRoot "scripts\automation_lab_generated_tool_dry_run.ps1"

$newDryRunDirs = @()

try {
    New-NavidromeReadonlyLabFixture -SourceDir $labSource -RequestId $requestId

    $rBuild = Invoke-ChildPs1 -ScriptPath $psCreateBuild -ArgumentList @('-AutomationLabRequestId', $requestId)
    Assert-True ($rBuild.Code -eq 0) "create_tool_build failed: $($rBuild.Output)"

    $rGen = Invoke-ChildPs1 -ScriptPath $psGenCand -ArgumentList @('-ToolBuildId', $requestId)
    Assert-True ($rGen.Code -eq 0) "generate_tool_candidate failed: $($rGen.Output)"

    $proposalPath = Join-Path $buildRoot "source_automation_lab\TOOL_PROPOSAL.md"
    $notesPath = Join-Path $buildRoot "candidate\CANDIDATE_NOTES.md"
    $schemaPath = Join-Path $buildRoot "candidate\TOOL_SCHEMA.json"
    $candidatePyPath = Join-Path $buildRoot "candidate\CANDIDATE_TOOL.py"

    Assert-True (Test-Path -LiteralPath $candidatePyPath) "CANDIDATE_TOOL.py missing."
    Assert-True (Test-Path -LiteralPath $schemaPath) "TOOL_SCHEMA.json missing."

    $proposalText = Get-Content -Raw -LiteralPath $proposalPath -Encoding UTF8
    $notesText = Get-Content -Raw -LiteralPath $notesPath -Encoding UTF8
    Assert-NavidromeReadonlyBoundaryText -Label "TOOL_PROPOSAL.md" -Text $proposalText
    Assert-NavidromeReadonlyBoundaryText -Label "CANDIDATE_NOTES.md (includes proposal excerpt)" -Text $notesText

    $candPy = Get-Content -Raw -LiteralPath $candidatePyPath -Encoding UTF8
    Assert-True ($candPy -match 'NotImplementedError') "Candidate stub must remain non-executable."
    Assert-True ($candPy -notmatch '(?i)\b(httpx|requests\.|urllib3|aiohttp)\b') "Candidate stub must not reference HTTP client libraries."

    $rHarness = Invoke-ChildPs1 -ScriptPath $psTestCand -ArgumentList @('-ToolBuildId', $requestId)
    Assert-True ($rHarness.Code -eq 0) "test_tool_candidate failed: $($rHarness.Output)"

    $rPack = Invoke-ChildPs1 -ScriptPath $psInstallReview -ArgumentList @('-ToolBuildId', $requestId)
    Assert-True ($rPack.Code -eq 0) "create_tool_install_review failed: $($rPack.Output)"

    $rReg = Invoke-ChildPs1 -ScriptPath $psRegistryInstall -ArgumentList @(
        '-ToolBuildId', $requestId,
        '-ConfirmReviewedInstall', 'INSTALL_REVIEWED_TOOL'
    )
    Assert-True ($rReg.Code -eq 0) "install_reviewed_tool failed: $($rReg.Output)"

    $py = Select-Python -RepoRoot $RepoRoot
    $pyVerify = "import sys; sys.path.insert(0, r'$RepoRoot'); import registry as r; e=r.get('$expectedGeneratedName','v1'); assert e and e.status=='installed'"
    & $py -c $pyVerify
    Assert-True ($LASTEXITCODE -eq 0) "Registry must list metadata for $expectedGeneratedName after install."

    $drySnapBefore = Get-DryRunDirSnapshot -DryRoot $dryRunsRoot
    $rDry = Invoke-ChildPs1 -ScriptPath $psDryRun -ArgumentList @(
        '-ToolName', $expectedGeneratedName,
        '-Version', 'v1'
    )
    Assert-True ($rDry.Code -eq 0) "generated_tool_dry_run failed: $($rDry.Output)"

    $drySnapAfter = Get-DryRunDirSnapshot -DryRoot $dryRunsRoot
    $newDirs = Compare-NewDryRunDirs -Before $drySnapBefore -After $drySnapAfter
    Assert-True ($newDirs.Count -ge 1) "Dry-run must create a new directory under data/generated_tool_dry_runs (snapshot diff)."

    $picked = $null
    foreach ($d in $newDirs) {
        $j = Join-Path $d "DRY_RUN_RESULT.json"
        if (-not (Test-Path -LiteralPath $j)) { continue }
        $dj = Read-JsonFile -Path $j
        if ($dj.tool_name -eq $expectedGeneratedName) {
            $picked = $d
            break
        }
    }
    Assert-True ($null -ne $picked) "Could not locate new dry-run evidence for $expectedGeneratedName via snapshot diff."
    $newDryRunDirs = @($picked)

    $dryJson = Read-JsonFile -Path (Join-Path $picked "DRY_RUN_RESULT.json")
    Assert-True ($dryJson.overall_status -eq "passed") "Dry-run overall_status must be passed."
    Assert-True ($dryJson.callable_dispatch_present -eq $false) "callable_dispatch_present must be false."
    Assert-True ($dryJson.candidate_code_executed -eq $false) "candidate_code_executed must be false."
    Assert-True ($dryJson.sandbox_worker_invoked -eq $false) "sandbox_worker_invoked must be false."
    Assert-True ($dryJson.tools_executed -eq $false) "tools_executed must be false."
    Assert-True ($dryJson.execution_allowed -eq $false) "execution_allowed must be false."
    Assert-True ($dryJson.real_service_calls -eq $false) "real_service_calls must be false."
    Assert-True ($dryJson.dry_run_only -eq $true) "dry_run_only must be true."

    $toolsPyAfter = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8
    Assert-True ($toolsPyAfter -eq $toolsPyBefore) "tools.py must be unchanged (no dispatch wiring)."
    Assert-True ($toolsPyAfter -notmatch [regex]::Escape($expectedGeneratedName)) "tools.py must not mention generated tool name."

    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore

    Write-Host "OK: Navidrome read-only generated-tool lifecycle example (offline) passed."
} finally {
    try {
        [System.IO.File]::WriteAllBytes($genRegPath, $genBackupBytes)
    } catch {
        Write-Warning "Failed to restore generated_installed_tools.json: $_"
    }
    foreach ($d in $newDryRunDirs) {
        if ($d -and (Test-Path -LiteralPath $d)) {
            Remove-Item -LiteralPath $d -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    if ($buildRoot -and (Test-Path -LiteralPath $buildRoot)) {
        Remove-Item -LiteralPath $buildRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($labSource -and (Test-Path -LiteralPath $labSource)) {
        Remove-Item -LiteralPath $labSource -Recurse -Force -ErrorAction SilentlyContinue
    }
}
