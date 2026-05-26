# Launch the Prompt Optimizer desktop app.
# For the correct Windows taskbar icon, this prefers the custom
# ".venv\Scripts\Prompt Optimizer.exe" launcher created by
# scripts\build_windows_launcher.ps1.
#
# Run:  powershell -ExecutionPolicy Bypass -File scripts\run_desktop.ps1

$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $proj ".venv\Scripts\Prompt Optimizer.exe"

if (-not (Test-Path $launcher)) {
    & (Join-Path $PSScriptRoot "build_windows_launcher.ps1")
}

if (Test-Path $launcher) {
    & $launcher (Join-Path $proj "desktop.py")
} else {
    & (Join-Path $proj ".venv\Scripts\python.exe") (Join-Path $proj "desktop.py")
}
