# Tests for read-only scripts/report_workspace_storage.ps1 (no data mutation).

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

function Get-FileSha256Hex {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Invoke-StorageReport {
    param(
        [string]$ReportScript,
        [string[]]$ArgumentList
    )

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $psiArgs = @('-ExecutionPolicy', 'Bypass', '-File', $ReportScript) + $ArgumentList
        $out = & powershell.exe @psiArgs 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return [pscustomobject]@{ Code = $code; Output = $out }
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$reportSrc = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "scripts\report_workspace_storage.ps1") -Encoding UTF8
foreach ($bad in @(
        'Remove-Item', 'Move-Item', 'Set-Content', 'Add-Content', 'Out-File', 'Compress-Archive',
        'WriteAllText', 'WriteAllBytes', 'CreateText', 'StreamWriter'
    )) {
    Assert-True ($reportSrc -notmatch [regex]::Escape($bad)) "Report script must not contain mutation/write token: $bad"
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("mj_ws_report_" + [Guid]::NewGuid().ToString("N").Substring(0, 12))
$dataRoot = Join-Path $tempRoot "data"
$reportPs1 = Join-Path $RepoRoot "scripts\report_workspace_storage.ps1"

try {
    New-Item -ItemType Directory -Path (Join-Path $dataRoot "workspaces\active\keep") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dataRoot "workspaces\completed\old_ws") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dataRoot "automation_lab\agent_tp_flow_test123") -Force | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $dataRoot "automation_lab\agent_tp_flow_test123\marker.txt"), "x", [System.Text.UTF8Encoding]::new($false))
    New-Item -ItemType Directory -Path (Join-Path $dataRoot "tool_builds\tb_ws_smoke") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dataRoot "generated_tool_dry_runs\old_run") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dataRoot "registry") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dataRoot "plans\executed\nested") -Force | Out-Null

    $bigPath = Join-Path $dataRoot "plans\executed\nested\big.bin"
    $smallPath = Join-Path $dataRoot "workspaces\active\keep\a.txt"
    $bytes = New-Object byte[] 5000
    [System.IO.File]::WriteAllBytes($bigPath, $bytes)
    [System.IO.File]::WriteAllText($smallPath, "hello", [System.Text.UTF8Encoding]::new($false))

    $old = [datetime]::UtcNow.AddDays(-45)
    [System.IO.Directory]::SetLastWriteTimeUtc((Join-Path $dataRoot "workspaces\completed\old_ws"), $old)
    [System.IO.Directory]::SetLastWriteTimeUtc((Join-Path $dataRoot "generated_tool_dry_runs\old_run"), $old)

    $hashBeforeBig = Get-FileSha256Hex -Path $bigPath
    $hashBeforeSmall = Get-FileSha256Hex -Path $smallPath

    $rText = Invoke-StorageReport -ReportScript $reportPs1 -ArgumentList @(
        '-DataRoot', $dataRoot,
        '-Top', '5',
        '-OlderThanDays', '30'
    )
    Assert-True ($rText.Code -eq 0) "Report text mode failed: $($rText.Output)"

    $o = $rText.Output
    Assert-True ($o -match 'Top-level directories') "Missing top-level section."
    Assert-True ($o -match 'workspaces') "Missing workspaces in output."
    Assert-True ($o -match 'automation_lab') "Missing automation_lab."
    Assert-True ($o -match 'tool_builds') "Missing tool_builds."
    Assert-True ($o -match 'generated_tool_dry_runs') "Missing generated_tool_dry_runs."
    Assert-True ($o -match 'registry') "Missing registry."
    Assert-True ($o -match 'Workspace state sizes') "Missing workspace states section."
    Assert-True ($o -match 'Largest 5 directories') "Missing largest dirs section."
    Assert-True ($o -match 'plans\\executed' -or $o -match 'plans/executed') "Missing nested plans path in largest."
    Assert-True ($o -match 'Test-looking') "Missing test-looking section."
    Assert-True ($o -match 'agent_tp_flow_test123') "Missing test-looking folder name."
    Assert-True ($o -match 'Archive hints') "Missing archive hints section."

    $hashMidBig = Get-FileSha256Hex -Path $bigPath
    $hashMidSmall = Get-FileSha256Hex -Path $smallPath
    Assert-True ($hashMidBig -eq $hashBeforeBig) "big.bin hash changed after text report."
    Assert-True ($hashMidSmall -eq $hashBeforeSmall) "a.txt hash changed after text report."

    $rJson = Invoke-StorageReport -ReportScript $reportPs1 -ArgumentList @(
        '-DataRoot', $dataRoot,
        '-Top', '3',
        '-OlderThanDays', '30',
        '-Json'
    )
    Assert-True ($rJson.Code -eq 0) "Report JSON mode failed: $($rJson.Output)"
    $j = $rJson.Output | ConvertFrom-Json
    Assert-True ($null -ne $j.data_root) "JSON missing data_root."
    Assert-True ($null -ne $j.largest_directories) "JSON missing largest_directories."
    Assert-True ($j.top_level_directories.Count -ge 1) "JSON top_level_directories empty."

    $rFiles = Invoke-StorageReport -ReportScript $reportPs1 -ArgumentList @(
        '-DataRoot', $dataRoot,
        '-Top', '5',
        '-IncludeFiles'
    )
    Assert-True ($rFiles.Code -eq 0) "Report with -IncludeFiles failed."
    Assert-True ($rFiles.Output -match 'Largest 5 files') "IncludeFiles section missing."

    $hashAfterBig = Get-FileSha256Hex -Path $bigPath
    $hashAfterSmall = Get-FileSha256Hex -Path $smallPath
    Assert-True ($hashAfterBig -eq $hashBeforeBig) "big.bin hash changed after JSON report."
    Assert-True ($hashAfterSmall -eq $hashBeforeSmall) "a.txt hash changed after JSON report."

    Write-Host "OK: workspace storage report tests passed."
} finally {
    if ($tempRoot -and (Test-Path -LiteralPath $tempRoot)) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
