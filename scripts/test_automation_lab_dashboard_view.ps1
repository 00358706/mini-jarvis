# Automation lab local dashboard view test.

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

function Get-FreePort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse("127.0.0.1"), 0)
    $listener.Start()
    try {
        return $listener.LocalEndpoint.Port
    } finally {
        $listener.Stop()
    }
}

function Wait-ForDashboard {
    param([string]$BaseUrl)

    for ($i = 0; $i -lt 40; $i++) {
        try {
            $resp = Invoke-WebRequest -UseBasicParsing -Method Get -Uri "$BaseUrl/" -TimeoutSec 2
            if ($resp.StatusCode -eq 200) { return }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    throw "Dashboard server did not become ready at $BaseUrl"
}

function Invoke-ExpectedHttpFailure {
    param(
        [string]$Method,
        [string]$Uri,
        [int[]]$AllowedStatus
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $null = Invoke-WebRequest -UseBasicParsing -Method $Method -Uri $Uri -TimeoutSec 10
        $statusCode = 200
        $body = ""
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = [System.IO.StreamReader]::new($stream)
        $body = $reader.ReadToEnd()
        $reader.Dispose()
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    Assert-True ($AllowedStatus -contains $statusCode) "Expected $Uri to fail with one of $AllowedStatus, got $statusCode. Body: $body"
    return @{ StatusCode = $statusCode; Body = $body }
}

function Get-DirectorySnapshot {
    param([string]$Directory)

    $snapshot = @{}
    foreach ($file in Get-ChildItem -LiteralPath $Directory -File | Sort-Object Name) {
        $snapshot[$file.Name] = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
    }
    return $snapshot
}

function Assert-SnapshotUnchanged {
    param(
        [string]$Directory,
        [hashtable]$Before
    )

    $after = Get-DirectorySnapshot -Directory $Directory
    $beforeNames = @($Before.Keys | Sort-Object)
    $afterNames = @($after.Keys | Sort-Object)
    $diff = @(Compare-Object -ReferenceObject $beforeNames -DifferenceObject $afterNames)
    Assert-True ($diff.Count -eq 0) "Dashboard artifact reads created, removed, or renamed artifacts."
    foreach ($name in $beforeNames) {
        Assert-True ($after[$name] -eq $Before[$name]) "Dashboard artifact read modified artifact: $name"
    }
}

function Assert-NoAutomationLabAuthoritySurface {
    param([string]$RepoRoot)

    $serverSource = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "integrations\local_dashboard\serve_dashboard.py")
    $appSource = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "integrations\local_dashboard\app.js")
    $htmlSource = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "integrations\local_dashboard\index.html")

    $forbiddenRoutePattern = '/api/automation-lab/[^''"`\s]*(approve|execute|install)'
    Assert-True (-not ($serverSource -match $forbiddenRoutePattern)) "Automation lab server routes must not add approve/execute/install paths."
    Assert-True (-not ($appSource -match $forbiddenRoutePattern)) "Automation lab UI calls must not add approve/execute/install paths."
    Assert-True (-not ($htmlSource -match 'btnLab(Approve|Execute|Install)')) "Automation lab UI must not add approve/execute/install buttons."
}

function Remove-LabOutput {
    param([string]$RepoRoot, [string]$OutputDir)

    if (-not $OutputDir -or -not (Test-Path -LiteralPath $OutputDir)) {
        return
    }
    $automationRoot = Join-Path $RepoRoot "data\automation_lab"
    $resolvedOutput = (Resolve-Path -LiteralPath $OutputDir).Path
    $resolvedRoot = (Resolve-Path -LiteralPath $automationRoot).Path
    if ($resolvedOutput.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $OutputDir -Recurse -Force
    }
}

$RepoRoot = Resolve-RepoRoot
Set-Location $RepoRoot

$py = Select-Python -RepoRoot $RepoRoot
$port = Get-FreePort
$baseUrl = "http://127.0.0.1:$port"
$server = $null
$outputDir = $null

try {
    Assert-NoAutomationLabAuthoritySurface -RepoRoot $RepoRoot

    $server = Start-Process `
        -FilePath $py `
        -ArgumentList @("integrations\local_dashboard\serve_dashboard.py", "--listen", "127.0.0.1", "--port", "$port") `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -PassThru
    Wait-ForDashboard -BaseUrl $baseUrl

    $generateBody = @{
        message = "Search repo for automation lab review artifacts"
        use_fixture = $true
    } | ConvertTo-Json
    $generated = Invoke-RestMethod `
        -Method Post `
        -Uri "$baseUrl/api/automation-lab/generate" `
        -ContentType "application/json" `
        -Body $generateBody

    Assert-True ($generated.authority -eq $false) "Dashboard generate response must not claim authority."
    Assert-True ($generated.result.status -eq "created") "Dashboard generate did not create a run."
    Assert-True ($generated.result.authority_boundary.tools_executed -eq $false) "Generate claims tools executed."
    Assert-True ($generated.result.authority_boundary.sandbox_worker_invoked -eq $false) "Generate claims sandbox worker invoked."
    Assert-True ($generated.result.authority_boundary.registry_modified -eq $false) "Generate claims registry modified."
    Assert-True ($generated.result.authority_boundary.generated_tool_execution_allowed -eq $false) "Generate claims generated tool execution allowed."

    $requestId = [string]$generated.result.request_id
    $outputDir = [string]$generated.result.output_dir_abs
    $snapshot = Get-DirectorySnapshot -Directory $outputDir

    $index = Invoke-RestMethod -Method Get -Uri "$baseUrl/api/automation-lab/$requestId/index"
    Assert-True ($index.request_id -eq $requestId) "Dashboard index route returned wrong request id."
    Assert-True ($index.fixture_lookup.enabled -eq $true) "Dashboard fixture-enabled run should record fixture lookup metadata."
    Assert-True ($index.authority -eq $false) "INDEX.json route must return review evidence only."

    $summary = Invoke-WebRequest -UseBasicParsing -Method Get -Uri "$baseUrl/api/automation-lab/$requestId/summary"
    Assert-True ($summary.Content -match "Automation Lab Review Summary") "Dashboard summary route did not return review summary."
    Assert-True ($summary.Content -match "all_artifacts_authority_false:\s*true") "Dashboard summary should report non-authority artifacts."

    $artifact = Invoke-RestMethod -Method Get -Uri "$baseUrl/api/automation-lab/$requestId/artifacts/INDEX.json"
    Assert-True ($artifact.filename -eq "INDEX.json") "Dashboard artifact route returned wrong filename."
    Assert-True ($artifact.authority -eq $false) "Artifact response must not claim authority."
    Assert-True ($artifact.content -match "automation-lab-review-artifact-index.v1") "Artifact content should include INDEX.json content."
    Assert-SnapshotUnchanged -Directory $outputDir -Before $snapshot

    $null = Invoke-ExpectedHttpFailure `
        -Method Get `
        -Uri "$baseUrl/api/automation-lab/$requestId/artifacts/README.md" `
        -AllowedStatus @(403)

    $null = Invoke-ExpectedHttpFailure `
        -Method Get `
        -Uri "$baseUrl/api/automation-lab/$requestId/artifacts/..%2F..%2FREADME.md" `
        -AllowedStatus @(400, 403, 404)
    Assert-SnapshotUnchanged -Directory $outputDir -Before $snapshot

    Write-Host "OK: local dashboard automation lab view is narrow, indexed, and review-only."
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
    }
    if ($outputDir) {
        Remove-LabOutput -RepoRoot $RepoRoot -OutputDir $outputDir
    }
}
