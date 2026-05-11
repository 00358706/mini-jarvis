# Automation lab optional local model draft test.

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

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$guardBefore = Get-GuardHashes -RepoRoot $RepoRoot
$requestId = "auto_lab_model_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$outputDir = $null

try {
    $raw = & powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 `
        -Message "Create a tool to list new Navidrome releases" `
        -RequestId $requestId `
        -UseLocalModel `
        -ModelBaseUrl "http://127.0.0.1:1/v1" `
        -ModelName "local-test-model"

    if ($LASTEXITCODE -ne 0) {
        throw "automation_lab_propose.ps1 failed with exit code $LASTEXITCODE"
    }

    $result = ($raw -join "`n") | ConvertFrom-Json
    Assert-True ($result.status -eq "created") "Expected created status."
    Assert-True ($result.request_id -eq $requestId) "Expected request id '$requestId'."
    Assert-True ($result.local_model.enabled -eq $true) "Expected local model mode to be recorded as enabled."
    Assert-True ($result.local_model.validation_state -eq "failed") "Expected unreachable model validation failure."
    Assert-True ($result.authority_boundary.model_called -eq $true) "Expected model_called true when optional model was attempted."
    Assert-True ($result.authority_boundary.tools_executed -eq $false) "Result claims tools were executed."
    Assert-True ($result.authority_boundary.sandbox_worker_invoked -eq $false) "Result claims sandbox worker was invoked."
    Assert-True ($result.authority_boundary.registry_modified -eq $false) "Result claims registry was modified."
    Assert-True ($result.authority_boundary.generated_tool_execution_allowed -eq $false) "Generated tool execution must remain false."

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
        "TOOL_PROPOSAL.md",
        "MODEL_REQUEST.json",
        "MODEL_RESPONSE.json",
        "MODEL_VALIDATION.json",
        "MODEL_DRAFT.md"
    )

    foreach ($artifact in $requiredArtifacts) {
        $path = Join-Path $outputDir $artifact
        Assert-True (Test-Path -LiteralPath $path) "Missing artifact: $artifact"
    }

    $request = Read-JsonFile (Join-Path $outputDir "REQUEST.json")
    $modelRequest = Read-JsonFile (Join-Path $outputDir "MODEL_REQUEST.json")
    $modelResponse = Read-JsonFile (Join-Path $outputDir "MODEL_RESPONSE.json")
    $modelValidation = Read-JsonFile (Join-Path $outputDir "MODEL_VALIDATION.json")
    $modelDraft = Get-Content -Raw -LiteralPath (Join-Path $outputDir "MODEL_DRAFT.md")
    $summary = Get-Content -Raw -LiteralPath (Join-Path $outputDir "REVIEW_SUMMARY.md")

    Assert-True ($request.local_model.enabled -eq $true) "REQUEST.json should record local model enabled."
    Assert-True ($request.local_model.tool_calling_enabled -eq $false) "Model tool calling must remain disabled."
    Assert-True ($request.authority_boundary.model_called -eq $true) "REQUEST.json should record model_called true."
    Assert-True ($modelRequest.tool_calling_enabled -eq $false) "MODEL_REQUEST.json must keep tool_calling_enabled false."
    Assert-True ($modelRequest.generated_tool_execution_allowed -eq $false) "MODEL_REQUEST.json must keep generated tool execution false."
    Assert-True (-not ($modelRequest.request_payload.PSObject.Properties.Name -contains "tools")) "OpenAI-compatible request must not include top-level tools."
    Assert-True (-not ($modelRequest.request_payload.PSObject.Properties.Name -contains "tool_choice")) "OpenAI-compatible request must not include top-level tool_choice."
    Assert-True ($modelResponse.response.ok -eq $false) "Unreachable model should be recorded as failed response."
    Assert-True ($modelValidation.valid -eq $false) "Unreachable model should fail validation."
    Assert-True ($modelValidation.validation_state -eq "failed") "Expected failed validation state."
    Assert-True ($modelValidation.advisory_only -eq $true) "Model validation must remain advisory only."
    Assert-True ($modelDraft -match "No valid model draft is available") "MODEL_DRAFT.md should record fallback draft text."
    Assert-True ($summary -match 'Local model draft: `enabled \(failed\)`') "REVIEW_SUMMARY.md should record failed optional model draft."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $outputDir "EXECUTION_LOG.jsonl"))) "Automation lab must not write execution logs."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $outputDir "PLAN.json"))) "Automation lab must not create executable plan state."

    Assert-NoForbiddenImports -Path (Join-Path $RepoRoot "automation_lab.py")
    Assert-NoForbiddenImports -Path (Join-Path $RepoRoot "local_model_adapter.py")
    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore
    Write-Host "OK: optional local model draft failure is recorded and deterministic artifacts remain proposal-only."
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
