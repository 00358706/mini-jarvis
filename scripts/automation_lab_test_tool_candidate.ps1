# Static/offline test harness for review-only tool build candidate workspaces.
# Does not import or execute candidate code, sandbox, registry, gateway, or installs.

param(
    [Parameter(Mandatory = $true)]
    [string]$ToolBuildId
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $root = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $root "README.md"))) {
        throw "Could not find repo root (README.md missing) at: $root"
    }
    return $root
}

function Exit-HarnessError {
    param([string]$Message, [int]$Code = 1)
    Write-Host $Message -ForegroundColor Red
    exit $Code
}

function Read-JsonObject {
    param([string]$Path)
    $raw = Get-Content -Raw -LiteralPath $Path -Encoding UTF8
    return $raw | ConvertFrom-Json
}

function Get-NormalizedFullPath {
    param([string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Test-PathUnderRoot {
    param([string]$Path, [string]$Root)

    $separators = [char[]]@(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $normalizedPath = (Get-NormalizedFullPath -Path $Path).TrimEnd($separators)
    $normalizedRoot = (Get-NormalizedFullPath -Path $Root).TrimEnd($separators)
    $rootPrefix = $normalizedRoot + [System.IO.Path]::DirectorySeparatorChar
    return (
        $normalizedPath.Equals($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $normalizedPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)
    )
}

function Assert-PathUnderRoot {
    param([string]$Path, [string]$Root, [string]$Label)

    if (-not (Test-PathUnderRoot -Path $Path -Root $Root)) {
        Exit-HarnessError "$Label path escapes expected root."
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

function Test-GuardHashesMatch {
    param(
        [string]$RepoRoot,
        [hashtable]$Expected
    )

    foreach ($rel in $Expected.Keys) {
        $path = Join-Path $RepoRoot $rel
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash
        if ($actual -ne $Expected[$rel]) {
            return [pscustomobject]@{
                Ok      = $false
                Message = "Guarded file hash changed for $rel"
            }
        }
    }
    return [pscustomobject]@{ Ok = $true; Message = "Guarded runtime files unchanged." }
}

function Add-Check {
    param(
        [System.Collections.Generic.List[object]]$List,
        [string]$CheckId,
        [string]$Status,
        [string]$Message,
        [string]$Severity
    )

    $List.Add([ordered]@{
            check_id  = $CheckId
            status    = $Status
            message   = $Message
            severity  = $Severity
        }) | Out-Null
}

$RepoRoot = Resolve-RepoRoot
$buildId = $ToolBuildId.Trim()
if (-not $buildId) {
    Exit-HarnessError "ToolBuildId must not be empty."
}
if ($buildId -notmatch '^[A-Za-z0-9_-]{8,80}$') {
    Exit-HarnessError "ToolBuildId must match ^[A-Za-z0-9_-]{8,80}$."
}

$toolBuildsRoot = Join-Path (Join-Path $RepoRoot "data") "tool_builds"
$buildRoot = Join-Path $toolBuildsRoot $buildId

Assert-PathUnderRoot -Path $buildRoot -Root $toolBuildsRoot -Label "Tool build workspace"

if (-not (Test-Path -LiteralPath $buildRoot)) {
    Exit-HarnessError "Tool build workspace not found: data/tool_builds/$buildId"
}

$indexPath = Join-Path $buildRoot "BUILD_INDEX.json"
$candidateDir = Join-Path $buildRoot "candidate"
$testsDir = Join-Path $buildRoot "tests"
$candidatePy = Join-Path $candidateDir "CANDIDATE_TOOL.py"
$toolSchema = Join-Path $candidateDir "TOOL_SCHEMA.json"
$candidateNotes = Join-Path $candidateDir "CANDIDATE_NOTES.md"
$riskNotes = Join-Path $candidateDir "RISK_NOTES.md"
$testPlan = Join-Path $testsDir "TEST_PLAN.md"
$resultsPath = Join-Path $buildRoot "TEST_RESULTS.json"
$summaryPath = Join-Path $buildRoot "TEST_SUMMARY.md"

$required = @(
    @{ Path = $indexPath; Label = "BUILD_INDEX.json" },
    @{ Path = $candidatePy; Label = "candidate/CANDIDATE_TOOL.py" },
    @{ Path = $toolSchema; Label = "candidate/TOOL_SCHEMA.json" },
    @{ Path = $candidateNotes; Label = "candidate/CANDIDATE_NOTES.md" },
    @{ Path = $riskNotes; Label = "candidate/RISK_NOTES.md" },
    @{ Path = $testPlan; Label = "tests/TEST_PLAN.md" }
)

foreach ($item in $required) {
    if (-not (Test-Path -LiteralPath $item.Path)) {
        Exit-HarnessError "Required path missing: $($item.Label)"
    }
}

if (Test-Path -LiteralPath $resultsPath) {
    Exit-HarnessError "TEST_RESULTS.json already exists; refusing to overwrite."
}
if (Test-Path -LiteralPath $summaryPath) {
    Exit-HarnessError "TEST_SUMMARY.md already exists; refusing to overwrite."
}

$bi = Read-JsonObject -Path $indexPath

function Test-BuildIndexSafe {
    param($Index)

    $rules = @(
        @{ Name = "authority"; Expected = $false }
        @{ Name = "review_evidence_only"; Expected = $true }
        @{ Name = "install_allowed"; Expected = $false }
        @{ Name = "execution_allowed"; Expected = $false }
        @{ Name = "registry_modified"; Expected = $false }
        @{ Name = "tools_executed"; Expected = $false }
        @{ Name = "sandbox_worker_invoked"; Expected = $false }
        @{ Name = "generated_code_present"; Expected = $true }
        @{ Name = "candidate_generation_completed"; Expected = $true }
    )
    foreach ($r in $rules) {
        $n = $r.Name
        $actual = $Index.$n
        if ($actual -ne $r.Expected) {
            return "Unsafe BUILD_INDEX.json: '$n' must be $($r.Expected) (got $actual)."
        }
    }
    return $null
}

$unsafeReason = Test-BuildIndexSafe -Index $bi
if ($null -ne $unsafeReason) {
    Exit-HarnessError $unsafeReason
}

$indexBackup = Get-Content -Raw -LiteralPath $indexPath -Encoding UTF8
$guardedBefore = Get-GuardHashes -RepoRoot $RepoRoot
$toolsPyPath = Join-Path $RepoRoot "tools.py"
$toolsPyBefore = Get-Content -Raw -LiteralPath $toolsPyPath -Encoding UTF8

$checks = New-Object System.Collections.Generic.List[object]

# --- Static checks (no candidate execution) ---
try {
    $schemaText = Get-Content -Raw -LiteralPath $toolSchema -Encoding UTF8
    $schemaObj = $schemaText | ConvertFrom-Json
    Add-Check -List $checks -CheckId "tool_schema_json_parse" -Status "passed" -Message "TOOL_SCHEMA.json parses as JSON." -Severity "info"
}
catch {
    Add-Check -List $checks -CheckId "tool_schema_json_parse" -Status "failed" -Message "TOOL_SCHEMA.json is not valid JSON: $($_.Exception.Message)" -Severity "error"
    $schemaObj = $null
}

if ($null -ne $schemaObj) {
    $roOk = ($schemaObj.PSObject.Properties.Name -contains "review_only") -and ($schemaObj.review_only -eq $true)
    $advOk = ($schemaObj.PSObject.Properties.Name -contains "advisory") -and ($schemaObj.advisory -eq $true)
    if ($roOk -and $advOk) {
        Add-Check -List $checks -CheckId "tool_schema_review_flags" -Status "passed" -Message "review_only and advisory are true." -Severity "info"
    }
    else {
        Add-Check -List $checks -CheckId "tool_schema_review_flags" -Status "failed" -Message "Expected review_only: true and advisory: true on TOOL_SCHEMA.json." -Severity "error"
    }
}

try {
    $pyText = Get-Content -Raw -LiteralPath $candidatePy -Encoding UTF8
    if ($null -eq $pyText) { $pyText = "" }
    Add-Check -List $checks -CheckId "candidate_py_readable" -Status "passed" -Message "CANDIDATE_TOOL.py read as text." -Severity "info"
}
catch {
    $pyText = $null
    Add-Check -List $checks -CheckId "candidate_py_readable" -Status "failed" -Message "Could not read CANDIDATE_TOOL.py: $($_.Exception.Message)" -Severity "error"
}

if ($null -ne $pyText) {
    if ($pyText -match "Review-only") {
        Add-Check -List $checks -CheckId "candidate_py_review_marker" -Status "passed" -Message "Contains review-only warning text." -Severity "info"
    }
    else {
        Add-Check -List $checks -CheckId "candidate_py_review_marker" -Status "failed" -Message "Missing expected review-only marker text." -Severity "error"
    }

    $forbidden = @(
        @{ Id = "no_main_guard"; Pattern = '(?i)if\s+__name__'; Message = "Must not contain if __name__ entrypoint." }
        @{ Id = "no_http_clients"; Pattern = '(?i)\bimport\s+(requests|httpx|urllib)\b'; Message = "Must not import HTTP client modules." }
        @{ Id = "no_subprocess"; Pattern = '(?i)(subprocess\.|\bimport\s+subprocess\b)'; Message = "Must not use or import subprocess." }
        @{ Id = "no_open_call"; Pattern = '(?i)\bopen\s*\('; Message = "Must not call open()." }
        @{ Id = "no_registry_import"; Pattern = '(?i)(\bimport\s+registry\b|\bfrom\s+registry\b)'; Message = "Must not import registry." }
        @{ Id = "no_sandbox_import"; Pattern = '(?i)(\bimport\s+sandbox\b|\bfrom\s+sandbox\b)'; Message = "Must not import sandbox." }
        @{ Id = "no_tools_import"; Pattern = '(?i)(\bimport\s+tools\b|\bfrom\s+tools\b)'; Message = "Must not import tools module." }
        @{ Id = "no_main_import"; Pattern = '(?i)(\bimport\s+main\b|\bfrom\s+main\b)'; Message = "Must not import main/gateway entry." }
        @{ Id = "no_url_literals"; Pattern = '(?i)https?://'; Message = "Must not contain http(s) URL literals (direct network hint)." }
    )

    $pyFailed = $false
    foreach ($fb in $forbidden) {
        if ($pyText -match $fb.Pattern) {
            Add-Check -List $checks -CheckId $fb.Id -Status "failed" -Message $fb.Message -Severity "error"
            $pyFailed = $true
        }
    }
    if (-not $pyFailed) {
        foreach ($fb in $forbidden) {
            Add-Check -List $checks -CheckId $fb.Id -Status "passed" -Message "Pattern OK: $($fb.Id)" -Severity "info"
        }
    }
}

# Candidate tree containment
$candidateOk = $true
Get-ChildItem -LiteralPath $candidateDir -Recurse -File -Force | ForEach-Object {
    $full = $_.FullName
    if (-not (Test-PathUnderRoot -Path $full -Root $candidateDir)) {
        $candidateOk = $false
    }
}
if ($candidateOk) {
    Add-Check -List $checks -CheckId "candidate_tree_contained" -Status "passed" -Message "All files under candidate/ stay within candidate/." -Severity "info"
}
else {
    Add-Check -List $checks -CheckId "candidate_tree_contained" -Status "failed" -Message "A file path escapes candidate/ root." -Severity "error"
}

# tools.py unchanged (no copy of candidate into tools module)
$toolsPyAfter = Get-Content -Raw -LiteralPath $toolsPyPath -Encoding UTF8
if ($toolsPyAfter -eq $toolsPyBefore) {
    Add-Check -List $checks -CheckId "tools_py_unchanged" -Status "passed" -Message "tools.py content unchanged." -Severity "info"
}
else {
    Add-Check -List $checks -CheckId "tools_py_unchanged" -Status "failed" -Message "tools.py was modified during harness run." -Severity "error"
}

if ($toolsPyAfter -notmatch "proposed_tool_placeholder") {
    Add-Check -List $checks -CheckId "tools_py_no_candidate_stub" -Status "passed" -Message "tools.py does not contain candidate stub marker." -Severity "info"
}
else {
    Add-Check -List $checks -CheckId "tools_py_no_candidate_stub" -Status "failed" -Message "tools.py appears to contain candidate stub text." -Severity "error"
}

$guardResult = Test-GuardHashesMatch -RepoRoot $RepoRoot -Expected $guardedBefore
if ($guardResult.Ok) {
    Add-Check -List $checks -CheckId "guarded_runtime_unchanged" -Status "passed" -Message $guardResult.Message -Severity "info"
}
else {
    Add-Check -List $checks -CheckId "guarded_runtime_unchanged" -Status "failed" -Message $guardResult.Message -Severity "error"
}

$failedCount = @($checks | Where-Object { $_.status -eq "failed" }).Count
$overall = if ($failedCount -eq 0) { "passed" } else { "failed" }

$createdAt = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")

$resultsObj = [ordered]@{
    schema_version               = "generated-tool-test-results.v1"
    tool_build_id                = $buildId
    created_at                   = $createdAt
    test_harness_kind            = "static_review"
    candidate_code_executed      = $false
    sandbox_worker_invoked       = $false
    registry_modified            = $false
    tools_executed               = $false
    install_allowed              = $false
    execution_allowed            = $false
    real_service_calls           = $false
    overall_status               = $overall
    checks                       = @($checks.ToArray())
}

try {
    ($resultsObj | ConvertTo-Json -Depth 25) | Set-Content -LiteralPath $resultsPath -Encoding UTF8

    $summaryLines = @(
        '# Generated tool test summary (static review only)',
        '',
        '- **Harness:** `static_review` — file and schema inspection only.',
        '- **Candidate code was not executed** (no import, no Python run of `CANDIDATE_TOOL.py`).',
        '- **No registry, sandbox, tool execution, gateway, or install path** was used by this harness.',
        "- **Overall status:** ``$overall``",
        '',
        '## Evidence',
        '',
        '- Detailed checks: `TEST_RESULTS.json` (review evidence only; not authority).',
        '',
        '## Important',
        '',
        'Passing checks **do not** approve installation, registry changes, or execution. Registry `status=installed` remains execution truth only after normal gateway flows.'
    )
    Set-Content -LiteralPath $summaryPath -Value ($summaryLines -join "`n") -Encoding UTF8

    if ($overall -eq "passed") {
        $bi | Add-Member -NotePropertyName test_harness_completed -NotePropertyValue $true -Force
        $bi | Add-Member -NotePropertyName static_validation_completed -NotePropertyValue $true -Force
        $bi | Add-Member -NotePropertyName test_results_path -NotePropertyValue "TEST_RESULTS.json" -Force
        $bi | Add-Member -NotePropertyName test_summary_path -NotePropertyValue "TEST_SUMMARY.md" -Force
        $bi | Add-Member -NotePropertyName test_harness_kind -NotePropertyValue "static_review" -Force
        $bi | Add-Member -NotePropertyName candidate_code_executed -NotePropertyValue $false -Force
        $bi | Add-Member -NotePropertyName install_allowed -NotePropertyValue $false -Force
        $bi | Add-Member -NotePropertyName execution_allowed -NotePropertyValue $false -Force
        $bi | Add-Member -NotePropertyName registry_modified -NotePropertyValue $false -Force
        $bi | Add-Member -NotePropertyName tools_executed -NotePropertyValue $false -Force
        $bi | Add-Member -NotePropertyName sandbox_worker_invoked -NotePropertyValue $false -Force
        $bi | Add-Member -NotePropertyName authority -NotePropertyValue $false -Force
        $bi | Add-Member -NotePropertyName review_evidence_only -NotePropertyValue $true -Force
        ($bi | ConvertTo-Json -Depth 25) | Set-Content -LiteralPath $indexPath -Encoding UTF8
    }
}
catch {
    if (Test-Path -LiteralPath $resultsPath) {
        Remove-Item -LiteralPath $resultsPath -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $summaryPath) {
        Remove-Item -LiteralPath $summaryPath -Force -ErrorAction SilentlyContinue
    }
    Set-Content -LiteralPath $indexPath -Value $indexBackup -Encoding UTF8
    exit 3
}

Write-Host "Wrote $overall static harness results under data/tool_builds/$buildId"

if ($overall -eq "failed") {
    exit 2
}
exit 0
