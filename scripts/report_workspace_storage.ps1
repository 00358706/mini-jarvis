# Read-only storage report for Mini-Jarvis data/evidence folders.
# Output: stdout only (human text or JSON with -Json). No file writes, no mutations.

param(
    [string]$DataRoot = ".\data",

    [ValidateRange(1, 500)]
    [int]$Top = 20,

    [ValidateRange(0, 3650)]
    [int]$OlderThanDays = 30,

    [switch]$IncludeFiles,

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
    # Relative paths resolve from repo root so default .\data is always repo-confined.
    $combined = Join-Path $RepoRoot ($trim -replace '^\.\\', '' -replace '^\./', '')
    return [System.IO.Path]::GetFullPath($combined)
}

function Test-PathIsUnderRoot {
    param(
        [string]$Path,
        [string]$Root
    )

    $p = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $r = [System.IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    return ($p.Equals($r, [StringComparison]::OrdinalIgnoreCase) -or
        $p.StartsWith($r + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
        $p.StartsWith($r + [System.IO.Path]::AltDirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase))
}

function Add-SizeToAncestors {
    param(
        [hashtable]$SizeMap,
        [hashtable]$FileCountMap,
        [string]$RootPath,
        [string]$DirectoryPath,
        [long]$Length
    )

    $d = $DirectoryPath
    $rootNorm = [System.IO.Path]::GetFullPath($RootPath).TrimEnd('\', '/')
    while ($null -ne $d -and $d.Length -ge $rootNorm.Length) {
        $dn = [System.IO.Path]::GetFullPath($d).TrimEnd('\', '/')
        if (-not (Test-PathIsUnderRoot -Path $dn -Root $rootNorm) -and -not ($dn.Equals($rootNorm, [StringComparison]::OrdinalIgnoreCase))) {
            break
        }
        if (-not $SizeMap.ContainsKey($dn)) {
            $SizeMap[$dn] = [long]0
            $FileCountMap[$dn] = 0
        }
        $SizeMap[$dn] = [long]$SizeMap[$dn] + $Length
        $FileCountMap[$dn] = [int]$FileCountMap[$dn] + 1
        $parent = [System.IO.Path]::GetDirectoryName($dn)
        if ([string]::IsNullOrEmpty($parent) -or $parent.Equals($dn, [StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $d = $parent
    }
}

function Invoke-EnumerateFilesForReport {
    param(
        [string]$RootPath
    )

    $sizeMap = @{}
    $fileCountMap = @{}
    $fileList = [System.Collections.Generic.List[object]]::new()

    $rootFull = [System.IO.Path]::GetFullPath($RootPath)
    if (-not (Test-Path -LiteralPath $rootFull)) {
        return [pscustomobject]@{
            SizeMap      = $sizeMap
            FileCountMap = $fileCountMap
            FileList     = $fileList
        }
    }

    $queue = New-Object System.Collections.Queue
    $queue.Enqueue($rootFull)
    while ($queue.Count -gt 0) {
        $dir = $queue.Dequeue()
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
                    $len = $fi.Length
                    $parent = $fi.DirectoryName
                    Add-SizeToAncestors -SizeMap $sizeMap -FileCountMap $fileCountMap -RootPath $rootFull `
                        -DirectoryPath $parent -Length $len
                    $fileList.Add([pscustomobject]@{
                            FullName = $filePath
                            Length   = $len
                        }) | Out-Null
                } catch {
                    continue
                }
            }
        } catch {
            continue
        }
    }

    return [pscustomobject]@{
        SizeMap      = $sizeMap
        FileCountMap = $fileCountMap
        FileList     = $fileList
    }
}

function Get-DirectorySizeBytes {
    param(
        [hashtable]$SizeMap,
        [string]$DirPath
    )

    $key = [System.IO.Path]::GetFullPath($DirPath).TrimEnd('\', '/')
    if ($SizeMap.ContainsKey($key)) {
        return [long]$SizeMap[$key]
    }
    return [long]0
}

function Get-DirectoryFileCount {
    param(
        [hashtable]$FileCountMap,
        [string]$DirPath
    )

    $key = [System.IO.Path]::GetFullPath($DirPath).TrimEnd('\', '/')
    if ($FileCountMap.ContainsKey($key)) {
        return [int]$FileCountMap[$key]
    }
    return 0
}

function Test-TestLookingName {
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

function Get-ArchiveHintDirectories {
    param(
        [string]$DataRootFull,
        [int]$OlderThanDays,
        [string[]]$RelativeSegments
    )

    $cutoff = [datetime]::UtcNow.AddDays(-$OlderThanDays)
    $out = [System.Collections.Generic.List[object]]::new()
    foreach ($rel in $RelativeSegments) {
        $base = Join-Path $DataRootFull $rel.Replace('/', [string][char][System.IO.Path]::DirectorySeparatorChar)
        if (-not (Test-Path -LiteralPath $base)) {
            continue
        }
        foreach ($di in Get-ChildItem -LiteralPath $base -Directory -Force -ErrorAction SilentlyContinue) {
            try {
                if (($di.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                    continue
                }
                if ($di.LastWriteTimeUtc -lt $cutoff) {
                    $out.Add([pscustomobject]@{
                            Path             = $di.FullName
                            RelativePath     = $rel + "/" + $di.Name
                            LastWriteTimeUtc = $di.LastWriteTimeUtc.ToString("yyyy-MM-ddTHH:mm:ssZ")
                        }) | Out-Null
                }
            } catch {
                continue
            }
        }
    }
    return $out
}

$repoRoot = Resolve-RepoRoot
$dataRootFull = Resolve-DataRootPath -DataRootParam $DataRoot -RepoRoot $repoRoot

if (-not (Test-Path -LiteralPath $dataRootFull)) {
    throw "DataRoot does not exist: $dataRootFull"
}

$enum = Invoke-EnumerateFilesForReport -RootPath $dataRootFull
$sizeMap = $enum.SizeMap
$fileCountMap = $enum.FileCountMap
$fileList = $enum.FileList

# Top-level directory sizes
$topLevel = [System.Collections.Generic.List[object]]::new()
if (Test-Path -LiteralPath $dataRootFull) {
    foreach ($child in Get-ChildItem -LiteralPath $dataRootFull -Directory -Force -ErrorAction SilentlyContinue) {
        if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            continue
        }
        $bytes = Get-DirectorySizeBytes -SizeMap $sizeMap -DirPath $child.FullName
        $fc = Get-DirectoryFileCount -FileCountMap $fileCountMap -DirPath $child.FullName
        $topLevel.Add([pscustomobject]@{
                Name      = $child.Name
                Path      = $child.FullName
                Bytes     = $bytes
                Megabytes = [math]::Round($bytes / 1MB, 3)
                FileCount = $fc
            }) | Out-Null
    }
}

# Workspace states
$workspaceStates = [System.Collections.Generic.List[object]]::new()
$wsRoot = Join-Path $dataRootFull "workspaces"
foreach ($state in @("active", "completed", "rejected")) {
    $p = Join-Path $wsRoot $state
    if (Test-Path -LiteralPath $p) {
        $bytes = Get-DirectorySizeBytes -SizeMap $sizeMap -DirPath $p
        $fc = Get-DirectoryFileCount -FileCountMap $fileCountMap -DirPath $p
        $workspaceStates.Add([pscustomobject]@{
                State     = $state
                Path      = $p
                Bytes     = $bytes
                Megabytes = [math]::Round($bytes / 1MB, 3)
                FileCount = $fc
            }) | Out-Null
    }
}

# Largest N directories under data root (exclude root itself from ranking list; include subdirs)
$dirRanking = [System.Collections.Generic.List[object]]::new()
foreach ($kv in $sizeMap.GetEnumerator()) {
    $dn = $kv.Key
    if ($dn.Equals($dataRootFull.TrimEnd('\', '/'), [StringComparison]::OrdinalIgnoreCase)) {
        continue
    }
    $bytes = [long]$kv.Value
    $fc = if ($fileCountMap.ContainsKey($dn)) { [int]$fileCountMap[$dn] } else { 0 }
    $rel = if ($dn.StartsWith($dataRootFull, [StringComparison]::OrdinalIgnoreCase)) {
        $dn.Substring($dataRootFull.Length).TrimStart('\', '/')
    } else { $dn }
    $dirRanking.Add([pscustomobject]@{
            Path          = $dn
            RelativePath  = $rel
            Bytes         = $bytes
            Megabytes     = [math]::Round($bytes / 1MB, 3)
            FileCount     = $fc
        }) | Out-Null
}
$largestDirs = $dirRanking | Sort-Object Bytes -Descending | Select-Object -First $Top

# Test-looking directories (name match)
$testLooking = [System.Collections.Generic.List[object]]::new()
foreach ($kv in $sizeMap.GetEnumerator()) {
    $dn = $kv.Key
    $leaf = [System.IO.Path]::GetFileName($dn.TrimEnd('\', '/'))
    if (Test-TestLookingName -Name $leaf) {
        $bytes = [long]$kv.Value
        $testLooking.Add([pscustomobject]@{
                Path         = $dn
                RelativePath = if ($dn.StartsWith($dataRootFull, [StringComparison]::OrdinalIgnoreCase)) {
                    $dn.Substring($dataRootFull.Length).TrimStart('\', '/')
                } else { $dn }
                Bytes        = $bytes
                Megabytes    = [math]::Round($bytes / 1MB, 3)
            }) | Out-Null
    }
}

# Archive hints (report only)
$hintSegments = @(
    "workspaces/completed",
    "workspaces/rejected",
    "generated_tool_dry_runs",
    "automation_lab",
    "tool_builds"
)
$archiveHints = Get-ArchiveHintDirectories -DataRootFull $dataRootFull -OlderThanDays $OlderThanDays -RelativeSegments $hintSegments

$largestFiles = $null
if ($IncludeFiles) {
    $largestFiles = @($fileList | Sort-Object Length -Descending | Select-Object -First $Top | ForEach-Object {
            [pscustomobject]@{
                Path        = $_.FullName
                Bytes       = $_.Length
                Megabytes   = [math]::Round($_.Length / 1MB, 3)
            }
        })
}

$report = [ordered]@{
    data_root              = $dataRootFull
    repo_root              = $repoRoot
    generated_at_utc       = [datetime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    older_than_days        = $OlderThanDays
    top_level_directories  = @($topLevel | Sort-Object Name)
    workspace_states       = @($workspaceStates)
    largest_directories    = @($largestDirs)
    test_looking_directories = @($testLooking | Sort-Object Path)
    archive_hints          = @($archiveHints | Sort-Object Path)
}
if ($null -ne $largestFiles) {
    $report["largest_files"] = $largestFiles
}

if ($Json) {
    $report | ConvertTo-Json -Depth 8
    exit 0
}

# Human-readable
Write-Output "Mini-Jarvis data storage report (read-only)"
Write-Output "DataRoot: $dataRootFull"
Write-Output "Generated (UTC): $($report['generated_at_utc'])"
Write-Output ""

Write-Output "=== Top-level directories under DataRoot ==="
foreach ($row in $report['top_level_directories']) {
    Write-Output ("{0,-28} {1,14} MB  files={2,8}  {3}" -f $row.Name, $row.Megabytes, $row.FileCount, $row.Path)
}
Write-Output ""

Write-Output "=== Workspace state sizes ==="
if ($report['workspace_states'].Count -eq 0) {
    Write-Output "(no workspaces/active|completed|rejected present)"
} else {
    foreach ($row in $report['workspace_states']) {
        Write-Output ("{0,-12} {1,14} MB  files={2,8}  {3}" -f $row.State, $row.Megabytes, $row.FileCount, $row.Path)
    }
}
Write-Output ""

Write-Output "=== Largest $($Top) directories (recursive size under DataRoot) ==="
foreach ($row in $report['largest_directories']) {
    Write-Output ("{0,12} MB  files={1,8}  {2}" -f $row.Megabytes, $row.FileCount, $row.RelativePath)
}
Write-Output ""

Write-Output "=== Test-looking directory names (report only) ==="
if ($report['test_looking_directories'].Count -eq 0) {
    Write-Output "(none matched)"
} else {
    foreach ($row in $report['test_looking_directories']) {
        Write-Output ("{0,12} MB  {1}" -f $row.Megabytes, $row.RelativePath)
    }
}
Write-Output ""

Write-Output "=== Archive hints (older than $OlderThanDays days, report only) ==="
if ($report['archive_hints'].Count -eq 0) {
    Write-Output "(none)"
} else {
    foreach ($row in $report['archive_hints']) {
        Write-Output ("{0}  |  {1}" -f $row.LastWriteTimeUtc, $row.RelativePath)
    }
}
Write-Output ""

if ($IncludeFiles) {
    Write-Output "=== Largest $($Top) files ==="
    foreach ($row in $report['largest_files']) {
        Write-Output ("{0,12} MB  {1}" -f $row.Megabytes, $row.Path)
    }
}

exit 0
