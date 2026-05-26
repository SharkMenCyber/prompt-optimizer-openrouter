param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$healthUrl = "http://127.0.0.1:$Port/api/health"
$modelsUrl = "http://127.0.0.1:$Port/api/models"
$hermesUrl = "http://127.0.0.1:$Port/api/hermes/status"

Write-Host "Checking Prompt Optimizer..." -ForegroundColor Cyan

try {
    $health = Invoke-RestMethod -Uri $healthUrl
    Write-Host "Backend: $($health.status)" -ForegroundColor Green
    Write-Host "OpenRouter configured: $($health.openrouter_configured)"
    Write-Host "Default model setting: $($health.default_model)"
    Write-Host "Selected model: $($health.selected_model)"
    Write-Host "Database: $($health.database_path)"

    if ($health.openrouter_configured) {
        $models = Invoke-RestMethod -Uri $modelsUrl
        Write-Host "OpenRouter text models found: $($models.models.Count)" -ForegroundColor Green
    } else {
        Write-Host "OpenRouter is not configured. Add OPENROUTER_API_KEY to .env." -ForegroundColor Yellow
    }

    $hermes = Invoke-RestMethod -Uri $hermesUrl
    Write-Host "Hermes installed: $($hermes.installed)"
    Write-Host "Hermes configured: $($hermes.configured)"
    Write-Host "Hermes message: $($hermes.message)"
} catch {
    Write-Host "Status check failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Try running: .\scripts\run_dev.ps1"
    exit 1
}
