# Automation lab read-only review summary test.

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

function Get-DirectorySnapshot {
    param([string]$Directory)

    $snapshot = @{}
    foreach ($file in Get-ChildItem -LiteralPath $Directory -File | Sort-Object Name) {
        $snapshot[$file.Name] = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
    }
    return $snapshot
}

function Assert-SnapshotUnchanged {
    param(
        [string]$Directory,
        [hashtable]$Before
    )

    $after = Get-DirectorySnapshot -Directory $Directory
    $beforeNames = @($Before.Keys | Sort-Object)
    $afterNames = @($after.Keys | Sort-Object)
    $diff = @(Compare-Object -ReferenceObject $beforeNames -DifferenceObject $afterNames)
    Assert-True ($diff.Count -eq 0) "Review command created, removed, or renamed artifacts."
    foreach ($name in $beforeNames) {
        Assert-True ($after[$name] -eq $Before[$name]) "Review command modified artifact: $name"
    }
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

function Assert-NoForbiddenImports {
    param([string]$Path)

    $source = Get-Content -Raw -LiteralPath $Path
    $forbiddenPatterns = @(
        '(?m)^\s*import\s+registry\b',
        '(?m)^\s*from\s+registry\b',
        '(?m)^\s*import\s+sandbox\b',
        '(?m)^\s*from\s+sandbox\b',
        '(?m)^\s*import\s+tools\b',
        '(?m)^\s*from\s+tools\b',
        '(?m)^\s*import\s+main\b',
        '(?m)^\s*from\s+main\b',
        '(?m)^\s*import\s+local_model_adapter\b',
        '(?m)^\s*from\s+local_model_adapter\b',
        'sandbox\.run\s*\(',
        'run_tool_by_name\s*\(',
        'run_installed_tool\s*\(',
        'urlopen\s*\('
    )
    foreach ($pattern in $forbiddenPatterns) {
        Assert-True (-not ($source -match $pattern)) "Source '$Path' references forbidden review path pattern: $pattern"
    }
}

function Remove-LabOutput {
    param([string]$RepoRoot, [string]$OutputDir)

    if (-not $OutputDir -or -not (Test-Path -LiteralPath $OutputDir)) {
        return
    }
    $automationRoot = Join-Path $RepoRoot "data\automation_lab"
    $resolvedOutput = (Resolve-Path -LiteralPath $OutputDir).Path
    $resolvedRoot = (Resolve-Path -LiteralPath $automationRoot).Path
    if ($resolvedOutput.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $OutputDir -Recurse -Force
    }
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$guardBefore = Get-GuardHashes -RepoRoot $RepoRoot
$requestId = "auto_review_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$outputDir = $null

try {
    $raw = & powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 `
        -Message "Search repo for automation lab review artifacts" `
        -RequestId $requestId `
        -FixturePath ".\fixtures\automation_lab\capabilities.json"

    if ($LASTEXITCODE -ne 0) {
        throw "automation_lab_propose.ps1 failed with exit code $LASTEXITCODE"
    }

    $result = ($raw -join "`n") | ConvertFrom-Json
    $outputDir = [string]$result.output_dir_abs
    $indexPath = Join-Path $outputDir "INDEX.json"
    Assert-True (Test-Path -LiteralPath $indexPath) "Generated run is missing INDEX.json."
    $index = Read-JsonFile $indexPath
    $beforeSnapshot = Get-DirectorySnapshot -Directory $outputDir

    $summaryById = & powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_review.ps1 `
        -RequestId $requestId
    if ($LASTEXITCODE -ne 0) {
        throw "automation_lab_review.ps1 -RequestId failed with exit code $LASTEXITCODE"
    }
    $summaryText = $summaryById -join "`n"

    Assert-True ($summaryText -match "Automation Lab Review Summary") "Review summary header missing."
    Assert-True ($summaryText -match [regex]::Escape("Review source: $indexPath")) "Review summary should show INDEX.json source."
    Assert-True ($summaryText -match "request_id:\s*$requestId") "Review summary missing request id."
    Assert-True ($summaryText -match "proposal_kind:\s*$($index.proposal_kind)") "Review summary missing proposal kind."
    Assert-True ($summaryText -match "primary_capability_outcome:\s*$($index.primary_capability_outcome)") "Review summary missing primary outcome."
    Assert-True ($summaryText -match "fixture_lookup:\s*enabled=true") "Review summary should report fixture lookup enabled."
    Assert-True ($summaryText -match "source=static_fixture_lookup:") "Review summary should report fixture lookup source."
    Assert-True ($summaryText -match "Artifacts \($(@($index.artifacts).Count)\):") "Review summary should report artifact count."
    Assert-True ($summaryText -match "authority=false") "Review summary should report authority=false artifacts."
    Assert-True ($summaryText -match "Recommended review order:") "Review summary should include recommended review order."
    Assert-True ($summaryText -match "tools_executed:\s*false") "Review summary should report tools_executed false."
    Assert-True ($summaryText -match "sandbox_worker_invoked:\s*false") "Review summary should report sandbox_worker_invoked false."
    Assert-True ($summaryText -match "registry_modified:\s*false") "Review summary should report registry_modified false."
    Assert-True ($summaryText -match "all_artifacts_authority_false:\s*true") "Review summary should report all artifacts as non-authority."
    Assert-SnapshotUnchanged -Directory $outputDir -Before $beforeSnapshot

    $summaryByPath = & powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_review.ps1 `
        -Path $indexPath
    if ($LASTEXITCODE -ne 0) {
        throw "automation_lab_review.ps1 -Path failed with exit code $LASTEXITCODE"
    }
    Assert-True (($summaryByPath -join "`n") -match "request_id:\s*$requestId") "Path-based review summary missing request id."
    Assert-SnapshotUnchanged -Directory $outputDir -Before $beforeSnapshot

    $missingPath = Join-Path $RepoRoot "data\automation_lab\missing_review_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $missingOutput = & powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_review.ps1 `
            -Path $missingPath 2>&1
        $missingExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    Assert-True ($missingExitCode -ne 0) "Missing path should fail safely."
    Assert-True (($missingOutput -join "`n") -match "INDEX\.json not found") "Missing path failure should mention INDEX.json."
    Assert-True (-not (Test-Path -LiteralPath $missingPath)) "Review command should not create missing run path."
    Assert-SnapshotUnchanged -Directory $outputDir -Before $beforeSnapshot

    Assert-NoForbiddenImports -Path (Join-Path $RepoRoot "automation_lab_review.py")
    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore
    Write-Host "OK: automation lab review summary CLI is read-only and index-based."
} finally {
    if ($outputDir) {
        Remove-LabOutput -RepoRoot $RepoRoot -OutputDir $outputDir
    }
}
