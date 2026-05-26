param(
    [int]$Port = 8050
)

$ErrorActionPreference = "Stop"

if (!(Test-Path ".venv")) {
    python -m venv .venv
}

New-Item -ItemType Directory -Force -Path logs | Out-Null
$supervisorLog = Join-Path (Resolve-Path logs).Path "supervisor-launch-$Port.log"

Start-Process `
    -FilePath "powershell" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ".\scripts\supervisor.ps1", "-Port", "$Port") `
    -WorkingDirectory (Get-Location).Path `
    -WindowStyle Hidden `
    -RedirectStandardOutput $supervisorLog `
    -RedirectStandardError (Join-Path (Resolve-Path logs).Path "supervisor-launch-$Port.err.log")

# Poll the health endpoint instead of a single fixed-delay request, so a slow
# first start (cold venv, model catalog fetch) doesn't crash the launcher.
$health = $null
$deadline = (Get-Date).AddSeconds(40)
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}

if ($null -eq $health) {
    Write-Host "Prompt Optimizer did not become healthy on port $Port within 40s." -ForegroundColor Red
    Write-Host "Check logs\supervised-$Port.err.log for details." -ForegroundColor Yellow
    exit 1
}

Write-Host "Prompt Optimizer is running at http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "Version: $($health.app_version)"
Write-Host "Selected model: $($health.selected_model)"

