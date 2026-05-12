# Automation lab read-only registry capability lookup test.

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

function Select-Python {
    param([string]$RepoRoot)
    $venvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { return $venvPy }
    return "python"
}

function Get-RegistryToolCount {
    param([string]$Py, [string]$RepoRoot)
    $code = "import sys; sys.path.insert(0, r'''$RepoRoot'''); import automation_lab_registry_read as r; print(r.registry_tool_count_readonly())"
    $n = & $Py -c $code
    if ($LASTEXITCODE -ne 0) { throw "Python registry count failed." }
    return [int]([string]$n).Trim()
}

function Assert-RegistryReaderImportsReadOnly {
    param([string]$Path)
    $source = Get-Content -Raw -LiteralPath $Path
    $forbiddenPatterns = @(
        '(?m)^\s*import\s+sandbox\b',
        '(?m)^\s*from\s+sandbox\b',
        '(?m)^\s*import\s+tools\b',
        '(?m)^\s*from\s+tools\b',
        '(?m)^\s*import\s+main\b',
        '(?m)^\s*from\s+main\b',
        'registry\.(propose|approve|install|reject)\s*\(',
        'sandbox\.run\s*\(',
        'run_tool_by_name\s*\(',
        'run_installed_tool\s*\('
    )
    foreach ($pattern in $forbiddenPatterns) {
        Assert-True (-not ($source -match $pattern)) "Registry reader '$Path' must not reference forbidden pattern: $pattern"
    }
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

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot
$Py = Select-Python -RepoRoot $RepoRoot

$beforeCount = Get-RegistryToolCount -Py $Py -RepoRoot $RepoRoot
$requestId = "auto_reglk_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$outputDir = $null
$fixtureDir = $null
$conflictDir = $null

try {
    $raw = & powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 `
        -Message "Search Radarr for a movie titled test" `
        -RequestId $requestId

    if ($LASTEXITCODE -ne 0) {
        throw "automation_lab_propose.ps1 failed with exit code $LASTEXITCODE"
    }

    $afterCount = Get-RegistryToolCount -Py $Py -RepoRoot $RepoRoot
    Assert-True ($afterCount -eq $beforeCount) "Registry tool count must be unchanged after automation lab (read-only)."

    $result = ($raw -join "`n") | ConvertFrom-Json
    Assert-True ($result.status -eq "created") "Expected created status."
    Assert-True ($result.authority_boundary.tools_executed -eq $false) "Result must remain proposal-only (no tool execution)."
    Assert-True ($result.authority_boundary.sandbox_worker_invoked -eq $false) "Sandbox worker must not be invoked."
    Assert-True ($result.authority_boundary.registry_modified -eq $false) "Registry must not be modified."

    $outputDir = [string]$result.output_dir_abs
    $cap = Read-JsonFile (Join-Path $outputDir "CAPABILITY_MATCHES.json")

    Assert-True ($cap.schema_version -eq "automation-lab-capability-matches.v3") "Expected v3 capability matches schema."
    Assert-True ($cap.registry_lookup.registry_read -eq $true) "CAPABILITY_MATCHES must record registry_read."
    Assert-True ($cap.registry_lookup.registry_modified -eq $false) "CAPABILITY_MATCHES must record registry_modified false."
    Assert-True ($cap.evidence_sources -contains "registry_readonly") "Evidence sources must include registry_readonly."
    Assert-True ($cap.primary_outcome_source -eq "registry_metadata") "Radarr message should prefer registry-informed primary source."
    Assert-True ($cap.source -match "registry_readonly") "Combined source string should mention registry_readonly."
    Assert-True ($null -ne $cap.score) "Advisory score must be present."
    Assert-True ($null -ne $cap.score_breakdown.deterministic_template) "score_breakdown must include deterministic lane."
    Assert-True ($null -ne $cap.recommendation_reason) "recommendation_reason must be present."
    Assert-True ($cap.precedence_applied -eq "registry_only") "Radarr-only run should apply registry_only precedence."

    $radarRows = @($cap.registry_matches | Where-Object { $_.tool_name -and ([string]$_.tool_name).ToLower() -like "*radarr*" })
    Assert-True ($radarRows.Count -ge 1) "Expected at least one radarr-related row in registry_matches."
    $top = $radarRows | Sort-Object { [double]$_.confidence } -Descending | Select-Object -First 1
    Assert-True ($top.status -eq "installed") "Seeded Radarr tools should be installed in registry."
    Assert-True ($null -ne $top.input_schema_summary) "Row should include input_schema_summary for review."
    Assert-True ($null -ne $top.side_effects_inferred) "Row should include side_effects_inferred."
    Assert-True ($null -ne $top.risk_level_inferred) "Row should include risk_level_inferred."

    $fixtureRaw = & powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 `
        -Message "Search repo for automation lab review artifacts" `
        -RequestId "auto_reglk_fix_$([Guid]::NewGuid().ToString('N').Substring(0, 8))" `
        -FixturePath ".\fixtures\automation_lab\capabilities.json"
    if ($LASTEXITCODE -ne 0) { throw "Fixture propose failed." }
    $fixtureResult = ($fixtureRaw -join "`n") | ConvertFrom-Json
    $fixtureDir = [string]$fixtureResult.output_dir_abs
    $fx = Read-JsonFile (Join-Path $fixtureDir "CAPABILITY_MATCHES.json")
    Assert-True ($fx.registry_lookup.registry_read -eq $true) "Fixture run must still perform registry read."
    Assert-True ($fx.primary_outcome -eq "reuse_existing") "Fixture reuse case must keep reuse_existing primary outcome."
    Assert-True (
        ($fx.primary_outcome_source -eq "registry_metadata") -or
        ($fx.primary_outcome_source -eq "static_fixture")
    ) "Fixture run may attribute primary to registry_metadata or static_fixture depending on duplicate-risk precedence."
    Assert-True (
        ($fx.precedence_applied -eq "registry_and_fixture_agree") -or
        ($fx.precedence_applied -eq "fixture_over_registry_duplicate_risk_heuristic")
    ) "Expected agreement or explicit fixture-over-duplicate-risk precedence."
    Assert-True ($null -ne $fx.score) "Scoring score must be present."
    Assert-True ($null -ne $fx.score_breakdown) "score_breakdown must be present."

    $conflictRaw = & powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 `
        -Message "Create a new search_repo helper to grep yaml in the repository" `
        -RequestId "auto_reglk_cf_$([Guid]::NewGuid().ToString('N').Substring(0, 8))" `
        -FixturePath ".\fixtures\automation_lab\capabilities_force_propose_new.json"
    if ($LASTEXITCODE -ne 0) { throw "Conflict fixture propose failed." }
    $conflictResult = ($conflictRaw -join "`n") | ConvertFrom-Json
    $conflictDir = [string]$conflictResult.output_dir_abs
    $cf = Read-JsonFile (Join-Path $conflictDir "CAPABILITY_MATCHES.json")
    Assert-True ($cf.primary_outcome -ne "propose_new") "Strong registry signal must not yield silent fixture propose_new primary."
    Assert-True ($cf.precedence_applied -eq "registry_strong_installed_over_fixture_propose_new") "Expected explicit registry-over-fixture precedence."
    Assert-True (@($cf.conflicts).Count -ge 1) "Conflicts array must surface fixture vs registry disagreement."
    Assert-True ($null -ne $cf.fixture_alternate_recommendation) "Fixture propose_new should be preserved as alternate."
    Assert-True ($cf.fixture_alternate_recommendation.primary_outcome -eq "propose_new") "Alternate must record fixture propose_new."

    Assert-RegistryReaderImportsReadOnly -Path (Join-Path $RepoRoot "automation_lab_registry_read.py")
    Write-Host "OK: automation lab registry capability lookup is read-only and records evidence sources."
} finally {
    Remove-LabOutput -RepoRoot $RepoRoot -OutputDir $outputDir
    if ($fixtureDir) { Remove-LabOutput -RepoRoot $RepoRoot -OutputDir $fixtureDir }
    if ($conflictDir) { Remove-LabOutput -RepoRoot $RepoRoot -OutputDir $conflictDir }
}
