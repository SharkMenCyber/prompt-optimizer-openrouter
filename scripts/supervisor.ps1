param(
    [int]$Port = 8050
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path ".").Path
$python = (Resolve-Path ".\.venv\Scripts\python.exe").Path
$dataDir = Join-Path $root "data"
$logsDir = Join-Path $root "logs"
$requestFile = Join-Path $dataDir "restart_request.json"

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

$lastRequestId = $null
$appProcess = $null

# Seed from any existing restart request so a stale file left over from a
# previous session does not trigger a spurious restart on startup.
if (Test-Path $requestFile) {
    try {
        $lastRequestId = (Get-Content -Raw -LiteralPath $requestFile | ConvertFrom-Json).request_id
    } catch {
        $lastRequestId = $null
    }
}

function Start-App {
    param([int]$AppPort)

    $outLog = Join-Path $logsDir "supervised-$AppPort.out.log"
    $errLog = Join-Path $logsDir "supervised-$AppPort.err.log"
    $supervisorLog = Join-Path $logsDir "supervisor-$AppPort.log"

    "[$(Get-Date -Format o)] Starting app on http://127.0.0.1:$AppPort" | Add-Content -LiteralPath $supervisorLog
    return Start-Process `
        -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$AppPort") `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -PassThru
}

function Stop-App {
    param($Process)

    if ($null -ne $Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
}

$appProcess = Start-App -AppPort $Port
Write-Host "Prompt Optimizer supervised at http://127.0.0.1:$Port" -ForegroundColor Green

while ($true) {
    Start-Sleep -Seconds 1

    if ($null -eq $appProcess -or $appProcess.HasExited) {
        $appProcess = Start-App -AppPort $Port
        continue
    }

    if (Test-Path $requestFile) {
        try {
            $request = Get-Content -Raw -LiteralPath $requestFile | ConvertFrom-Json
            if ($request.request_id -and $request.request_id -ne $lastRequestId) {
                $lastRequestId = $request.request_id
                Write-Host "Restart request received: $lastRequestId" -ForegroundColor Cyan
                Stop-App -Process $appProcess
                $appProcess = Start-App -AppPort $Port
            }
        } catch {
            Write-Host "Could not read restart request: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

