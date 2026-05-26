# Contributing

Thank you for helping improve the Prompt Optimizer.

## Development Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
.\scripts\start_supervised.ps1
```

Open:

```text
http://127.0.0.1:8050
```

## Before Submitting Changes

Run:

```powershell
python -m compileall app
node --check static\app.js
.\scripts\check_status.ps1 -Port 8050
```

## Contribution Areas

- better prompt scoring rubrics
- more evaluation cases
- OpenRouter model-selection improvements
- Promptfoo or other eval integrations
- dashboard usability
- documentation and beginner guides
- policy layer improvements

## Policy Layer

Do not submit changes that make the optimizer strengthen malware, credential theft, stealth, or unauthorized access prompts. Improve `app/policy.py` and `docs/OPEN_SOURCE_POLICY.md` when changing policy behavior.
