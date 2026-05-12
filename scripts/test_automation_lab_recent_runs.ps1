# Automation lab recent-runs dashboard route test.

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

function New-SyntheticIndexRun {
    param(
        [string]$AutomationRoot,
        [string]$RequestId,
        [string]$CreatedAt
    )

    $runDir = Join-Path $AutomationRoot $RequestId
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null
    $payload = [ordered]@{
        schema_version = "automation-lab-review-artifact-index.v1"
        request_id = $RequestId
        created_at = $CreatedAt
        proposal_kind = "review_only"
        primary_capability_outcome = "reuse_existing"
        local_model = [ordered]@{
            enabled = $false
            validation_state = "not_requested"
        }
        fixture_lookup = [ordered]@{
            enabled = $false
            source = $null
            advisory_only = $true
        }
        registry_capability_lookup = [ordered]@{
            enabled = $false
            registry_read = $false
            tools_inspected_count = $null
            primary_outcome_source = $null
            evidence_sources = $null
        }
        authority = $false
        authority_boundary = [ordered]@{
            proposal_only = $true
            tools_executed = $false
            sandbox_worker_invoked = $false
            registry_modified = $false
            generated_tool_execution_allowed = $false
        }
        artifacts = @(
            [ordered]@{
                filename = "INDEX.json"
                kind = "review_artifact_index"
                format = "json"
                required = $true
                authority = $false
            }
        )
    }
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDir "INDEX.json") -Encoding ASCII
    return $runDir
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
$automationRoot = Join-Path $RepoRoot "data\automation_lab"
$server = $null
$createdDirs = @()

try {
    Assert-NoAutomationLabAuthoritySurface -RepoRoot $RepoRoot

    $server = Start-Process `
        -FilePath $py `
        -ArgumentList @("integrations\local_dashboard\serve_dashboard.py", "--listen", "127.0.0.1", "--port", "$port") `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -PassThru
    Wait-ForDashboard -BaseUrl $baseUrl

    $generated = Invoke-RestMethod `
        -Method Post `
        -Uri "$baseUrl/api/automation-lab/generate" `
        -ContentType "application/json" `
        -Body (@{ message = "Create a tool to list new Navidrome releases"; use_fixture = $true } | ConvertTo-Json)
    $generatedId = [string]$generated.result.request_id
    $createdDirs += [string]$generated.result.output_dir_abs

    $syntheticId = "auto_recent_index_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
    $syntheticDir = New-SyntheticIndexRun `
        -AutomationRoot $automationRoot `
        -RequestId $syntheticId `
        -CreatedAt "2099-01-01T00:00:00Z"
    $createdDirs += $syntheticDir

    $missingId = "auto_recent_missing_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
    $missingDir = Join-Path $automationRoot $missingId
    New-Item -ItemType Directory -Path $missingDir -Force | Out-Null
    $createdDirs += $missingDir

    $malformedId = "auto_recent_bad_$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
    $malformedDir = Join-Path $automationRoot $malformedId
    New-Item -ItemType Directory -Path $malformedDir -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $malformedDir "INDEX.json") -Value "{bad json" -Encoding UTF8
    $createdDirs += $malformedDir

    $recent = Invoke-RestMethod -Method Get -Uri "$baseUrl/api/automation-lab/recent"
    Assert-True ($recent.authority -eq $false) "Recent-runs response must not claim authority."

    $runs = @($recent.runs)
    $generatedRun = @($runs | Where-Object { $_.request_id -eq $generatedId })[0]
    Assert-True ($null -ne $generatedRun) "Recent-runs route did not list generated automation lab run."
    Assert-True ($generatedRun.authority -eq $false) "Generated run summary must be non-authority."
    Assert-True ($generatedRun.fixture_lookup.enabled -eq $true) "Generated run summary should include fixture lookup metadata."
    Assert-True ($generatedRun.local_model.enabled -eq $false) "Generated dashboard run should not use local model."
    Assert-True ($generatedRun.artifact_count -ge 5) "Generated run summary should include artifact count from INDEX.json."

    $syntheticRun = @($runs | Where-Object { $_.request_id -eq $syntheticId })[0]
    Assert-True ($null -ne $syntheticRun) "Recent-runs route should list an INDEX-only synthetic run."
    Assert-True ($syntheticRun.created_at -eq "2099-01-01T00:00:00Z") "Synthetic run created_at should come from INDEX.json."
    Assert-True ($syntheticRun.proposal_kind -eq "review_only") "Synthetic proposal_kind should come from INDEX.json."
    Assert-True ($syntheticRun.artifact_count -eq 1) "Synthetic artifact count should come from INDEX.json only."

    $skipped = @($recent.skipped)
    Assert-True (@($skipped | Where-Object { $_.request_id -eq $missingId -and $_.reason -eq "missing_index" }).Count -eq 1) "Missing INDEX run should be safely reported as skipped."
    Assert-True (@($skipped | Where-Object { $_.request_id -eq $malformedId -and $_.reason -eq "malformed_index" }).Count -eq 1) "Malformed INDEX run should be safely reported as skipped."

    $null = Invoke-ExpectedHttpFailure `
        -Method Get `
        -Uri "$baseUrl/api/automation-lab/recent?path=..\README.md" `
        -AllowedStatus @(400)

    Write-Host "OK: local dashboard recent automation lab runs are index-derived and review-only."
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
    }
    foreach ($dir in $createdDirs) {
        Remove-LabOutput -RepoRoot $RepoRoot -OutputDir $dir
    }
}
