# Commit and push only explicitly approved files for Mini-Jarvis.
# Refuses main/master, forbidden paths, empty file lists, pre-existing staged files, and missing approval phrase.
# This script stages exact paths only. It never uses git add .

param(
    [Parameter(Mandatory=$true)]
    [string[]]$Files,

    [Parameter(Mandatory=$true)]
    [string]$Message,

    [Parameter(Mandatory=$true)]
    [string]$Confirm,

    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$RequiredApprovalPhrase = "Approved: commit and push this branch."

function Invoke-Git {
    param([string[]]$GitArgs)

    $oldErrorActionPreference = $ErrorActionPreference
    try {
        # Git may write non-fatal warnings to stderr, for example CRLF/LF
        # conversion warnings during `git add`. Capture those warnings without
        # letting Windows PowerShell convert them into terminating errors.
        $script:ErrorActionPreference = "Continue"
        $output = & git -C $RepoRoot @GitArgs 2>&1
        $code = $LASTEXITCODE
    }
    finally {
        $script:ErrorActionPreference = $oldErrorActionPreference
    }

    return [pscustomobject]@{ Code = $code; Output = @($output) }
}

function Assert-GitOk {
    param(
        [string[]]$GitArgs,
        [string]$Message
    )

    $result = Invoke-Git -GitArgs $GitArgs
    if ($result.Code -ne 0) {
        throw "$Message`n$($result.Output -join "`n")"
    }
    return $result.Output
}

function Get-GitLines {
    param([string[]]$GitArgs)

    $result = Invoke-Git -GitArgs $GitArgs
    if ($result.Code -ne 0) {
        throw ($result.Output -join "`n")
    }
    return @($result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Test-ForbiddenPath {
    param([string]$Path)

    $p = ($Path -replace "\\", "/").TrimStart("/")

    if ($p -match "(^|/)\.env($|\.)") { return "secret/env file" }
    if ($p -match "(^|/)(id_rsa|id_ed25519|credentials|secrets?|tokens?)(\.|$|/)") { return "secret-like path" }
    if ($p -match "^data/workspaces(/|$)") { return "workspace data" }
    if ($p -match "^data/(models|checkpoints|cache|tmp|temp)(/|$)") { return "runtime/model/cache data" }
    if ($p -match "(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|node_modules|dist|build|\.next|\.vite)(/|$)") { return "generated cache/build output" }
    if ($p -match "\.(gguf|safetensors|ckpt|pt|pth|onnx|bin|model)$") { return "model/binary artifact" }

    return $null
}

function Normalize-PathForCompare {
    param([string]$Path)
    return (($Path -replace "\\", "/").TrimStart("/"))
}

if ($Confirm -ne $RequiredApprovalPhrase) {
    throw "Refusing: Confirm must be exactly '$RequiredApprovalPhrase'"
}

if (-not $Files -or $Files.Count -eq 0) {
    throw "Refusing: no files specified."
}

if ([string]::IsNullOrWhiteSpace($Message)) {
    throw "Refusing: commit message is empty."
}

$repo = (Assert-GitOk -GitArgs @("rev-parse", "--show-toplevel") -Message "Not a git repo") -join "`n"
$repo = $repo.Trim()

$branch = (Assert-GitOk -GitArgs @("branch", "--show-current") -Message "Could not determine branch") -join "`n"
$branch = $branch.Trim()

if (-not $branch -or $branch -eq "main" -or $branch -eq "master") {
    throw "Refusing to commit or push on branch: $branch"
}

$normalizedFiles = @()
foreach ($file in $Files) {
    if ([string]::IsNullOrWhiteSpace($file)) {
        throw "Refusing: file list contains an empty path."
    }

    $normalized = Normalize-PathForCompare -Path $file
    if ($normalized -match "(^|/)\.\.?(/|$)") {
        throw "Refusing suspicious path: $file"
    }

    $reason = Test-ForbiddenPath -Path $normalized
    if ($reason) {
        throw "Refusing forbidden path: $file -- $reason"
    }

    $normalizedFiles += $normalized
}

$duplicates = @($normalizedFiles | Group-Object | Where-Object { $_.Count -gt 1 } | ForEach-Object { $_.Name })
if ($duplicates.Count -gt 0) {
    throw "Refusing: duplicate file path(s): $($duplicates -join ', ')"
}

$preExistingStaged = @(Get-GitLines -GitArgs @("diff", "--cached", "--name-only"))
if ($preExistingStaged.Count -gt 0) {
    throw "Refusing: staged files already exist before this script runs. Unstage/review them first:`n$($preExistingStaged -join "`n")"
}

Write-Host "Repo: $repo"
Write-Host "Branch: $branch"
Write-Host ""
Write-Host "Approved files requested:"
foreach ($file in $normalizedFiles) {
    Write-Host "  $file"
}

Write-Host ""
Write-Host "Staging approved files only..."
foreach ($file in $normalizedFiles) {
    Assert-GitOk -GitArgs @("add", "--", $file) -Message "Failed to stage $file" | Out-Null
}

Write-Host ""
Write-Host "Staged files:"
Assert-GitOk -GitArgs @("diff", "--cached", "--name-status") -Message "Could not show staged files"

$stagedNames = @(Get-GitLines -GitArgs @("diff", "--cached", "--name-only"))
$unexpected = @()
foreach ($staged in $stagedNames) {
    $normalizedStaged = Normalize-PathForCompare -Path $staged
    if ($normalizedFiles -notcontains $normalizedStaged) {
        $unexpected += $staged
    }
}

if ($unexpected.Count -gt 0) {
    throw "Refusing: unexpected staged file(s): $($unexpected -join ', ')"
}

$staged = Invoke-Git -GitArgs @("diff", "--cached", "--quiet")
if ($staged.Code -eq 0) {
    throw "Refusing: nothing staged."
}
if ($staged.Code -ne 1) {
    throw "Could not inspect staged diff."
}

Write-Host ""
Write-Host "Committing..."
Assert-GitOk -GitArgs @("commit", "-m", $Message) -Message "Commit failed"

Write-Host ""
Write-Host "Pushing..."
Assert-GitOk -GitArgs @("push", "-u", "origin", $branch) -Message "Push failed"

Write-Host ""
Write-Host "Done."
