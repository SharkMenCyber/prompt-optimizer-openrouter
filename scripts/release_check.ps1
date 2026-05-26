param(
    [int]$Port = 8050
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

function Run-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "== $Name ==" -ForegroundColor Cyan
    & $Command
    Write-Host "OK: $Name" -ForegroundColor Green
}

function Run-OptionalStep {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "== $Name ==" -ForegroundColor Cyan
    try {
        & $Command
        Write-Host "OK: $Name" -ForegroundColor Green
    }
    catch {
        Write-Host "Skipped or failed optional check: $Name" -ForegroundColor Yellow
        Write-Host $_.Exception.Message -ForegroundColor Yellow
    }
}

Push-Location $root
try {
    Write-Host "Hermes Prompt Optimizer release check" -ForegroundColor Cyan
    Write-Host "Project: $root"
    Write-Host "This script does not print .env values or API keys."

    Run-Step "Python compile check" {
        & $python -m compileall app
    }

    Run-Step "Frontend JavaScript syntax" {
        & node --check static\app.js
    }

    Run-Step "Updates JSON syntax" {
        & $python -m json.tool docs\updates.json | Out-Null
    }

    Run-OptionalStep "Running app health check" {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 8
        Write-Host "Version: $($health.app_version)"
        Write-Host "Status: $($health.status)"
        Write-Host "Database: $($health.database_backend)"
        Write-Host "OpenRouter configured: $($health.openrouter_configured)"
        Write-Host "Hermes installed: $($health.hermes_installed)"
    }

    Write-Host ""
    Write-Host "Release check complete." -ForegroundColor Green
    Write-Host "If the health check was skipped, start the app with:"
    Write-Host ".\scripts\start_supervised.ps1 -Port $Port"
}
finally {
    Pop-Location
}
