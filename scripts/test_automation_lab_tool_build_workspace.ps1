# Tests for review-only tool build workspace creation from Automation Lab artifacts.

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

function Assert-DirHasOnlyReadme {
    param([string]$DirPath, [string]$Label)

    Assert-True (Test-Path -LiteralPath $DirPath) "Expected directory: $Label"
    $files = @(Get-ChildItem -LiteralPath $DirPath -File -Force)
    Assert-True ($files.Count -eq 1) "$Label should contain exactly one file; found $($files.Count)."
    Assert-True ($files[0].Name -eq "README.md") "$Label should only contain README.md."
}

function Invoke-ToolBuildCreator {
    param(
        [string]$CreatorPath,
        [string]$RequestId
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & powershell -ExecutionPolicy Bypass -File $CreatorPath `
            -AutomationLabRequestId $RequestId 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return [pscustomobject]@{
        Code   = $code
        Output = $output
    }
}

function New-MinimalLabSource {
    param(
        [string]$SourceDir,
        [string]$RequestId,
        [bool]$IncludeToolProposal
    )

    New-Item -ItemType Directory -Path $SourceDir -Force | Out-Null

    $indexObj = [ordered]@{
        schema_version                 = "automation-lab-review-artifact-index.v1"
        authority                      = $false
        request_id                     = $RequestId
        proposal_kind                  = "tool_proposal"
        primary_capability_outcome     = "propose_new"
        created_at                     = "2026-05-11T12:00:00Z"
        authority_boundary             = @{
            proposal_only              = $true
            registry_modified          = $false
            tools_executed             = $false
            sandbox_worker_invoked     = $false
            registry_is_execution_truth = $true
        }
    }
    ($indexObj | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath (Join-Path $SourceDir "INDEX.json") -Encoding UTF8

    $capObj = [ordered]@{
        schema_version             = "automation-lab-capability-matches.v3"
        authority                  = $false
        request_id                 = $RequestId
        capability_ids             = @("fixture.capability.example")
        primary_outcome            = "propose_new"
        primary_outcome_source     = "deterministic_template"
        evidence_sources           = @("deterministic_template", "registry_readonly")
        score                      = 72
        precedence_applied         = "fixture_test_lane_merge"
        conflicts                  = @()
        authority_boundary         = @{
            proposal_only          = $true
            registry_modified      = $false
        }
    }
    ($capObj | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath (Join-Path $SourceDir "CAPABILITY_MATCHES.json") -Encoding UTF8

    if ($IncludeToolProposal) {
        $proposal = @"
# Fixture tool proposal

generated_tool_execution_allowed: false

This is minimal test content only.
"@
        Set-Content -LiteralPath (Join-Path $SourceDir "TOOL_PROPOSAL.md") -Value $proposal.TrimEnd() -Encoding UTF8
    }
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$guardBefore = Get-GuardHashes -RepoRoot $RepoRoot

$creatorPath = Join-Path $RepoRoot "scripts\automation_lab_create_tool_build.ps1"
$creatorSrc = Get-Content -Raw -LiteralPath $creatorPath
Assert-True ($creatorSrc -notmatch '(?i)\bpython(\.exe)?\b') "Tool build script must not invoke Python."
Assert-True ($creatorSrc -notmatch '(?i)automation_lab\.py') "Tool build script must not invoke automation_lab.py."
Assert-True ($creatorSrc -notmatch '(?i)import\s+registry') "Tool build script must not import registry."
Assert-True ($creatorSrc -notmatch '(?i)from\s+sandbox\b') "Tool build script must not import sandbox module."
Assert-True ($creatorSrc -notmatch '(?i)import\s+sandbox\b') "Tool build script must not import sandbox module."
Assert-True ($creatorSrc -match '\^\[A-Za-z0-9_-\]\{8,80\}\$') "Tool build script must validate safe Automation Lab request ids."

$labRoot = Join-Path $RepoRoot "data\automation_lab"
$buildsRoot = Join-Path $RepoRoot "data\tool_builds"
if (-not (Test-Path -LiteralPath $labRoot)) {
    New-Item -ItemType Directory -Path $labRoot -Force | Out-Null
}
if (-not (Test-Path -LiteralPath $buildsRoot)) {
    New-Item -ItemType Directory -Path $buildsRoot -Force | Out-Null
}

$positiveId = "tb_ws_pos_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
$negativeId = "tb_ws_neg_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
$positiveSource = Join-Path $labRoot $positiveId
$negativeSource = Join-Path $labRoot $negativeId
$positiveBuild = Join-Path $buildsRoot $positiveId
$negBuild = $null
$outsideSentinelDir = Join-Path (Join-Path $RepoRoot "data") "tb_ws_sentinel"
$outsideSentinelFile = Join-Path $outsideSentinelDir "keep.txt"
$outsideTraversalCandidate = Join-Path (Join-Path $RepoRoot "data") "tb_ws_evil"

try {
    # --- Positive path ---
    New-MinimalLabSource -SourceDir $positiveSource -RequestId $positiveId -IncludeToolProposal $true

    $proc = Invoke-ToolBuildCreator -CreatorPath $creatorPath -RequestId $positiveId
    Assert-True ($proc.Code -eq 0) "automation_lab_create_tool_build.ps1 should exit 0 (got $($proc.Code)). Output: $($proc.Output)"

    Assert-True (Test-Path -LiteralPath $positiveBuild) "Build workspace directory should exist."
    $idxPath = Join-Path $positiveBuild "BUILD_INDEX.json"
    Assert-True (Test-Path -LiteralPath $idxPath) "BUILD_INDEX.json missing."

    $bi = Read-JsonFile -Path $idxPath
    Assert-True ($bi.schema_version -eq "tool-build-index.v1") "schema_version"
    Assert-True ($bi.build_id -eq $positiveId) "build_id"
    Assert-True ($bi.source_request_id -eq $positiveId) "source_request_id"
    Assert-True ($bi.source_automation_lab_dir -eq "data/automation_lab/$positiveId") "source_automation_lab_dir"
    Assert-True ($bi.source_tool_proposal -eq "source_automation_lab/TOOL_PROPOSAL.md") "source_tool_proposal"
    Assert-True ($null -ne $bi.created_at) "created_at"
    Assert-True ($bi.proposal_kind -eq "tool_proposal") "proposal_kind"
    Assert-True (@($bi.capability_ids).Count -eq 1) "capability_ids"
    Assert-True ($bi.capability_ids[0] -eq "fixture.capability.example") "capability id value"
    Assert-True ($bi.primary_capability_outcome -eq "propose_new") "primary_capability_outcome"
    Assert-True ($bi.primary_outcome_source -eq "deterministic_template") "primary_outcome_source"
    Assert-True ($bi.evidence_sources -contains "deterministic_template") "evidence_sources"
    Assert-True ($bi.score -eq 72) "score"
    Assert-True ($bi.precedence_applied -eq "fixture_test_lane_merge") "precedence_applied"
    Assert-True ($bi.conflicts_count -eq 0) "conflicts_count"
    Assert-True ($bi.authority -eq $false) "authority"
    Assert-True ($bi.review_evidence_only -eq $true) "review_evidence_only"
    Assert-True ($bi.generated_code_present -eq $false) "generated_code_present"
    Assert-True ($bi.install_allowed -eq $false) "install_allowed"
    Assert-True ($bi.execution_allowed -eq $false) "execution_allowed"
    Assert-True ($bi.registry_modified -eq $false) "registry_modified"
    Assert-True ($bi.tools_executed -eq $false) "tools_executed"
    Assert-True ($bi.sandbox_worker_invoked -eq $false) "sandbox_worker_invoked"
    Assert-True ($bi.automatic_registry_installation_allowed -eq $false) "automatic_registry_installation_allowed"
    Assert-True (@($bi.artifacts_copied).Count -ge 3) "artifacts_copied should list at least required copies."
    Assert-True (@($bi.artifacts_copied) -contains "source_automation_lab/TOOL_PROPOSAL.md") "artifacts_copied should include TOOL_PROPOSAL.md."

    $copiedProposal = Join-Path $positiveBuild "source_automation_lab\TOOL_PROPOSAL.md"
    Assert-True (Test-Path -LiteralPath $copiedProposal) "Copied TOOL_PROPOSAL.md missing."

    Assert-DirHasOnlyReadme -DirPath (Join-Path $positiveBuild "candidate") -Label "candidate/"
    Assert-DirHasOnlyReadme -DirPath (Join-Path $positiveBuild "tests") -Label "tests/"

    Assert-True (Test-Path -LiteralPath (Join-Path $positiveBuild "IMPLEMENTATION_PLAN.md")) "IMPLEMENTATION_PLAN.md missing."
    Assert-True (Test-Path -LiteralPath (Join-Path $positiveBuild "BUILD_REVIEW.md")) "BUILD_REVIEW.md missing."
    $impl = Get-Content -Raw -LiteralPath (Join-Path $positiveBuild "IMPLEMENTATION_PLAN.md")
    Assert-True ($impl -match "No generated code is present in this workspace") "IMPLEMENTATION_PLAN must state no generated code."

    # --- Negative path (no TOOL_PROPOSAL.md) ---
    New-MinimalLabSource -SourceDir $negativeSource -RequestId $negativeId -IncludeToolProposal $false

    $negBuild = Join-Path $buildsRoot $negativeId
    Assert-True (-not (Test-Path -LiteralPath $negBuild)) "Precondition: negative build dir must not exist."

    $procNeg = Invoke-ToolBuildCreator -CreatorPath $creatorPath -RequestId $negativeId
    Assert-True ($procNeg.Code -ne 0) "Script should exit nonzero when TOOL_PROPOSAL.md is missing."
    Assert-True (-not (Test-Path -LiteralPath $negBuild)) "No build workspace should be created on validation failure."

    # --- Traversal rejection ---
    New-Item -ItemType Directory -Path $outsideSentinelDir -Force | Out-Null
    Set-Content -LiteralPath $outsideSentinelFile -Value "do not remove" -Encoding UTF8
    foreach ($badId in @("..\tb_ws_sentinel", "../tb_ws_evil")) {
        $procBad = Invoke-ToolBuildCreator -CreatorPath $creatorPath -RequestId $badId
        Assert-True ($procBad.Code -ne 0) "Traversal request id '$badId' should fail nonzero."
        Assert-True ($procBad.Output -match "invalid characters") "Traversal request id '$badId' should return a clear validation error."
    }
    Assert-True (Test-Path -LiteralPath $outsideSentinelFile) "Traversal rejection must not remove directories outside data/tool_builds."
    Assert-True (-not (Test-Path -LiteralPath $outsideTraversalCandidate)) "Traversal rejection must not create directories outside data/tool_builds."

    Assert-GuardHashesUnchanged -RepoRoot $RepoRoot -Before $guardBefore
    Write-Host "OK: tool build workspace script and boundaries passed."
} finally {
    foreach ($p in @($positiveSource, $negativeSource)) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    if ($positiveBuild -and (Test-Path -LiteralPath $positiveBuild)) {
        Remove-Item -LiteralPath $positiveBuild -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($negBuild -and (Test-Path -LiteralPath $negBuild)) {
        Remove-Item -LiteralPath $negBuild -Recurse -Force -ErrorAction SilentlyContinue
    }
    foreach ($p in @($outsideSentinelDir, $outsideTraversalCandidate)) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
