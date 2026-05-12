# Automation lab review artifact index test.

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
        'sandbox\.run\s*\(',
        'run_tool_by_name\s*\(',
        'run_installed_tool\s*\('
    )
    foreach ($pattern in $forbiddenPatterns) {
        Assert-True (-not ($source -match $pattern)) "Source '$Path' references forbidden execution path pattern: $pattern"
    }
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

function Assert-IndexMatchesOutput {
    param(
        [string]$OutputDir,
        [bool]$ExpectModelArtifacts,
        [bool]$ExpectFixtureLookup
    )

    $indexPath = Join-Path $OutputDir "INDEX.json"
    Assert-True (Test-Path -LiteralPath $indexPath) "Missing INDEX.json."
    $index = Read-JsonFile $indexPath

    Assert-True ($index.schema_version -eq "automation-lab-review-artifact-index.v1") "Unexpected INDEX.json schema version."
    Assert-True ($index.authority -eq $false) "INDEX.json must not claim authority."
    Assert-True ($index.authority_boundary.proposal_only -eq $true) "INDEX.json boundary is not proposal-only."
    Assert-True ($index.authority_boundary.tools_executed -eq $false) "INDEX.json claims tools executed."
    Assert-True ($index.authority_boundary.sandbox_worker_invoked -eq $false) "INDEX.json claims sandbox worker invoked."
    Assert-True ($index.authority_boundary.registry_modified -eq $false) "INDEX.json claims registry modified."
    Assert-True ($index.authority_boundary.generated_tool_execution_allowed -eq $false) "INDEX.json claims generated tool execution allowed."

    Assert-True ($null -ne $index.registry_capability_lookup) "INDEX.json must include registry_capability_lookup summary."
    Assert-True ($index.registry_capability_lookup.enabled -eq $true) "Registry capability lookup must be enabled for lab runs."
    Assert-True ($index.registry_capability_lookup.registry_read -eq $true) "Registry read must be recorded as true."
    Assert-True ($null -ne $index.registry_capability_lookup.tools_inspected_count) "tools_inspected_count should be present."
    Assert-True ([int]$index.registry_capability_lookup.tools_inspected_count -gt 0) "tools_inspected_count should be positive."
    Assert-True ($null -ne $index.registry_capability_lookup.conflicts_count) "INDEX.json should surface capability scoring conflicts_count."

    $actualFiles = @(Get-ChildItem -LiteralPath $OutputDir -File | Select-Object -ExpandProperty Name | Sort-Object)
    $listedFiles = @($index.artifacts | ForEach-Object { [string]$_.filename } | Sort-Object)
    $diff = @(Compare-Object -ReferenceObject $actualFiles -DifferenceObject $listedFiles)
    Assert-True ($diff.Count -eq 0) "INDEX.json artifact list does not match files written in '$OutputDir'."

    foreach ($entry in @($index.artifacts)) {
        Assert-True ($entry.filename -and $entry.kind -and $entry.format) "Artifact entry is missing filename/kind/format."
        Assert-True (($entry.format -eq "json") -or ($entry.format -eq "markdown")) "Artifact '$($entry.filename)' has invalid format '$($entry.format)'."
        Assert-True (($entry.required -eq $true) -or ($entry.required -eq $false)) "Artifact '$($entry.filename)' has invalid required flag."
        Assert-True ($entry.authority -eq $false) "Artifact '$($entry.filename)' must have authority=false."
    }

    foreach ($required in @("REQUEST.json", "CLASSIFICATION.json", "CAPABILITY_MATCHES.json", "REVIEW_SUMMARY.md", "INDEX.json")) {
        $entry = @($index.artifacts | Where-Object { $_.filename -eq $required })[0]
        Assert-True ($null -ne $entry) "INDEX.json is missing required artifact entry '$required'."
        Assert-True ($entry.required -eq $true) "Required artifact '$required' should be marked required=true."
    }

    foreach ($modelArtifact in @("MODEL_REQUEST.json", "MODEL_RESPONSE.json", "MODEL_VALIDATION.json", "MODEL_DRAFT.md")) {
        $hasModelArtifact = $listedFiles -contains $modelArtifact
        Assert-True ($hasModelArtifact -eq $ExpectModelArtifacts) "Unexpected INDEX.json model artifact presence for '$modelArtifact'."
        if ($hasModelArtifact) {
            $entry = @($index.artifacts | Where-Object { $_.filename -eq $modelArtifact })[0]
            Assert-True ($entry.required -eq $false) "Optional model artifact '$modelArtifact' should be required=false."
        }
    }

    Assert-True ($index.local_model.enabled -eq $ExpectModelArtifacts) "INDEX.json local_model.enabled mismatch."
    if ($ExpectModelArtifacts) {
        Assert-True ($index.local_model.validation_state -eq "failed") "Unreachable local model should be indexed as failed."
    } else {
        Assert-True ($index.local_model.validation_state -eq "not_requested") "Default run should index local model as not_requested."
    }

    Assert-True ($index.fixture_lookup.enabled -eq $ExpectFixtureLookup) "INDEX.json fixture lookup enabled mismatch."
    if ($ExpectFixtureLookup) {
        $src = [string]$index.fixture_lookup.source
        Assert-True (
            ($src -like "*fixture:*") -or ($src -like "static_fixture_lookup:*")
        ) "INDEX.json fixture lookup source should record static fixture selection (got: '$src')."
        Assert-True ($index.fixture_lookup.advisory_only -eq $true) "INDEX.json fixture lookup must be advisory."
    } else {
        Assert-True ($null -eq $index.fixture_lookup.source) "INDEX.json fixture lookup source should be null when disabled."
    }
}

function Invoke-IndexedRun {
    param(
        [string]$CaseName,
        [string]$Message,
        [switch]$UseLocalModel,
        [string]$FixturePath
    )

    $requestId = "auto_index_$($CaseName)_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
    $args = @(
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        ".\scripts\automation_lab_propose.ps1",
        "-Message",
        $Message,
        "-RequestId",
        $requestId
    )

    if ($UseLocalModel) {
        $args += @(
            "-UseLocalModel",
            "-ModelBaseUrl",
            "http://127.0.0.1:1/v1",
            "-ModelName",
            "local-test-model"
        )
    }

    if ($FixturePath -and $FixturePath.Trim()) {
        $args += @("-FixturePath", $FixturePath.Trim())
    }

    $raw = & powershell @args
    if ($LASTEXITCODE -ne 0) {
        throw "automation_lab_propose.ps1 failed with exit code $LASTEXITCODE for case '$CaseName'"
    }

    $result = ($raw -join "`n") | ConvertFrom-Json
    Assert-True ($result.status -eq "created") "Expected created status for case '$CaseName'."
    Assert-True ($result.request_id -eq $requestId) "Unexpected request id for case '$CaseName'."
    Assert-True ($result.artifacts -contains "INDEX.json") "CLI artifact list should include INDEX.json for case '$CaseName'."
    Assert-True ($result.authority_boundary.tools_executed -eq $false) "Result claims tools executed for case '$CaseName'."
    Assert-True ($result.authority_boundary.sandbox_worker_invoked -eq $false) "Result claims sandbox worker invoked for case '$CaseName'."
    Assert-True ($result.authority_boundary.registry_modified -eq $false) "Result claims registry modified for case '$CaseName'."
    return [string]$result.output_dir_abs
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
$outputDirs = @()

try {
    $defaultDir = Invoke-IndexedRun `
        -CaseName "default" `
        -Message "Create a tool to list new Navidrome releases"
    $outputDirs += $defaultDir
    Assert-IndexMatchesOutput -OutputDir $defaultDir -ExpectModelArtifacts:$false -ExpectFixtureLookup:$false

    $modelDir = Invoke-IndexedRun `
        -CaseName "model" `
        -Message "Create a tool to list new Navidrome releases" `
        -UseLocalModel
    $outputDirs += $modelDir
    Assert-IndexMatchesOutput -OutputDir $modelDir -ExpectModelArtifacts:$true -ExpectFixtureLookup:$false

    $fixtureDir = Invoke-IndexedRun `
        -CaseName "fixture" `
        -Message "Search repo for automation lab review artifacts" `
        -FixturePath ".\fixtures\automation_lab\capabilities.json"
    $outputDirs += $fixtureDir
    Assert-IndexMatchesOutput -OutputDir $fixtureDir -ExpectModelArtifacts:$false -ExpectFixtureLookup:$true

    Assert-NoForbiddenImports -Path (Join-Path $RepoRoot "automation_lab.py")
    Assert-NoForbiddenImports -Path (Join-Path $RepoRoot "local_model_adapter.py")
    Assert-RegistryReaderImportsReadOnly -Path (Join-Path $RepoRoot "automation_lab_registry_read.py")
    Assert-ScoringModuleSafe -Path (Join-Path $RepoRoot "automation_lab_capability_scoring.py")
    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore
    Write-Host "OK: automation lab INDEX.json records review artifacts without authority."
} finally {
    foreach ($dir in $outputDirs) {
        Remove-LabOutput -RepoRoot $RepoRoot -OutputDir $dir
    }
}
