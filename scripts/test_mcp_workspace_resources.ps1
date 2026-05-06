# MCP workspace resources smoke test (read-only; resources only).
#
# This test does NOT require a full MCP host/client. It uses the script's CLI
# "--read" mode to validate URI parsing and safety constraints.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $RepoRoot "integrations\\mcp\\mini_jarvis_workspace_resources.py"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Assert-Contains {
    param([string]$Text, [string]$Needle, [string]$Message)
    if ($Text -notmatch [Regex]::Escape($Needle)) { throw $Message }
}

function Run-ProcessCapture {
    param(
        [string]$Cmd,
        [string[]]$CmdArgs
    )

    if (-not $CmdArgs -or $CmdArgs.Count -eq 0) {
        throw "Run-ProcessCapture called with empty CmdArgs."
    }

    $stdoutFile = $null
    $stderrFile = $null
    try {
        $stdoutFile = (New-TemporaryFile).FullName
        $stderrFile = (New-TemporaryFile).FullName

        $p = Start-Process `
            -FilePath $Cmd `
            -ArgumentList $CmdArgs `
            -RedirectStandardOutput $stdoutFile `
            -RedirectStandardError $stderrFile `
            -Wait `
            -PassThru `
            -NoNewWindow
    }
    catch {
        Write-Host "--- FAILED TO START PROCESS ---"
        Write-Host ("Command: " + $Cmd)
        Write-Host ("Args: " + ($CmdArgs -join " "))
        throw
    }

    $stdout = ""
    $stderr = ""
    if ($stdoutFile -and (Test-Path $stdoutFile)) {
        $stdout = Get-Content -Raw -Path $stdoutFile
    }
    if ($stderrFile -and (Test-Path $stderrFile)) {
        $stderr = Get-Content -Raw -Path $stderrFile
    }

    try {
        return @{
            code   = $p.ExitCode
            stdout = $stdout
            stderr = $stderr
            cmd    = $Cmd
            args   = $CmdArgs
        }
    } finally {
        if ($stdoutFile -and (Test-Path $stdoutFile)) { Remove-Item -Force $stdoutFile }
        if ($stderrFile -and (Test-Path $stderrFile)) { Remove-Item -Force $stderrFile }
    }
}

function Get-PythonCommandSpec {
    # Interpreter selection order:
    # 1) $env:PYTHON (explicit)
    # 2) .\.venv\Scripts\python.exe if present
    # 3) "python" if "python --version" runs
    # 4) "py -3" as a last resort

    if ($env:PYTHON -and $env:PYTHON.Trim()) {
        return @{
            cmd  = $env:PYTHON.Trim()
            args = @()
        }
    }

    $venvPy = Join-Path $RepoRoot ".venv\\Scripts\\python.exe"
    if (Test-Path $venvPy) {
        return @{
            cmd  = $venvPy
            args = @()
        }
    }

    $probe = Run-ProcessCapture -Cmd "python" -CmdArgs @("--version")
    if ($probe.code -eq 0) {
        return @{
            cmd  = "python"
            args = @()
        }
    }

    return @{
        cmd  = "py"
        args = @("-3")
    }
}

function Run-Read {
    param([string]$Uri)
    $spec = Get-PythonCommandSpec
    $cmd = $spec.cmd
    $cmdArgs = @()
    $cmdArgs += $spec.args
    $cmdArgs += @($Script, "--read", $Uri)
    Write-Host ("Command: " + $cmd)
    Write-Host ("Args: " + ($cmdArgs -join " "))
    $r = Run-ProcessCapture -Cmd $cmd -CmdArgs $cmdArgs
    $combined = ($r.stdout + $r.stderr)
    return @{
        code   = $r.code
        out    = $combined
        stdout = $r.stdout
        stderr = $r.stderr
        cmd    = $cmd
        args   = $cmdArgs
    }
}

function Assert-ExitCode {
    param([hashtable]$RunResult, [int]$Expected, [string]$Context)
    if ($RunResult.code -ne $Expected) {
        Write-Host "--- FAILURE CONTEXT ---"
        Write-Host $Context
        Write-Host "--- COMMAND ---"
        Write-Host ($RunResult.cmd + " " + (($RunResult.args | ForEach-Object { '"' + $_ + '"' }) -join " "))
        Write-Host ("exit_code: " + $RunResult.code)
        Write-Host "--- STDOUT ---"
        Write-Host $RunResult.stdout
        Write-Host "--- STDERR ---"
        Write-Host $RunResult.stderr
        if ($RunResult.stderr -match "ModuleNotFoundError:\s*No module named 'pydantic'") {
            Write-Host ""
            Write-Host "HINT: Selected Python is missing project dependencies."
            Write-Host "Run scripts/setup_venv.ps1, activate .venv, or set `$env:PYTHON to .venv\\Scripts\\python.exe."
        }
        throw ("Unexpected exit code. Expected " + $Expected + " for: " + $Context)
    }
}

Write-Host "--- Case 1: list active workspaces ---"
$R1 = Run-Read "mini-jarvis://workspaces/active"
Assert-ExitCode $R1 0 "list active workspaces"
Assert-Contains $R1.out '"state": "active"' "Expected state=active in list output."

Write-Host "--- Case 2: compact summary for a known active workspace ---"
# Pick an existing workspace id from the filesystem (best-effort).
$ActiveDir = Join-Path $RepoRoot "data\\workspaces\\active"
$TaskId = $null
if (Test-Path $ActiveDir) {
    $dirs = Get-ChildItem -Path $ActiveDir -Directory | Select-Object -First 1
    if ($dirs) { $TaskId = $dirs.Name }
}
if (-not $TaskId) {
    throw "No active workspace directory found to test compact summary."
}
$R2 = Run-Read ("mini-jarvis://workspaces/active/{0}/compact" -f $TaskId)
Assert-ExitCode $R2 0 "compact summary for active workspace"
Assert-Contains $R2.out '"kind": "workspace_compact"' "Expected workspace_compact kind."
Assert-Contains $R2.out ('"task_id": "' + $TaskId + '"') "Expected task_id in compact payload."

Write-Host "--- Case 3: read allowed file PLAN.json ---"
$R3 = Run-Read ("mini-jarvis://workspaces/active/{0}/files/PLAN.json" -f $TaskId)
Assert-ExitCode $R3 0 "read PLAN.json file"
Assert-Contains $R3.out '"filename": "PLAN.json"' "Expected filename PLAN.json in output."

Write-Host "--- Case 4: invalid state rejected ---"
$R4 = Run-Read "mini-jarvis://workspaces/badstate"
if ($R4.code -eq 0) {
    Write-Host "--- Unexpected success output ---"
    Write-Host $R4.out
    throw "Expected nonzero exit for invalid state."
}
Assert-Contains $R4.out "Invalid state" "Expected Invalid state error."

Write-Host "--- Case 5: traversal/invalid filename rejected ---"
$R5 = Run-Read ("mini-jarvis://workspaces/active/{0}/files/%2e%2e%2fREADME.md" -f $TaskId)
if ($R5.code -eq 0) {
    Write-Host "--- Unexpected success output ---"
    Write-Host $R5.out
    throw "Expected nonzero exit for traversal filename."
}
Assert-Contains $R5.out "traversal" "Expected traversal rejection error."

Write-Host "--- Case 6: script must not reference execution/approval paths ---"
$Content = Get-Content -Raw -Path $Script
$Forbidden = @(
    "approve_plan",
    "reject_plan",
    "mark_executed",
    "run_installed_tool",
    "sandbox"
)
foreach ($f in $Forbidden) {
    if ($Content -match [Regex]::Escape($f)) {
        throw ("Forbidden reference found in MCP resources script: " + $f)
    }
}

Write-Host "--- Case 7: script must not register MCP tools ---"
$ToolMarkers = @(
    "@mcp.tool",
    ".tool(",
    "mcp.tool("
)
foreach ($m in $ToolMarkers) {
    if ($Content -match [Regex]::Escape($m)) {
        throw ("MCP tool registration marker found in script (tools are forbidden): " + $m)
    }
}

Write-Host "--- Case 8: negative URI cases (encoded traversal/task-id/path problems) ---"
$BadUris = @(
    "mini-jarvis://workspaces/active/%2e%2e/compact",
    "mini-jarvis://workspaces/active/%5c/compact",
    "mini-jarvis://workspaces/active/safe_id/files/PLAN.json/extra",
    "mini-jarvis://workspaces/active/safe_id/files/%2e%2e%2fREADME.md"
)
foreach ($u in $BadUris) {
    $r = Run-Read $u
    if ($r.code -eq 0) {
        Write-Host "--- Unexpected success output ---"
        Write-Host $r.out
        throw ("Expected nonzero exit for invalid URI: " + $u)
    }
}

Write-Host "Done."

