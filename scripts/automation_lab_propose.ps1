# Proposal-only automation lab CLI wrapper.

param(
    [Parameter(Mandatory = $true)]
    [string]$Message,

    [string]$RequestId,

    [switch]$UseLocalModel,

    [string]$ModelBaseUrl = "http://127.0.0.1:10000/v1",

    [string]$ModelName = "local-model",

    [switch]$StrictModel
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

    function Test-PythonCandidate {
        param([string]$Candidate)
        if (-not $Candidate -or -not $Candidate.Trim()) { return $false }
        try {
            & $Candidate -c "import sys" *> $null
            return ($LASTEXITCODE -eq 0)
        } catch {
            return $false
        }
    }

    $candidates = @()
    if ($env:PYTHON -and $env:PYTHON.Trim()) {
        $candidates += $env:PYTHON.Trim()
    }

    $venvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        $candidates += $venvPy
    }

    $candidates += @("python", "py")

    if ($env:LOCALAPPDATA) {
        $localPrograms = Join-Path $env:LOCALAPPDATA "Programs\Python"
        try {
            if (Test-Path $localPrograms -ErrorAction Stop) {
                $candidates += Get-ChildItem -Path $localPrograms -Recurse -Filter python.exe -ErrorAction SilentlyContinue |
                    Select-Object -ExpandProperty FullName
            }
        } catch {
            # Best-effort interpreter discovery only.
        }
    }

    if ($env:ProgramFiles) {
        $blenderRoot = Join-Path $env:ProgramFiles "Blender Foundation"
        try {
            if (Test-Path $blenderRoot -ErrorAction Stop) {
                $candidates += Get-ChildItem -Path $blenderRoot -Recurse -Filter python.exe -ErrorAction SilentlyContinue |
                    Where-Object { $_.FullName -like "*\python\bin\python.exe" } |
                    Select-Object -ExpandProperty FullName
            }
        } catch {
            # Best-effort interpreter discovery only.
        }
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonCandidate -Candidate $candidate) {
            return $candidate
        }
    }

    throw "Could not find a working Python interpreter. Set PYTHON to a valid python.exe path."
}

$RepoRoot = Resolve-RepoRoot
$Py = Select-Python -RepoRoot $RepoRoot
$ArgsList = @(
    (Join-Path $RepoRoot "automation_lab.py"),
    "--message",
    $Message
)

if ($RequestId -and $RequestId.Trim()) {
    $ArgsList += @("--request-id", $RequestId.Trim())
}

if ($UseLocalModel) {
    $ArgsList += @(
        "--use-local-model",
        "--model-base-url",
        $ModelBaseUrl,
        "--model-name",
        $ModelName
    )
}

if ($StrictModel) {
    $ArgsList += "--strict-model"
}

& $Py @ArgsList
