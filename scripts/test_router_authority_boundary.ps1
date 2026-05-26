# Run the local Python tests that cover automatic chatbar routing and authority boundaries.
#
# This script intentionally runs in-process TestClient tests only. It does not start
# the gateway, approve plans, execute generated tools, mutate the registry, or call
# real services.

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $root = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $root "requirements.txt"))) {
        throw "Could not find requirements.txt at repo root: $root"
    }
    return $root
}

function Invoke-Python {
    param(
        [string]$Command,
        [string[]]$Arguments
    )

    if ($Command -eq "py -3.12") {
        & py -3.12 @Arguments
    } else {
        & $Command @Arguments
    }
}

function Test-PythonCandidate {
    param([string]$Command)

    if (-not $Command -or -not $Command.Trim()) {
        return $false
    }

    try {
        Invoke-Python -Command $Command.Trim() -Arguments @("-c", "import fastapi, httpx, pydantic") *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Select-Python {
    param([string]$RepoRoot)

    $candidates = @()
    $venvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { $candidates += $venvPy }
    if ($env:PYTHON -and $env:PYTHON.Trim()) { $candidates += $env:PYTHON.Trim() }
    $candidates += "py -3.12"
    $candidates += "py"
    $candidates += "python"

    foreach ($candidate in $candidates) {
        if (Test-PythonCandidate -Command $candidate) {
            return $candidate
        }
    }

    throw "No usable Python interpreter found with project requirements installed. Run scripts/setup_venv.ps1 or recreate .venv with Python 3.12."
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$Py = Select-Python -RepoRoot $RepoRoot
Write-Host ("Repo root: " + $RepoRoot)
Write-Host ("Selected Python: " + $Py)
Invoke-Python -Command $Py -Arguments @("--version")

$Tests = @(
    "scripts/test_small_router.py",
    "scripts/test_plan_builder_generalization.py",
    "scripts/test_policy_approval_unit_tests.py",
    "scripts/test_ingest_local_tools_gated.py"
)

foreach ($test in $Tests) {
    Write-Host ""
    Write-Host ("=== " + $Py + " " + $test + " ===")
    Invoke-Python -Command $Py -Arguments @($test)
}

Write-Host ""
Write-Host "OK: router and authority-boundary local tests passed."
