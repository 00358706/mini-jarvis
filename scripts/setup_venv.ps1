# Setup a project-local Python virtual environment (.venv).
#
# - Does not delete existing .venv
# - Does not install globally
# - Intended to standardize interpreter+deps across gateway, tests, and integrations

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    # Detect repo root as parent of scripts/ (this file's directory).
    $root = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $root "requirements.txt"))) {
        throw "Could not find requirements.txt at repo root: $root"
    }
    return $root
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

Write-Host ("Repo root: " + $RepoRoot)

if (-not (Test-Path $VenvDir)) {
    Write-Host "Creating venv at .venv ..."
    python -m venv .venv
} else {
    Write-Host "Found existing .venv (not modifying)."
}

if (-not (Test-Path $VenvPython)) {
    throw "Expected venv python not found: $VenvPython"
}

# Print Python version and warn on 3.14+
$PyVer = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
Write-Host ("Venv python: " + $VenvPython)
Write-Host ("Venv version: " + $PyVer)

try {
    $major = [int]($PyVer.Split(".")[0])
    $minor = [int]($PyVer.Split(".")[1])
    if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 14)) {
        Write-Host "WARNING: Python 3.14 may not be supported by all dependencies yet. Prefer Python 3.12 for now."
    }
} catch {
    # If parsing fails, do not block setup.
}

Write-Host "Upgrading pip ..."
& $VenvPython -m pip install --upgrade pip

Write-Host "Installing requirements.txt ..."
& $VenvPython -m pip install -r requirements.txt

Write-Host ""
Write-Host "Next steps:"
Write-Host "  .\\.venv\\Scripts\\Activate.ps1"
Write-Host "  python main.py"

