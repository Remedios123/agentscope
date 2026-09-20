[CmdletBinding()]
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[AgentScope] $Message" -ForegroundColor Cyan
}

function Test-HttpEndpoint {
    param(
        [string]$Uri,
        [hashtable]$Headers = @{}
    )

    try {
        $response = Invoke-WebRequest `
            -Uri $Uri `
            -Headers $Headers `
            -UseBasicParsing `
            -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

function Test-PortInUse {
    param([int]$Port)

    return $null -ne (Get-NetTCPConnection `
        -State Listen `
        -LocalPort $Port `
        -ErrorAction SilentlyContinue `
        | Select-Object -First 1)
}

function ConvertTo-SingleQuotedLiteral {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Start-ServiceWindow {
    param(
        [string]$Title,
        [string]$WorkingDirectory,
        [string]$Executable,
        [string[]]$Arguments,
        [hashtable]$Environment = @{},
        [string]$LogPath
    )

    $quotedTitle = ConvertTo-SingleQuotedLiteral $Title
    $quotedDirectory = ConvertTo-SingleQuotedLiteral $WorkingDirectory
    $quotedExecutable = ConvertTo-SingleQuotedLiteral $Executable
    $quotedLogPath = ConvertTo-SingleQuotedLiteral $LogPath
    $quotedArguments = @($Arguments | ForEach-Object {
        ConvertTo-SingleQuotedLiteral $_
    }) -join " "
    $environmentLines = @($Environment.GetEnumerator() | Sort-Object Key | ForEach-Object {
        $quotedValue = ConvertTo-SingleQuotedLiteral ([string]$_.Value)
        "`$env:$($_.Key) = $quotedValue"
    }) -join "`n"

    $command = @"
`$Host.UI.RawUI.WindowTitle = $quotedTitle
Set-Location -LiteralPath $quotedDirectory
$environmentLines
Write-Host 'Starting $Title...' -ForegroundColor Cyan
& $quotedExecutable $quotedArguments 2>&1 | Tee-Object -FilePath $quotedLogPath -Append
`$serviceExitCode = `$LASTEXITCODE
if (`$serviceExitCode -ne 0) {
    Write-Host ''
    Write-Host '$Title exited with an error. Keep this window open to inspect the log.' -ForegroundColor Red
}
"@

    $encodedCommand = [Convert]::ToBase64String(
        [Text.Encoding]::Unicode.GetBytes($command)
    )

    Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoLogo",
            "-NoExit",
            "-ExecutionPolicy", "Bypass",
            "-EncodedCommand", $encodedCommand
        ) `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Normal | Out-Null
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$agentServiceDirectory = Join-Path $repoRoot "examples\agent_service"
$agentServiceEntry = Join-Path $agentServiceDirectory "main.py"
$webUiDirectory = Join-Path $repoRoot "examples\web_ui"
$webUiNodeModules = Join-Path $webUiDirectory "node_modules"
$logDirectory = Join-Path $repoRoot "logs"

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python environment is missing: $pythonPath`nCreate .venv and install the project dependencies first."
}

if (-not (Test-Path -LiteralPath $agentServiceEntry -PathType Leaf)) {
    throw "Agent service entry file is missing: $agentServiceEntry"
}

if (-not (Test-Path -LiteralPath $webUiNodeModules -PathType Container)) {
    throw "Web UI dependencies are missing. Run: cd examples\web_ui; corepack pnpm install"
}

$corepackCommand = Get-Command "corepack.cmd" -ErrorAction SilentlyContinue
if ($null -eq $corepackCommand) {
    $corepackCommand = Get-Command "corepack" -ErrorAction SilentlyContinue
}
if ($null -eq $corepackCommand) {
    throw "Corepack is missing. Install Node.js with Corepack support first."
}
$corepackPath = $corepackCommand.Source

Write-Step "Preparing local startup..."

$candidateWebBackendPorts = 3000..3010
$webBackendPort = $null
$firstFreeWebBackendPort = $null

foreach ($candidatePort in $candidateWebBackendPorts) {
    if (Test-PortInUse -Port $candidatePort) {
        $candidateUri = "http://127.0.0.1:$candidatePort/api/health"
        if (Test-HttpEndpoint -Uri $candidateUri) {
            $webBackendPort = $candidatePort
            break
        }
    }
    elseif ($null -eq $firstFreeWebBackendPort) {
        $firstFreeWebBackendPort = $candidatePort
    }
}

if ($null -eq $webBackendPort) {
    $webBackendPort = $firstFreeWebBackendPort
}

if ($null -eq $webBackendPort) {
    throw "No free Web backend port was found in the range 3000-3010."
}

if ($webBackendPort -ne 3000) {
    Write-Host "  Port 3000 is unavailable; Web backend will use port $webBackendPort." -ForegroundColor Yellow
}

$services = @(
    [PSCustomObject]@{
        Name = "Agent API"
        Port = 8000
        Uri = "http://127.0.0.1:8000/health"
        Headers = @{ "X-User-ID" = "local-user" }
        WorkingDirectory = $agentServiceDirectory
        Executable = $pythonPath
        Arguments = @($agentServiceEntry)
        Environment = @{}
        LogPath = Join-Path $logDirectory "agent-api.log"
    },
    [PSCustomObject]@{
        Name = "Web backend"
        Port = $webBackendPort
        Uri = "http://127.0.0.1:$webBackendPort/api/health"
        Headers = @{}
        WorkingDirectory = $webUiDirectory
        Executable = $corepackPath
        Arguments = @("pnpm", "--filter", "backend", "dev")
        Environment = @{ "PORT" = "$webBackendPort" }
        LogPath = Join-Path $logDirectory "web-backend.log"
    },
    [PSCustomObject]@{
        Name = "Web frontend"
        Port = 5173
        Uri = "http://localhost:5173/"
        Headers = @{}
        WorkingDirectory = $webUiDirectory
        Executable = $corepackPath
        Arguments = @("pnpm", "--filter", "frontend", "dev")
        Environment = @{
            "AGENTSCOPE_WEB_BACKEND_URL" = "http://localhost:$webBackendPort"
        }
        LogPath = Join-Path $logDirectory "web-frontend.log"
    }
)

Write-Step "Checking local services..."
foreach ($service in $services) {
    if (Test-HttpEndpoint -Uri $service.Uri -Headers $service.Headers) {
        Write-Host "  $($service.Name) is already running; reusing it." -ForegroundColor DarkGray
        continue
    }

    if (Test-PortInUse -Port $service.Port) {
        throw "Port $($service.Port) is already occupied, but it is not a healthy $($service.Name) service. Stop the process using that port and try again."
    }

    Write-Step "Starting $($service.Name) on port $($service.Port)..."
    Start-ServiceWindow `
        -Title "AgentScope - $($service.Name)" `
        -WorkingDirectory $service.WorkingDirectory `
        -Executable $service.Executable `
        -Arguments $service.Arguments `
        -Environment $service.Environment `
        -LogPath $service.LogPath
}

Write-Step "Waiting for all services to become ready..."
$deadline = (Get-Date).AddSeconds(60)
do {
    $pendingServices = @($services | Where-Object {
        -not (Test-HttpEndpoint -Uri $_.Uri -Headers $_.Headers)
    })

    if ($pendingServices.Count -eq 0) {
        break
    }

    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)

if ($pendingServices.Count -gt 0) {
    $pendingNames = ($pendingServices | ForEach-Object { $_.Name }) -join ", "
    throw "Startup timed out while waiting for: $pendingNames. Check the corresponding service window for details."
}

Write-Host ""
Write-Host "AgentScope is ready." -ForegroundColor Green
Write-Host "  Web UI:    http://localhost:5173"
Write-Host "  Agent API: http://127.0.0.1:8000"
Write-Host "  Web API:   http://127.0.0.1:$webBackendPort"
Write-Host ""
Write-Host "Use Ctrl+C in a service window to stop that service." -ForegroundColor DarkGray

if (-not $NoBrowser) {
    Start-Process "http://localhost:5173"
}
