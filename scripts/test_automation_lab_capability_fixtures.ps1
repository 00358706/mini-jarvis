# Automation lab static capability fixture test.

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

function Get-AllowedCapabilityOutcomes {
    param([string]$RepoRoot)

    $docPath = Join-Path $RepoRoot "docs\CAPABILITY_REGISTRY_SCHEMA.md"
    $doc = Get-Content -Raw -LiteralPath $docPath
    $matches = [regex]::Matches($doc, '\*\*`([^`]+)`\*\*')
    $allowed = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($match in $matches) {
        [void]$allowed.Add($match.Groups[1].Value)
    }
    foreach ($required in @("reuse_existing", "extend_existing", "compose_existing", "propose_new", "reject_duplicate")) {
        Assert-True ($allowed.Contains($required)) "Could not find capability outcome '$required' in docs/CAPABILITY_REGISTRY_SCHEMA.md."
    }
    return $allowed
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

function Invoke-FixtureCase {
    param(
        [string]$RepoRoot,
        [string]$FixturePath,
        [string]$CaseName,
        [string]$Message,
        [string]$ExpectedOutcome,
        [string[]]$ExpectedCandidateTools,
        [System.Collections.Generic.HashSet[string]]$AllowedOutcomes
    )

    $requestId = "auto_fixture_$($CaseName)_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
    $raw = & powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 `
        -Message $Message `
        -RequestId $requestId `
        -FixturePath $FixturePath

    if ($LASTEXITCODE -ne 0) {
        throw "automation_lab_propose.ps1 failed with exit code $LASTEXITCODE for case '$CaseName'"
    }

    $result = ($raw -join "`n") | ConvertFrom-Json
    Assert-True ($result.status -eq "created") "Expected created status for case '$CaseName'."
    Assert-True ($result.request_id -eq $requestId) "Unexpected request id for case '$CaseName'."
    Assert-True ($result.authority_boundary.tools_executed -eq $false) "Result claims tools were executed for case '$CaseName'."
    Assert-True ($result.authority_boundary.sandbox_worker_invoked -eq $false) "Result claims sandbox worker was invoked for case '$CaseName'."
    Assert-True ($result.authority_boundary.registry_modified -eq $false) "Result claims registry was modified for case '$CaseName'."
    Assert-True ($result.authority_boundary.generated_tool_execution_allowed -eq $false) "Generated tool execution must remain false for case '$CaseName'."

    $outputDir = [string]$result.output_dir_abs
    $automationRoot = Join-Path $RepoRoot "data\automation_lab"
    $resolvedOutput = (Resolve-Path -LiteralPath $outputDir).Path
    $resolvedRoot = (Resolve-Path -LiteralPath $automationRoot).Path
    Assert-True ($resolvedOutput.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) "Output dir is outside data/automation_lab for case '$CaseName'."

    $request = Read-JsonFile (Join-Path $outputDir "REQUEST.json")
    $capabilities = Read-JsonFile (Join-Path $outputDir "CAPABILITY_MATCHES.json")
    Assert-True ($request.local_model.enabled -eq $false) "Local model should remain disabled by default for case '$CaseName'."
    Assert-True ($capabilities.primary_outcome -eq $ExpectedOutcome) "Expected outcome '$ExpectedOutcome' for case '$CaseName', got '$($capabilities.primary_outcome)'."
    Assert-True ($capabilities.fixture_lookup.enabled -eq $true) "CAPABILITY_MATCHES.json should include fixture lookup for case '$CaseName'."
    Assert-True ($capabilities.fixture_lookup.advisory_only -eq $true) "CAPABILITY_MATCHES fixture lookup must be advisory for case '$CaseName'."
    Assert-True ($capabilities.fixture_lookup.fixture_file_only -eq $true) "Fixture lookup must be file-only for case '$CaseName'."
    Assert-True ($capabilities.fixture_lookup.registry_modified -eq $false) "Fixture path must not modify registry for case '$CaseName'."
    Assert-True ($capabilities.registry_lookup.enabled -eq $true) "CAPABILITY_MATCHES.json should include registry lookup for case '$CaseName'."
    Assert-True ($capabilities.registry_lookup.registry_read -eq $true) "Registry metadata read must be recorded for case '$CaseName'."
    Assert-True ($capabilities.registry_lookup.registry_modified -eq $false) "Registry lookup must not modify registry for case '$CaseName'."
    Assert-True (@($capabilities.registry_matches).Count -gt 0) "registry_matches should list scored tools for case '$CaseName'."
    $installedRow = @($capabilities.registry_matches | Where-Object { $_.status -eq "installed" } | Select-Object -First 1)
    Assert-True ($null -ne $installedRow) "Expected at least one installed tool row in registry_matches for case '$CaseName'."
    Assert-True ($null -ne $installedRow.input_schema_summary) "registry_matches should include input_schema_summary for case '$CaseName'."
    Assert-True ($capabilities.missing_capability_behavior.generated_tool_execution_allowed -eq $false) "generated_tool_execution_allowed must remain false for case '$CaseName'."
    Assert-True ($capabilities.authority_boundary.tools_executed -eq $false) "CAPABILITY_MATCHES claims tools executed for case '$CaseName'."
    Assert-True ($capabilities.authority_boundary.sandbox_worker_invoked -eq $false) "CAPABILITY_MATCHES claims sandbox worker invoked for case '$CaseName'."
    Assert-True ($capabilities.authority_boundary.registry_modified -eq $false) "CAPABILITY_MATCHES claims registry modified for case '$CaseName'."

    foreach ($toolName in $ExpectedCandidateTools) {
        $candidateNames = @($capabilities.candidate_tools | ForEach-Object { $_.tool_name })
        Assert-True ($candidateNames -contains $toolName) "Expected candidate tool '$toolName' for case '$CaseName'."
    }

    $observedOutcomes = @($capabilities.primary_outcome)
    foreach ($entry in @($capabilities.outcomes_considered)) {
        $observedOutcomes += [string]$entry.outcome
    }
    foreach ($outcome in $observedOutcomes) {
        Assert-True ($AllowedOutcomes.Contains($outcome)) "Capability outcome '$outcome' is not allowed by docs/CAPABILITY_REGISTRY_SCHEMA.md."
    }

    Assert-True (-not (Test-Path -LiteralPath (Join-Path $outputDir "EXECUTION_LOG.jsonl"))) "Automation lab must not write execution logs for case '$CaseName'."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $outputDir "PLAN.json"))) "Automation lab must not create executable plan state for case '$CaseName'."
    foreach ($modelArtifact in @("MODEL_REQUEST.json", "MODEL_RESPONSE.json", "MODEL_VALIDATION.json", "MODEL_DRAFT.md")) {
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $outputDir $modelArtifact))) "Model artifact '$modelArtifact' should not be written for fixture-only case '$CaseName'."
    }

    return $outputDir
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

$fixturePath = ".\fixtures\automation_lab\capabilities.json"
$guardBefore = Get-GuardHashes -RepoRoot $RepoRoot
$allowedOutcomes = Get-AllowedCapabilityOutcomes -RepoRoot $RepoRoot
$outputDirs = @()

try {
    $outputDirs += Invoke-FixtureCase `
        -RepoRoot $RepoRoot `
        -FixturePath $fixturePath `
        -CaseName "reuse" `
        -Message "Search repo for automation lab review artifacts" `
        -ExpectedOutcome "reuse_existing" `
        -ExpectedCandidateTools @("search_repo") `
        -AllowedOutcomes $allowedOutcomes

    $outputDirs += Invoke-FixtureCase `
        -RepoRoot $RepoRoot `
        -FixturePath $fixturePath `
        -CaseName "compose" `
        -Message "Review repo and summarize project files" `
        -ExpectedOutcome "compose_existing" `
        -ExpectedCandidateTools @("search_repo", "inspect_file") `
        -AllowedOutcomes $allowedOutcomes

    $outputDirs += Invoke-FixtureCase `
        -RepoRoot $RepoRoot `
        -FixturePath $fixturePath `
        -CaseName "navidrome" `
        -Message "Create a tool to list new Navidrome releases and new albums" `
        -ExpectedOutcome "extend_existing" `
        -ExpectedCandidateTools @("navidrome_recent_albums", "navidrome_list_new_releases") `
        -AllowedOutcomes $allowedOutcomes

    $outputDirs += Invoke-FixtureCase `
        -RepoRoot $RepoRoot `
        -FixturePath $fixturePath `
        -CaseName "unknown" `
        -Message "Create a tool to catalog Martian sprinkler telemetry" `
        -ExpectedOutcome "propose_new" `
        -ExpectedCandidateTools @() `
        -AllowedOutcomes $allowedOutcomes

    Assert-NoForbiddenImports -Path (Join-Path $RepoRoot "automation_lab.py")
    Assert-NoForbiddenImports -Path (Join-Path $RepoRoot "local_model_adapter.py")
    Assert-RegistryReaderImportsReadOnly -Path (Join-Path $RepoRoot "automation_lab_registry_read.py")
    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore
    Write-Host "OK: static capability fixture lookup is advisory and improves CAPABILITY_MATCHES.json only."
} finally {
    foreach ($dir in $outputDirs) {
        Remove-LabOutput -RepoRoot $RepoRoot -OutputDir $dir
    }
}
