param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,

    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [Parameter(Mandatory = $true)]
    [int]$Port,

    [Parameter(Mandatory = $true)]
    [string]$WorkDir
)

$ErrorActionPreference = "Stop"

Start-Sleep -Seconds 2

$logsDir = Join-Path $WorkDir "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

$restartLog = Join-Path $logsDir "restart-$Port.log"
$stdoutLog = Join-Path $logsDir "restart-$Port.out.log"
$stderrLog = Join-Path $logsDir "restart-$Port.err.log"

try {
    "[$(Get-Date -Format o)] Starting server on $HostName`:$Port with $PythonExe" | Add-Content -LiteralPath $restartLog
    Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", $HostName, "--port", "$Port") `
        -WorkingDirectory $WorkDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog
    "[$(Get-Date -Format o)] Start-Process completed." | Add-Content -LiteralPath $restartLog
} catch {
    "[$(Get-Date -Format o)] Failed: $($_.Exception.Message)" | Add-Content -LiteralPath $restartLog
    exit 1
}

