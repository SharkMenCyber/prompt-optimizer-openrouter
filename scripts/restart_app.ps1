param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

Write-Host "Restarting Prompt Optimizer on port $Port..." -ForegroundColor Cyan

$connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($connection in $connections) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($connection.OwningProcess)" -ErrorAction SilentlyContinue
    $processInfo = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
    $isPromptOptimizer = $false
    if ($process -and $process.CommandLine -like "*uvicorn*app.main:app*") {
        $isPromptOptimizer = $true
    } elseif ($processInfo -and $processInfo.ProcessName -like "python*") {
        $isPromptOptimizer = $true
    }

    if ($isPromptOptimizer) {
        Write-Host "Stopping existing app process $($connection.OwningProcess)..."
        try {
            Stop-Process -Id $connection.OwningProcess -Force -ErrorAction Stop
        } catch {
            Write-Host "Could not stop process $($connection.OwningProcess): $($_.Exception.Message)" -ForegroundColor Yellow
            Write-Host "Use another port, for example: .\scripts\restart_app.ps1 -Port 8001"
            exit 1
        }
    } elseif ($connection.OwningProcess) {
        Write-Host "Port $Port is used by another process: $($connection.OwningProcess)" -ForegroundColor Yellow
        Write-Host "Use a different port, for example: .\scripts\restart_app.ps1 -Port 8001"
        exit 1
    }
}

Start-Sleep -Seconds 1

Start-Process `
    -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port" `
    -WorkingDirectory (Get-Location).Path `
    -WindowStyle Hidden

Start-Sleep -Seconds 4

$health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health"
Write-Host "Backend: $($health.status)" -ForegroundColor Green
Write-Host "OpenRouter configured: $($health.openrouter_configured)"
Write-Host "Selected model: $($health.selected_model)"
Write-Host "Open: http://127.0.0.1:$Port"
