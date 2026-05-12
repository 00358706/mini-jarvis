# Deterministic capability scoring and conflict reporting for Automation Lab.

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
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Remove-LabOutput {
    param([string]$RepoRoot, [string]$OutputDir)
    if (-not $OutputDir -or -not (Test-Path -LiteralPath $OutputDir)) { return }
    $automationRoot = Join-Path $RepoRoot "data\automation_lab"
    $resolvedOutput = (Resolve-Path -LiteralPath $OutputDir).Path
    $resolvedRoot = (Resolve-Path -LiteralPath $automationRoot).Path
    if ($resolvedOutput.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $OutputDir -Recurse -Force
    }
}

function Get-GuardHashes {
    param([string]$RepoRoot)
    $guarded = @("registry.py", "tools.py", "sandbox.py", "sandbox_worker.py", "main.py", "ingestion.py")
    $hashes = @{}
    foreach ($rel in $guarded) {
        $path = Join-Path $RepoRoot $rel
        $hashes[$rel] = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash
    }
    return $hashes
}

function Assert-GuardHashesUnchanged {
    param([string]$RepoRoot, [hashtable]$Before)
    foreach ($rel in $Before.Keys) {
        $path = Join-Path $RepoRoot $rel
        $after = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash
        Assert-True ($after -eq $Before[$rel]) "Guarded runtime file changed unexpectedly: $rel"
    }
}

function Assert-ScoringModuleSafe {
    param([string]$Path)
    $source = Get-Content -Raw -LiteralPath $Path
    foreach ($pattern in @(
        '(?m)^\s*import\s+registry\b',
        '(?m)^\s*from\s+registry\b',
        'registry\.(propose|approve|install|reject)\s*\(',
        'sandbox\.run\s*\('
    )) {
        Assert-True (-not ($source -match $pattern)) "Scoring module must stay registry/sandbox-free: $pattern"
    }
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$guardBefore = Get-GuardHashes -RepoRoot $RepoRoot
$msg = "Search Radarr for a movie titled test"
$d1 = $null
$d2 = $null

try {
    $r1 = & powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 `
        -Message $msg `
        -RequestId "auto_score_a_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
    if ($LASTEXITCODE -ne 0) { throw "propose 1 failed" }
    $r2 = & powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 `
        -Message $msg `
        -RequestId "auto_score_b_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
    if ($LASTEXITCODE -ne 0) { throw "propose 2 failed" }

    $d1 = [string](($r1 -join "`n") | ConvertFrom-Json).output_dir_abs
    $d2 = [string](($r2 -join "`n") | ConvertFrom-Json).output_dir_abs

    $c1 = Read-JsonFile (Join-Path $d1 "CAPABILITY_MATCHES.json")
    $c2 = Read-JsonFile (Join-Path $d2 "CAPABILITY_MATCHES.json")

    $j1 = ($c1.score_breakdown | ConvertTo-Json -Compress -Depth 10)
    $j2 = ($c2.score_breakdown | ConvertTo-Json -Compress -Depth 10)
    Assert-True ($j1 -eq $j2) "score_breakdown must be identical for identical messages (deterministic)."
    Assert-True ($c1.primary_outcome -eq $c2.primary_outcome) "primary_outcome must be deterministic for identical input."
    Assert-True ($c1.score -eq $c2.score) "Advisory score must match for identical input."
    Assert-True ($c1.schema_version -eq "automation-lab-capability-matches.v3") "Expected v3 schema."

    Assert-ScoringModuleSafe -Path (Join-Path $RepoRoot "automation_lab_capability_scoring.py")
    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore
    Write-Host "OK: capability scoring is deterministic and scoring module stays read-only safe."
} finally {
    Remove-LabOutput -RepoRoot $RepoRoot -OutputDir $d1
    Remove-LabOutput -RepoRoot $RepoRoot -OutputDir $d2
}
