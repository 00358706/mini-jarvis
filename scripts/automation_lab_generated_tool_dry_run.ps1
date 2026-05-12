# Review-only dry-run for installed generated registry metadata (no execution, no registry mutation).

param(
    [Parameter(Mandatory = $true)]
    [string]$ToolName,

    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $root = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $root "README.md"))) {
        throw "Could not find repo root (README.md missing) at: $root"
    }
    return $root
}

function Test-GeneratedToolDryRunToolName {
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name)) { return $false }
    if ($Name.Length -gt 200) { return $false }
    # Case-sensitive: generated install names are lowercase [a-z0-9_] after the prefix.
    if ($Name -cnotmatch '^generated_[a-z0-9_]+$') { return $false }
    return $true
}

function Test-GeneratedToolDryRunVersion {
    param([string]$Ver)
    if ([string]::IsNullOrWhiteSpace($Ver)) { return $false }
    if ($Ver -cnotmatch '^v\d+$') { return $false }
    return $true
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

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

# --- Malformed / unsafe CLI: fail closed, no evidence directory ---
if (-not (Test-GeneratedToolDryRunToolName -Name $ToolName)) {
    [Console]::Error.WriteLine(
        "Invalid -ToolName: must match ^generated_[a-z0-9_]+$ case-sensitively (lowercase hex id segment only; no path-like segments)."
    )
    exit 1
}
if (-not (Test-GeneratedToolDryRunVersion -Ver $Version)) {
    [Console]::Error.WriteLine("Invalid -Version: must match ^v\d+$ (e.g. v1).")
    exit 1
}

$Py = Select-Python -RepoRoot $RepoRoot
$ts = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$suffix = [Guid]::NewGuid().ToString("N").Substring(0, 6)
$runId = "${ts}-${suffix}"
$dryRoot = Join-Path $RepoRoot "data\generated_tool_dry_runs"
$outDir = Join-Path $dryRoot $runId
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

$helper = Join-Path $RepoRoot "scripts\generated_tool_dry_run.py"
& $Py $helper --tool-name $ToolName --version $Version --out-dir $outDir
$code = $LASTEXITCODE
if ($code -ne 0) {
    exit $code
}
exit 0
