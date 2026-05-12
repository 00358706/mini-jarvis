# Proposal-only: agent-style missing-capability request enters Automation Lab tool-proposal lane (review artifacts only).
# Does not install, execute, sandbox, mutate registry, create tool builds, or add dispatch.

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

function Get-DryRunDirSnapshot {
    param([string]$DryRoot)

    if (-not (Test-Path -LiteralPath $DryRoot)) {
        return @()
    }
    return @(Get-ChildItem -LiteralPath $DryRoot -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { $_.FullName })
}

function Compare-NewDirs {
    param(
        [string[]]$Before,
        [string[]]$After
    )

    $bSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($x in $Before) { [void]$bSet.Add($x) }
    return @($After | Where-Object { -not $bSet.Contains($_) })
}

function Assert-ReadOnlyNavidromeBoundaries {
    param(
        [string]$Label,
        [string]$Text
    )

    if ([string]::IsNullOrWhiteSpace($Text)) {
        throw "$Label is empty."
    }
    Assert-True ($Text -match '(?i)navidrome_recently_added_albums') "$Label must include requested capability id text."
    Assert-True ($Text -match '(?i)media_agent') "$Label must reference media_agent."
    Assert-True ($Text -match '(?i)read[- ]only') "$Label must document read-only scope."
    Assert-True ($Text -match '(?i)no\s+playlist') "$Label must state no playlist edits."
    Assert-True ($Text -match '(?i)no\s+downloads') "$Label must state no downloads."
    Assert-True ($Text -match '(?i)no\s+deletes') "$Label must state no deletes."
    Assert-True ($Text -match '(?i)no\s+playback') "$Label must state no playback control."
    Assert-True ($Text -match '(?i)no\s+real\s+service') "$Label must state no real service calls."
    Assert-True ($Text -match '(?i)proposal\s+only') "$Label must state proposal only."
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$requestId = "agent_tp_flow_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
Assert-True ($requestId -cmatch '^[A-Za-z0-9_-]{8,80}$') "requestId must match automation lab id pattern."

$message = @"
media_agent needs a read-only tool to list recently added Navidrome albums.

Requested capability id (authoring label): navidrome_recently_added_albums.

Boundaries: read-only; no playlist edits; no downloads; no deletes; no playback control; no real service calls in this proposal lane. Proposal only — review evidence, not install or execution.
"@.Trim()

$labRoot = Join-Path $RepoRoot "data\automation_lab"
$runDir = Join-Path $labRoot $requestId
$buildRoot = Join-Path (Join-Path $RepoRoot "data\tool_builds") $requestId
$genRegPath = Join-Path $RepoRoot "data\registry\generated_installed_tools.json"
$dryRunsRoot = Join-Path $RepoRoot "data\generated_tool_dry_runs"
$proposePs1 = Join-Path $RepoRoot "scripts\automation_lab_propose.ps1"

$registryBytesBackup = [System.IO.File]::ReadAllBytes($genRegPath)
$registryHashBefore = (Get-FileHash -LiteralPath $genRegPath -Algorithm SHA256).Hash
$drySnapBefore = Get-DryRunDirSnapshot -DryRoot $dryRunsRoot
$toolsPyBefore = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8
$guardBefore = Get-GuardHashes -RepoRoot $RepoRoot

Assert-True (-not (Test-Path -LiteralPath $buildRoot)) "Precondition: no tool build workspace for this id."

try {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $psiArgs = @(
            '-ExecutionPolicy', 'Bypass',
            '-File', $proposePs1,
            '-RequestId', $requestId,
            '-Message', $message
        )
        $out = & powershell.exe @psiArgs 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }

    Assert-True ($code -eq 0) "automation_lab_propose.ps1 failed (exit $code). Output: $out"
    Assert-True (Test-Path -LiteralPath $runDir) "Automation Lab run directory missing."

    $index = Read-JsonFile -Path (Join-Path $runDir "INDEX.json")
    Assert-True ($index.schema_version -eq "automation-lab-review-artifact-index.v1") "INDEX.json schema_version."
    Assert-True ($index.authority -eq $false) "INDEX.json authority must be false."
    Assert-True ($index.proposal_kind -eq "tool_proposal") "INDEX.json proposal_kind must be tool_proposal."
    Assert-True ($null -ne $index.authority_boundary) "INDEX.json must include authority_boundary."
    Assert-True ($index.authority_boundary.proposal_only -eq $true) "INDEX proposal_only must be true."
    Assert-True ($index.authority_boundary.tools_executed -eq $false) "INDEX tools_executed must be false."
    Assert-True ($index.authority_boundary.registry_modified -eq $false) "INDEX registry_modified must be false."
    Assert-True ($index.authority_boundary.sandbox_worker_invoked -eq $false) "INDEX sandbox_worker_invoked must be false."

    $cap = Read-JsonFile -Path (Join-Path $runDir "CAPABILITY_MATCHES.json")
    Assert-True ($cap.schema_version -eq "automation-lab-capability-matches.v3") "CAPABILITY_MATCHES.json must be v3."

    $capIds = @($cap.capability_ids | ForEach-Object { [string]$_ })
    Assert-True ($capIds.Count -ge 1) "CAPABILITY_MATCHES must include capability_ids."
    $navMatch = $false
    foreach ($cid in $capIds) {
        if ($cid -match '(?i)navidrome') {
            $navMatch = $true
            break
        }
    }
    Assert-True $navMatch "CAPABILITY_MATCHES capability_ids must include Navidrome-related evidence."

    $toolProposalPath = Join-Path $runDir "TOOL_PROPOSAL.md"
    Assert-True (Test-Path -LiteralPath $toolProposalPath) "TOOL_PROPOSAL.md must exist for tool_proposal lane."

    $req = Read-JsonFile -Path (Join-Path $runDir "REQUEST.json")
    $proposalText = Get-Content -Raw -LiteralPath $toolProposalPath -Encoding UTF8
    $reqMsg = [string]$req.message
    Assert-ReadOnlyNavidromeBoundaries -Label "REQUEST.json message" -Text $reqMsg
    Assert-ReadOnlyNavidromeBoundaries -Label "TOOL_PROPOSAL.md" -Text $proposalText

    Assert-True (-not (Test-Path -LiteralPath $buildRoot)) "No tool build workspace must be created by propose-only flow."

    $candHits = @(Get-ChildItem -LiteralPath $runDir -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "CANDIDATE_TOOL.py" -or $_.Name -eq "TOOL_SCHEMA.json" })
    Assert-True ($candHits.Count -eq 0) "No candidate implementation files under automation lab run."

    Assert-True (-not (Test-Path -LiteralPath (Join-Path $runDir "INSTALL_MANIFEST.json"))) "No install review manifest in lab run."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $runDir "INSTALL_REVIEW.md"))) "No install review markdown in lab run."

    $drySnapAfter = Get-DryRunDirSnapshot -DryRoot $dryRunsRoot
    $newDry = Compare-NewDirs -Before $drySnapBefore -After $drySnapAfter
    Assert-True ($newDry.Count -eq 0) "No new dry-run evidence directories must be created."

    $registryHashAfter = (Get-FileHash -LiteralPath $genRegPath -Algorithm SHA256).Hash
    Assert-True ($registryHashAfter -eq $registryHashBefore) "data/registry/generated_installed_tools.json must be unchanged."

    $toolsPyAfter = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "tools.py") -Encoding UTF8
    Assert-True ($toolsPyAfter -eq $toolsPyBefore) "tools.py must be unchanged (no generated dispatch)."

    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore

    Write-Host "OK: agent tool proposal flow (Automation Lab proposal lane only) passed."
} finally {
    if ($runDir -and (Test-Path -LiteralPath $runDir)) {
        Remove-Item -LiteralPath $runDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $registryBytesBackup) {
        [System.IO.File]::WriteAllBytes($genRegPath, $registryBytesBackup)
    }
}
