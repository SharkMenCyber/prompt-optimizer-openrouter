# Open Source Policy Layer

This project includes a transparent policy layer for public releases.

The policy layer is not meant to be mysterious or moralizing. It exists because this tool improves prompts. A prompt optimizer should not make malware, credential theft, stealth, or unauthorized access instructions more effective.

## Configuration

Set the mode in `.env`:

```env
PROMPT_OPTIMIZER_POLICY_MODE=strict
```

Supported modes:

- `standard`: redirects disallowed abuse requests into safe, defensive, educational, or authorization-bound alternatives.
- `strict`: uses the same categories with stricter refusal-and-redirect wording.

There is intentionally no public `off` mode in the app configuration.

## What The Policy Layer Checks

The current local policy layer checks for obvious abuse patterns:

- credential theft
- malware or spyware
- stealth, evasion, or unauthorized access
- covert monitoring or system-wide input capture wording

## Secret Handling

The app redacts likely API keys, tokens, passwords, and long secret-like strings before storing prompt history and agent traces. Redaction is a defense-in-depth feature, not a substitute for careful key handling.

Rotate any key that was pasted into chat, committed, logged, screenshotted, or shared.

It is intentionally simple and auditable. Maintainers can improve it by editing `app/policy.py`, adding tests, or replacing it with a stronger policy engine.

## Why This Matters

For normal prompt engineering, the system should optimize aggressively.

For disallowed abuse, the system should not strengthen harmful instructions. Instead it should produce a safer prompt that helps with:

- defensive security
- incident response
- secure coding
- threat modeling
- authorized lab or training context

This keeps the open-source project useful without turning it into an abuse amplifier.
