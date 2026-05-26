# Creates a custom Windows launcher executable with the Prompt Optimizer icon.
#
# Why this exists:
# Windows often shows the icon embedded in the running .exe on the taskbar.
# If we launch with pythonw.exe, the taskbar can show Python even when the
# desktop shortcut has the correct icon. This script copies pythonw.exe to
# "Prompt Optimizer.exe" inside the venv and embeds assets\skull.ico into it.
#
# Run: powershell -ExecutionPolicy Bypass -File scripts\build_windows_launcher.ps1

$ErrorActionPreference = "Stop"

$proj = Split-Path -Parent $PSScriptRoot
$source = Join-Path $proj ".venv\Scripts\pythonw.exe"
$launcher = Join-Path $proj ".venv\Scripts\Prompt Optimizer.exe"
$icon = Join-Path $proj "assets\skull.ico"
$tools = Join-Path $env:LOCALAPPDATA "PromptOptimizerTools\rcedit"
$rceditEntry = Join-Path $tools "node_modules\rcedit\lib\index.js"

if (-not (Test-Path $source)) {
    throw "pythonw.exe not found in .venv. Create the virtual environment first."
}
if (-not (Test-Path $icon)) {
    throw "Icon missing. Run: .\.venv\Scripts\python.exe scripts\make_icon.py"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is required to embed the icon. Install Node.js/npm, then rerun this script."
}

New-Item -ItemType Directory -Force -Path $tools | Out-Null

if (-not (Test-Path $rceditEntry)) {
    npm --prefix $tools install rcedit@5.0.2 --no-audit --no-fund
}

Copy-Item -LiteralPath $source -Destination $launcher -Force

$nodeCode = @'
const { pathToFileURL } = require("node:url");

(async () => {
  const entry = process.argv[2];
  const launcher = process.argv[3];
  const icon = process.argv[4];
  const { rcedit } = await import(pathToFileURL(entry).href);

  await rcedit(launcher, {
    icon,
    "version-string": {
      FileDescription: "Prompt Optimizer",
      ProductName: "Prompt Optimizer",
      OriginalFilename: "Prompt Optimizer.exe",
      InternalName: "Prompt Optimizer"
    }
  });
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'@

$nodeFile = Join-Path ([System.IO.Path]::GetTempPath()) "prompt-optimizer-rcedit.js"
Set-Content -LiteralPath $nodeFile -Value $nodeCode -Encoding UTF8
try {
    node $nodeFile $rceditEntry $launcher $icon
}
finally {
    Remove-Item -LiteralPath $nodeFile -Force -ErrorAction SilentlyContinue
}

Write-Host "Created launcher: $launcher" -ForegroundColor Green
Write-Host "Icon embedded  : $icon"
