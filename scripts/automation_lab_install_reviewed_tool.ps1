# Manual/admin registry install for reviewed generated tools (persistent metadata only).

param(
    [Parameter(Mandatory = $true)]
    [string]$ToolBuildId,

    [Parameter(Mandatory = $true)]
    [string]$ConfirmReviewedInstall
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $root = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $root "README.md"))) {
        throw "Could not find repo root (README.md missing) at: $root"
    }
    return $root
}

function Select-Python {
    param([string]$RepoRoot)

    $candidates = @()
    if ($env:PYTHON -and $env:PYTHON.Trim()) {
        $candidates += $env:PYTHON.Trim()
    }
    $venvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        $candidates += $venvPy
    }
    $candidates += @("python", "py")

    foreach ($c in $candidates) {
        try {
            & $c -c "import sys" *> $null
            if ($LASTEXITCODE -eq 0) {
                return $c
            }
        } catch {
            continue
        }
    }
    throw "Could not find a working Python interpreter."
}

$expectedPhrase = "INSTALL_REVIEWED_TOOL"
if ($ConfirmReviewedInstall -ne $expectedPhrase) {
    Write-Host "Confirmation phrase missing or incorrect. No registry changes performed." -ForegroundColor Red
    exit 1
}

$bid = $ToolBuildId.Trim()
if ($bid -notmatch '^[A-Za-z0-9_-]{8,80}$') {
    Write-Host "Invalid ToolBuildId." -ForegroundColor Red
    exit 1
}

$RepoRoot = Resolve-RepoRoot
$Py = Select-Python -RepoRoot $RepoRoot
$helper = Join-Path $RepoRoot "scripts\registry_append_reviewed_generated_tool.py"

& $Py $helper `
    --repo-root $RepoRoot `
    --tool-build-id $bid `
    --confirm-install-review $expectedPhrase

exit $LASTEXITCODE
