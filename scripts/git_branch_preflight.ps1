# Read-only Git branch preflight for Mini-Jarvis.
# Shows branch, dirty files, untracked files, obvious forbidden paths, and EOL-only noise.
# This script does not stage, commit, push, or modify files.

param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$Json
)

$ErrorActionPreference = "Stop"

function Invoke-Git {
    param([string[]]$GitArgs)

    $output = & git -C $RepoRoot @GitArgs 2>&1
    $code = $LASTEXITCODE
    return [pscustomobject]@{ Code = $code; Output = @($output) }
}

function Assert-GitRepo {
    $rootResult = Invoke-Git -GitArgs @("rev-parse", "--show-toplevel")
    if ($rootResult.Code -ne 0) {
        throw "Not a git repository: $RepoRoot`n$($rootResult.Output -join "`n")"
    }
    return ($rootResult.Output -join "`n").Trim()
}

function Get-GitLines {
    param([string[]]$GitArgs)

    $result = Invoke-Git -GitArgs $GitArgs
    if ($result.Code -ne 0) {
        throw ($result.Output -join "`n")
    }
    return @($result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Get-StatusRows {
    $lines = Get-GitLines -GitArgs @("status", "--porcelain=v1")
    $rows = @()

    foreach ($line in $lines) {
        if ($line.Length -lt 3) { continue }
        $path = $line.Substring(3)
        if ($path -match " -> ") {
            $path = ($path -split " -> ", 2)[1]
        }
        $rows += [pscustomobject]@{
            Status = $line.Substring(0, 2)
            Path = $path
            Raw = $line
        }
    }

    return $rows
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

function Test-EolOnlyChange {
    param([string]$Path)

    $normal = Invoke-Git -GitArgs @("diff", "--quiet", "--", $Path)
    if ($normal.Code -eq 0) { return $false }
    if ($normal.Code -ne 1) { return $false }

    $ignoreEol = Invoke-Git -GitArgs @("diff", "--quiet", "--ignore-space-at-eol", "--", $Path)
    return ($ignoreEol.Code -eq 0)
}

$repo = Assert-GitRepo
$branchLines = Get-GitLines -GitArgs @("branch", "--show-current")
$branch = ($branchLines -join "`n").Trim()
if (-not $branch) { $branch = "(detached HEAD)" }

$statusRows = @(Get-StatusRows)
$dirtyTracked = @($statusRows | Where-Object { $_.Status -ne "??" })
$untracked = @($statusRows | Where-Object { $_.Status -eq "??" })

$forbidden = @()
foreach ($row in $statusRows) {
    $reason = Test-ForbiddenPath -Path $row.Path
    if ($reason) {
        $forbidden += [pscustomobject]@{ Path = $row.Path; Reason = $reason; Status = $row.Status }
    }
}

$eolOnly = @()
foreach ($row in $dirtyTracked) {
    if (Test-EolOnlyChange -Path $row.Path) {
        $eolOnly += $row.Path
    }
}

$result = [pscustomobject]@{
    RepoRoot = $repo
    Branch = $branch
    DirtyTracked = @($dirtyTracked | ForEach-Object { [pscustomobject]@{ Status = $_.Status; Path = $_.Path } })
    Untracked = @($untracked | ForEach-Object { $_.Path })
    Forbidden = $forbidden
    EolOnlyTracked = $eolOnly
}

if ($Json) {
    $result | ConvertTo-Json -Depth 5
    exit 0
}

Write-Host "Repo: $($result.RepoRoot)"
Write-Host "Branch: $($result.Branch)"
Write-Host ""
Write-Host "Dirty tracked files: $($result.DirtyTracked.Count)"
foreach ($row in $result.DirtyTracked) {
    Write-Host ("  {0} {1}" -f $row.Status, $row.Path)
}
Write-Host ""
Write-Host "Untracked files: $($result.Untracked.Count)"
foreach ($path in $result.Untracked) {
    Write-Host "  ?? $path"
}
Write-Host ""
Write-Host "Forbidden/sensitive path warnings: $($result.Forbidden.Count)"
foreach ($item in $result.Forbidden) {
    Write-Host ("  {0} {1} -- {2}" -f $item.Status, $item.Path, $item.Reason)
}
Write-Host ""
Write-Host "Line-ending-only tracked changes: $($result.EolOnlyTracked.Count)"
foreach ($path in $result.EolOnlyTracked) {
    Write-Host "  $path"
}
