$ErrorActionPreference = "Stop"

if (!(Test-Path ".venv")) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install hermes-agent
@'
from app.services.hermes_adapter import HermesAdapter
status = HermesAdapter().status()
print(status)
'@ | .\.venv\Scripts\python.exe -
