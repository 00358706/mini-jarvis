# Run all smoke tests using a standardized Python interpreter selection.
#
# Does NOT start the gateway automatically.
# Some tests require the gateway to already be running at http://127.0.0.1:8000.

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
    $venvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { return $venvPy }
    if ($env:PYTHON -and $env:PYTHON.Trim()) { return $env:PYTHON.Trim() }
    return "python"
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$Py = Select-Python -RepoRoot $RepoRoot
$env:PYTHON = $Py

Write-Host ("Repo root: " + $RepoRoot)
Write-Host ("Selected Python: " + $Py)

# Print Python version (best-effort)
try {
    & $Py --version
} catch {
    Write-Host "WARNING: Unable to run selected python --version."
}

Write-Host ""
Write-Host "NOTE: Gateway must be running at http://127.0.0.1:8000 for tests that call it."
Write-Host ""

& $Py -m compileall .

powershell -ExecutionPolicy Bypass -File .\scripts\test_plans_from_message.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\test_workspace_compact_summary.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\test_workspace_review_endpoints.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\test_project_agent_policy.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\test_project_readonly_tools.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\test_openwebui_action_wrapper.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\test_openwebui_plan_review_wrapper.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\test_mcp_workspace_resources.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\test_inspect_file_tool.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\test_propose_patch_tool.ps1

git diff --check

Write-Host ""
Write-Host "Done."

