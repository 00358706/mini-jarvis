# Automation lab propose wrapper exit-code propagation test.

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $root = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $root "README.md"))) {
        throw "Could not find repo root (README.md missing) at: $root"
    }
    return $root
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Remove-LabOutput {
    param([string]$RepoRoot, [string]$RequestId)

    $outputDir = Join-Path $RepoRoot ("data\automation_lab\" + $RequestId)
    if (-not (Test-Path -LiteralPath $outputDir)) {
        return
    }

    $automationRoot = Join-Path $RepoRoot "data\automation_lab"
    $resolvedOutput = (Resolve-Path -LiteralPath $outputDir).Path
    $resolvedRoot = (Resolve-Path -LiteralPath $automationRoot).Path
    if ($resolvedOutput.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $outputDir -Recurse -Force
    }
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$requestId = "auto_exit_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("mini_jarvis_fake_python_" + [Guid]::NewGuid().ToString("N"))
$fakePython = Join-Path $tempDir "fake_python.cmd"
$oldPython = $env:PYTHON

try {
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    @"
@echo off
if "%~1"=="-c" exit /b 0
>&2 echo fake python runtime failure
exit /b 37
"@ | Set-Content -LiteralPath $fakePython -Encoding ASCII

    $env:PYTHON = $fakePython
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 `
            -Message "Create a tool to list new Navidrome releases" `
            -RequestId $requestId 2>&1 | Out-String
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    Assert-True ($exitCode -eq 37) "Expected wrapper to propagate fake Python exit code 37; got '$exitCode'. Output: $output"
    Assert-True ($output -match "fake python runtime failure") "Expected fake Python stderr to be visible in wrapper output."
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ("data\automation_lab\" + $requestId)))) "Failed Python invocation must not create an automation lab run directory."

    Write-Host "OK: automation_lab_propose.ps1 propagates Python failure exit code."
} finally {
    $env:PYTHON = $oldPython
    Remove-LabOutput -RepoRoot $RepoRoot -RequestId $requestId
    if (Test-Path -LiteralPath $tempDir) {
        Remove-Item -LiteralPath $tempDir -Recurse -Force
    }
}
