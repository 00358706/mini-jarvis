# Read-only archive *candidate* report (stdout only). Does not archive, delete, move, or mutate data.

param(
    [string]$DataRoot = ".\data",

    [ValidateRange(0, 3650)]
    [int]$OlderThanDays = 30,

    [ValidateRange(1, 500)]
    [int]$Top = 50,

    [switch]$IncludeActive,

    [switch]$Json
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $root = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $root "README.md"))) {
        throw "Could not find repo root (README.md missing) at: $root"
    }
    return $root
}

function Resolve-DataRootPath {
    param(
        [string]$DataRootParam,
        [string]$RepoRoot
    )

    $trim = $DataRootParam.Trim()
    if ([string]::IsNullOrWhiteSpace($trim)) {
        return (Join-Path $RepoRoot "data")
    }
    if ([System.IO.Path]::IsPathRooted($trim)) {
        return [System.IO.Path]::GetFullPath($trim)
    }
    $combined = Join-Path $RepoRoot ($trim -replace '^\.\\', '' -replace '^\./', '')
    return [System.IO.Path]::GetFullPath($combined)
}

function Test-TestLookingLeafName {
    param([string]$Name)

    $patterns = @(
        "agent_tp_flow_", "navidrome_", "tb_", "tb_reg_", "tb_regdup_", "tb_regbad_", "tb_regroll_",
        "manual_", "test_"
    )
    foreach ($p in $patterns) {
        if ($Name -like "*$p*") {
            return $true
        }
    }
    return $false
}

function Get-SubtreeFileStats {
    param([string]$RootDir)

    $bytes = [long]0
    $count = 0
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue([System.IO.Path]::GetFullPath($RootDir))
    while ($queue.Count -gt 0) {
        $dir = [string]$queue.Dequeue()
        try {
            foreach ($sub in [System.IO.Directory]::EnumerateDirectories($dir)) {
                try {
                    $attr = [System.IO.File]::GetAttributes($sub)
                    if (($attr -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                        continue
                    }
                    $queue.Enqueue($sub)
                } catch {
                    continue
                }
            }
            foreach ($filePath in [System.IO.Directory]::EnumerateFiles($dir)) {
                try {
                    $fi = [System.IO.FileInfo]::new($filePath)
                    if (($fi.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                        continue
                    }
                    $bytes += $fi.Length
                    $count++
                } catch {
                    continue
                }
            }
        } catch {
            continue
        }
    }
    return [pscustomobject]@{ Bytes = $bytes; FileCount = $count }
}

function Get-AgeDays {
    param([datetime]$LastWriteUtc)

    return [math]::Round(([datetime]::UtcNow - $LastWriteUtc).TotalDays, 2)
}

function Test-IsOlderThanDays {
    param(
        [datetime]$LastWriteUtc,
        [int]$Days
    )

    return (([datetime]::UtcNow - $LastWriteUtc).TotalDays -gt [double]$Days)
}

function Merge-ReasonList {
    param(
        [string[]]$Existing,
        [string[]]$Add
    )

    $list = New-Object System.Collections.ArrayList
    foreach ($x in @($Existing) + @($Add)) {
        if (-not $x) { continue }
        if ($list -notcontains $x) {
            [void]$list.Add($x)
        }
    }
    return @($list.ToArray())
}

$repoRoot = Resolve-RepoRoot
$dataRootFull = Resolve-DataRootPath -DataRootParam $DataRoot -RepoRoot $repoRoot

if (-not (Test-Path -LiteralPath $dataRootFull)) {
    throw "DataRoot does not exist: $dataRootFull"
}

$utcNow = [datetime]::UtcNow
$candidateMap = @{}  # fullPath -> record object (mutable reasons list)

function Upsert-Candidate {
    param(
        [hashtable]$Map,
        [string]$FullPath,
        [string]$RelativePath,
        [string]$CandidateType,
        [string[]]$ReasonsToAdd,
        [string]$SuggestedAction,
        [datetime]$LastWriteUtc,
        [long]$TotalBytes,
        [int]$FileCount
    )

    $key = [System.IO.Path]::GetFullPath($FullPath).TrimEnd('\', '/')
    if ($Map.ContainsKey($key)) {
        $rec = $Map[$key]
        $existingR = @()
        if ($null -ne $rec.reason) {
            if ($rec.reason -is [System.Array]) {
                $existingR = @($rec.reason)
            } else {
                $existingR = @([string]$rec.reason)
            }
        }
        $rec.reason = Merge-ReasonList -Existing $existingR -Add $ReasonsToAdd
        $rec.suggested_action = $SuggestedAction
        $rec.last_write_time_utc = $LastWriteUtc.ToString("yyyy-MM-ddTHH:mm:ssZ")
        $rec.age_days = Get-AgeDays -LastWriteUtc $LastWriteUtc
        $rec.total_bytes = $TotalBytes
        $rec.total_mb = [math]::Round([double]$TotalBytes / 1MB, 4)
        $rec.file_count = $FileCount
        return
    }

    $Map[$key] = [ordered]@{
        path                 = $key
        relative_path        = $RelativePath.Replace('\', '/')
        candidate_type       = $CandidateType
        reason               = $ReasonsToAdd
        age_days             = (Get-AgeDays -LastWriteUtc $LastWriteUtc)
        last_write_time_utc  = $LastWriteUtc.ToString("yyyy-MM-ddTHH:mm:ssZ")
        total_bytes          = $TotalBytes
        total_mb             = [math]::Round([double]$TotalBytes / 1MB, 4)
        file_count           = $FileCount
        suggested_action     = $SuggestedAction
        mutation_performed   = $false
    }
}

$scanRoots = @(
    @{ Rel = "workspaces/completed"; Type = "workspace_completed" },
    @{ Rel = "workspaces/rejected"; Type = "workspace_rejected" },
    @{ Rel = "automation_lab"; Type = "automation_lab_run" },
    @{ Rel = "tool_builds"; Type = "tool_build_workspace" },
    @{ Rel = "generated_tool_dry_runs"; Type = "dry_run_evidence" }
)

foreach ($sr in $scanRoots) {
    $base = Join-Path $dataRootFull ($sr.Rel -replace '/', [string][char][System.IO.Path]::DirectorySeparatorChar)
    if (-not (Test-Path -LiteralPath $base)) {
        continue
    }
    foreach ($di in Get-ChildItem -LiteralPath $base -Directory -Force -ErrorAction SilentlyContinue) {
        if (($di.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            continue
        }
        $lw = $di.LastWriteTimeUtc
        $name = $di.Name
        $ageOk = Test-IsOlderThanDays -LastWriteUtc $lw -Days $OlderThanDays
        $testOk = Test-TestLookingLeafName -Name $name
        if (-not $ageOk -and -not $testOk) {
            continue
        }
        $stats = Get-SubtreeFileStats -RootDir $di.FullName
        $rel = ($sr.Rel.TrimEnd('/') + "/" + $name).Replace('\', '/')
        $reasons = @()
        if ($ageOk) { $reasons += "age_threshold" }
        if ($testOk) { $reasons += "test_artifact_name" }
        Upsert-Candidate -Map $candidateMap -FullPath $di.FullName -RelativePath $rel `
            -CandidateType $sr.Type -ReasonsToAdd $reasons -SuggestedAction "archive_later" `
            -LastWriteUtc $lw -TotalBytes $stats.Bytes -FileCount $stats.FileCount
    }
}

if ($IncludeActive) {
    $activeBase = Join-Path $dataRootFull "workspaces\active"
    if (Test-Path -LiteralPath $activeBase) {
        foreach ($di in Get-ChildItem -LiteralPath $activeBase -Directory -Force -ErrorAction SilentlyContinue) {
            if (($di.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                continue
            }
            $stats = Get-SubtreeFileStats -RootDir $di.FullName
            $lw = $di.LastWriteTimeUtc
            $rel = "workspaces/active/" + $di.Name
            $reasons = @(
                "active_workspace_included_only_because_includeactive_switch_was_used"
            )
            Upsert-Candidate -Map $candidateMap -FullPath $di.FullName -RelativePath $rel `
                -CandidateType "workspace_active" -ReasonsToAdd $reasons `
                -SuggestedAction "review_only_never_archive_automatically" `
                -LastWriteUtc $lw -TotalBytes $stats.Bytes -FileCount $stats.FileCount
        }
    }
}

$all = @($candidateMap.Values | ForEach-Object { $_ })
$fmt = "yyyy-MM-ddTHH:mm:ssZ"
$cult = [System.Globalization.CultureInfo]::InvariantCulture
$styles = [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal
$sorted = $all | Sort-Object `
    @{ Expression = { [datetime]::ParseExact([string]$_.last_write_time_utc, $fmt, $cult, $styles) }; Ascending = $true },
    @{ Expression = { [long]$_.total_bytes }; Ascending = $false }
$selected = @($sorted | Select-Object -First $Top)

$meta = [ordered]@{
    schema_version     = "workspace-archive-candidates-report.v1"
    data_root          = $dataRootFull
    repo_root          = $repoRoot
    generated_at_utc   = $utcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    older_than_days    = $OlderThanDays
    top_limit          = $Top
    include_active     = [bool]$IncludeActive
    mutation_performed = $false
    candidates         = $selected
}

if ($Json) {
    $meta | ConvertTo-Json -Depth 8
    exit 0
}

Write-Output "Mini-Jarvis archive candidate report (read-only; no mutations)"
Write-Output "DataRoot: $dataRootFull"
Write-Output "OlderThanDays: $OlderThanDays | Top: $Top | IncludeActive: $IncludeActive"
Write-Output "Generated (UTC): $($meta['generated_at_utc'])"
Write-Output ""
Write-Output "Sorted: oldest last_write_time_utc first, then larger total_bytes first (tie-break). Showing up to $Top rows."
Write-Output ""

foreach ($c in $selected) {
    $reasonStr = if ($c.reason -is [array]) { ($c.reason -join ", ") } else { [string]$c.reason }
    Write-Output ("---")
    Write-Output ("relative_path: {0}" -f $c.relative_path)
    Write-Output ("candidate_type: {0}" -f $c.candidate_type)
    Write-Output ("suggested_action: {0}" -f $c.suggested_action)
    Write-Output ("mutation_performed: {0}" -f $c.mutation_performed)
    Write-Output ("last_write_time_utc: {0}" -f $c.last_write_time_utc)
    Write-Output ("age_days: {0}" -f $c.age_days)
    Write-Output ("total_mb: {0}  bytes={1}  files={2}" -f $c.total_mb, $c.total_bytes, $c.file_count)
    Write-Output ("reason: {0}" -f $reasonStr)
    Write-Output ("path: {0}" -f $c.path)
}

exit 0
