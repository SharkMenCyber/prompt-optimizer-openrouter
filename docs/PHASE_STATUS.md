# Phase Status

Current app version: `0.6.1`

## Current Direction

The project has been simplified back to its core purpose: a local Hermes-powered prompt optimizer.

## Kept

- Raw prompt input
- OpenRouter model connection
- Auto model and model picker
- Hermes Agent System orchestration
- Intent, context, clarification, builder, critic, tester, scorer, and comparator agents
- Multiple prompt versions
- Final optimized prompt
- Prompt scoring
- Simple agent trace
- Basic history
- Memory retrieval from successful prior prompts
- Feedback summary
- Local restart button
- Optional API-key protected `/api/v1/optimize`

## Removed

- Login, sessions, password reset, and auth UI
- Workspaces, members, roles, invitations, and workspace preferences
- Admin dashboard
- Email/SMTP features
- PostgreSQL mode and migration scripts
- Docker and hosted deployment assets
- Analytics dashboard
- Evaluation lab and improve-from-eval flow
- Promptfoo integration
- External tools registry
- Settings/library import-export
- Templates tab
- Security simulation panel
- Observability dashboard
- Fancy neural Agents map
- AI judge toggle

## Latest Fix

- `0.6.1`: CSS/dashboard screenshot prompt requests now route to the focused design prompt builder instead of the software blueprint builder, even when noisy blueprint text surrounds the request.

## Next

1. Keep testing prompt quality with real prompts.
2. Tighten the prompt builder templates.
3. Add only features that directly improve prompt optimization.
