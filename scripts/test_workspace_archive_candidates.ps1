# Tests for read-only scripts/report_workspace_archive_candidates.ps1 (no data mutation).

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

function Invoke-ArchiveReport {
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

$reportSrc = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "scripts\report_workspace_archive_candidates.ps1") -Encoding UTF8
foreach ($bad in @(
        'Remove-Item', 'Move-Item', 'Set-Content', 'Add-Content', 'Out-File', 'Compress-Archive',
        'WriteAllText', 'WriteAllBytes', 'CreateText', 'StreamWriter'
    )) {
    Assert-True ($reportSrc -notmatch [regex]::Escape($bad)) "Report script must not contain mutation/write token: $bad"
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("mj_arch_cand_" + [Guid]::NewGuid().ToString("N").Substring(0, 12))
$dataRoot = Join-Path $tempRoot "data"
$reportPs1 = Join-Path $RepoRoot "scripts\report_workspace_archive_candidates.ps1"

try {
    New-Item -ItemType Directory -Path (Join-Path $dataRoot "workspaces\completed\old_completed") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dataRoot "workspaces\rejected\old_rejected") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dataRoot "workspaces\active\active_case") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dataRoot "automation_lab\agent_tp_flow_test123") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dataRoot "tool_builds\tb_reg_test123") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dataRoot "generated_tool_dry_runs\manual_test123") -Force | Out-Null

    $fixture = Join-Path $dataRoot "workspaces\completed\old_completed\keep.txt"
    [System.IO.File]::WriteAllText($fixture, "fixture-data", [System.Text.UTF8Encoding]::new($false))

    $old = [datetime]::UtcNow.AddDays(-45)
    [System.IO.Directory]::SetLastWriteTimeUtc((Join-Path $dataRoot "workspaces\completed\old_completed"), $old)
    [System.IO.Directory]::SetLastWriteTimeUtc((Join-Path $dataRoot "workspaces\rejected\old_rejected"), $old)
    [System.IO.Directory]::SetLastWriteTimeUtc((Join-Path $dataRoot "tool_builds\tb_reg_test123"), $old)
    [System.IO.Directory]::SetLastWriteTimeUtc((Join-Path $dataRoot "generated_tool_dry_runs\manual_test123"), $old)

    $recent = [datetime]::UtcNow.AddDays(-1)
    [System.IO.Directory]::SetLastWriteTimeUtc((Join-Path $dataRoot "automation_lab\agent_tp_flow_test123"), $recent)

    $hashBefore = Get-FileSha256Hex -Path $fixture

    $r1 = Invoke-ArchiveReport -ReportScript $reportPs1 -ArgumentList @(
        '-DataRoot', $dataRoot,
        '-OlderThanDays', '30',
        '-Top', '50'
    )
    Assert-True ($r1.Code -eq 0) "Archive report failed: $($r1.Output)"
    $o1 = $r1.Output
    Assert-True ($o1 -match 'old_completed') "Expected old_completed in output."
    Assert-True ($o1 -match 'old_rejected') "Expected old_rejected in output."
    Assert-True ($o1 -match 'agent_tp_flow_test123') "Expected automation_lab test-looking folder."
    Assert-True ($o1 -match 'tb_reg_test123') "Expected tool_builds candidate."
    Assert-True ($o1 -match 'manual_test123') "Expected dry_run candidate."
    Assert-True ($o1 -notmatch 'active_case') "Active workspace must be excluded by default."

    $hashMid = Get-FileSha256Hex -Path $fixture
    Assert-True ($hashMid -eq $hashBefore) "Fixture hash changed after report."

    $r2 = Invoke-ArchiveReport -ReportScript $reportPs1 -ArgumentList @(
        '-DataRoot', $dataRoot,
        '-OlderThanDays', '30',
        '-Top', '50',
        '-IncludeActive'
    )
    Assert-True ($r2.Code -eq 0) "Archive report with IncludeActive failed."
    $o2 = $r2.Output
    Assert-True ($o2 -match 'active_case') "IncludeActive must list active_case."
    Assert-True ($o2 -match 'review_only_never_archive_automatically') "IncludeActive must mark review_only."
    Assert-True ($o2 -match 'active_workspace_included_only_because_includeactive') "Reason must mention IncludeActive."

    $hashAfterActive = Get-FileSha256Hex -Path $fixture
    Assert-True ($hashAfterActive -eq $hashBefore) "Fixture hash changed after IncludeActive report."

    $r3 = Invoke-ArchiveReport -ReportScript $reportPs1 -ArgumentList @(
        '-DataRoot', $dataRoot,
        '-OlderThanDays', '30',
        '-Top', '10',
        '-Json'
    )
    Assert-True ($r3.Code -eq 0) "JSON report failed."
    $j = $r3.Output | ConvertFrom-Json
    Assert-True ($null -ne $j.candidates) "JSON missing candidates."
    foreach ($c in $j.candidates) {
        Assert-True ($c.mutation_performed -eq $false) "mutation_performed must be false on $($c.relative_path)."
    }
    $activeJson = @($j.candidates | Where-Object { $_.relative_path -match 'active/active_case' })
    Assert-True ($activeJson.Count -eq 0) "Active must not appear in JSON without IncludeActive."

    $r4 = Invoke-ArchiveReport -ReportScript $reportPs1 -ArgumentList @(
        '-DataRoot', $dataRoot,
        '-OlderThanDays', '30',
        '-Top', '50',
        '-Json',
        '-IncludeActive'
    )
    $j4 = $r4.Output | ConvertFrom-Json
    $activeJson2 = @($j4.candidates | Where-Object { $_.relative_path -match 'active/active_case' })
    Assert-True ($activeJson2.Count -ge 1) "IncludeActive JSON must include active_case."
    Assert-True ($activeJson2[0].suggested_action -eq 'review_only_never_archive_automatically') "Active suggested_action in JSON."

    $combined = @($j4.candidates | Where-Object { $_.relative_path -match 'agent_tp_flow' })
    if ($combined.Count -ge 1) {
        $r = $combined[0].reason
        Assert-True (($r -is [array]) -or ($r -match 'test_artifact')) "Combined reasons for test-looking automation lab row."
    }

    $hashEnd = Get-FileSha256Hex -Path $fixture
    Assert-True ($hashEnd -eq $hashBefore) "Fixture hash changed after JSON reports."

    Write-Host "OK: workspace archive candidates report tests passed."
} finally {
    if ($tempRoot -and (Test-Path -LiteralPath $tempRoot)) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
