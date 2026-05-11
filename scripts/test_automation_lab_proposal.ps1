# Automation lab proposal-only spike test.

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

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$guardBefore = Get-GuardHashes -RepoRoot $RepoRoot
$requestId = "auto_lab_test_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$outputDir = $null

try {
    $raw = & powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 `
        -Message "Create a tool to list new Navidrome releases" `
        -RequestId $requestId

    if ($LASTEXITCODE -ne 0) {
        throw "automation_lab_propose.ps1 failed with exit code $LASTEXITCODE"
    }

    $result = ($raw -join "`n") | ConvertFrom-Json
    Assert-True ($result.status -eq "created") "Expected created status."
    Assert-True ($result.request_id -eq $requestId) "Expected request id '$requestId'."
    Assert-True ($result.proposal_kind -eq "tool_proposal") "Expected tool_proposal classification."
    Assert-True ($result.authority_boundary.tools_executed -eq $false) "Result claims tools were executed."
    Assert-True ($result.authority_boundary.sandbox_worker_invoked -eq $false) "Result claims sandbox worker was invoked."
    Assert-True ($result.authority_boundary.registry_modified -eq $false) "Result claims registry was modified."
    Assert-True ($result.authority_boundary.model_called -eq $false) "Local model should be disabled by default."

    $outputDir = [string]$result.output_dir_abs
    $automationRoot = Join-Path $RepoRoot "data\automation_lab"
    $resolvedOutput = (Resolve-Path -LiteralPath $outputDir).Path
    $resolvedRoot = (Resolve-Path -LiteralPath $automationRoot).Path
    Assert-True ($resolvedOutput.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) "Output dir is outside data/automation_lab."

    $requiredArtifacts = @(
        "REQUEST.json",
        "CLASSIFICATION.json",
        "CAPABILITY_MATCHES.json",
        "REVIEW_SUMMARY.md",
        "TOOL_PROPOSAL.md"
    )

    foreach ($artifact in $requiredArtifacts) {
        $path = Join-Path $outputDir $artifact
        Assert-True (Test-Path -LiteralPath $path) "Missing artifact: $artifact"
    }

    $request = Read-JsonFile (Join-Path $outputDir "REQUEST.json")
    $classification = Read-JsonFile (Join-Path $outputDir "CLASSIFICATION.json")
    $capabilities = Read-JsonFile (Join-Path $outputDir "CAPABILITY_MATCHES.json")
    $summaryText = Get-Content -Raw -LiteralPath (Join-Path $outputDir "REVIEW_SUMMARY.md")
    $toolProposalText = Get-Content -Raw -LiteralPath (Join-Path $outputDir "TOOL_PROPOSAL.md")

    Assert-True ($request.authority_boundary.proposal_only -eq $true) "REQUEST.json is not proposal-only."
    Assert-True ($request.local_model.enabled -eq $false) "REQUEST.json should record local model disabled by default."
    Assert-True ($request.authority_boundary.model_called -eq $false) "REQUEST.json should record model_called false by default."
    Assert-True ($request.authority_boundary.plans_approved -eq $false) "REQUEST.json claims plans approved."
    Assert-True ($request.authority_boundary.plans_authorized -eq $false) "REQUEST.json claims plans authorized."
    Assert-True ($classification.authority_boundary.tools_executed -eq $false) "CLASSIFICATION.json claims tools executed."
    Assert-True ($classification.authority_boundary.sandbox_worker_invoked -eq $false) "CLASSIFICATION.json claims sandbox worker invoked."
    Assert-True ($capabilities.authority_boundary.registry_modified -eq $false) "CAPABILITY_MATCHES.json claims registry modified."

    Assert-True ($capabilities.missing_capability_behavior.generated_tool_execution_allowed -eq $false) "generated_tool_execution_allowed must be false."
    Assert-True ($toolProposalText -match 'generated_tool_execution_allowed:\s*false') "TOOL_PROPOSAL.md must state generated_tool_execution_allowed: false."
    Assert-True ($summaryText -match 'Tools executed:\s*false') "REVIEW_SUMMARY.md must state tools executed: false."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $outputDir "EXECUTION_LOG.jsonl"))) "Automation lab must not write execution logs."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $outputDir "PLAN.json"))) "Automation lab must not create executable plan state."
    foreach ($modelArtifact in @("MODEL_REQUEST.json", "MODEL_RESPONSE.json", "MODEL_VALIDATION.json", "MODEL_DRAFT.md")) {
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $outputDir $modelArtifact))) "Model artifact '$modelArtifact' should not be written unless local model mode is enabled."
    }

    $allowedOutcomes = Get-AllowedCapabilityOutcomes -RepoRoot $RepoRoot
    $observedOutcomes = @($capabilities.primary_outcome)
    foreach ($entry in @($capabilities.outcomes_considered)) {
        $observedOutcomes += [string]$entry.outcome
    }
    foreach ($outcome in $observedOutcomes) {
        Assert-True ($allowedOutcomes.Contains($outcome)) "Capability outcome '$outcome' is not allowed by docs/CAPABILITY_REGISTRY_SCHEMA.md."
    }

    $generatorSource = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "automation_lab.py")
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
        Assert-True (-not ($generatorSource -match $pattern)) "Generator source references forbidden execution path pattern: $pattern"
    }

    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore
    Write-Host "OK: automation lab proposal artifacts are proposal-only and boundary checks passed."
} finally {
    if ($outputDir -and (Test-Path -LiteralPath $outputDir)) {
        $automationRoot = Join-Path $RepoRoot "data\automation_lab"
        $resolvedOutput = (Resolve-Path -LiteralPath $outputDir).Path
        $resolvedRoot = (Resolve-Path -LiteralPath $automationRoot).Path
        if ($resolvedOutput.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $outputDir -Recurse -Force
        }
    }
}
