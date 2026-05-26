# Hermes Prompt Optimizer

A local prompt optimizer that uses OpenRouter and the Hermes Agent System to turn rough prompts into stronger, scored, versioned prompts.

## What It Does

- Accepts a rough prompt
- Analyzes intent and missing context
- Uses Hermes orchestration when enabled
- Builds multiple optimized prompt versions
- Critiques and stress-tests each version
- Scores prompt quality
- Chooses the strongest final prompt
- Saves basic history
- Reuses successful prior prompt patterns through memory retrieval

## What Was Removed

This project was simplified back to the core prompt optimizer. It no longer includes auth, workspaces, admin panels, email, PostgreSQL, Docker deployment, analytics, eval lab, Promptfoo, external tools, import/export, templates, observability, security simulation UI, the fancy agent map, or AI judge controls.

## Setup

1. Create or edit `.env`:

```env
OPENROUTER_API_KEY=your_key_here
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=auto
DATABASE_PATH=data/prompt_optimizer.db
PROMPT_OPTIMIZER_POLICY_MODE=strict
PROMPT_OPTIMIZER_ENABLE_LOCAL_RESTART=true
APP_PORT=8050
```

2. Install dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

3. Start the app:

```powershell
.\scripts\start_supervised.ps1 -Port 8050
```

4. Open:

```text
http://127.0.0.1:8050
```

## Verification

Run:

```powershell
.\scripts\release_check.ps1 -Port 8050
```

## Core Files

- `app/main.py`: focused API routes
- `app/pipeline.py`: Hermes and prompt optimization pipeline
- `app/agents/`: specialist prompt agents
- `app/db/repository.py`: SQLite storage, history, memory, feedback
- `static/index.html`: focused dashboard
- `static/app.js`: frontend behavior
- `static/styles.css`: focused dashboard styling

## API

The main local endpoint is:

```text
POST /api/optimize
```

The optional API-key protected endpoint is:

```text
POST /api/v1/optimize
```

Hermes remains part of the optimizer and can be enabled from the dashboard.
