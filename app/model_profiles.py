from __future__ import annotations

from typing import Any


def profile_for_model(model_id: str | None, model_spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build prompt-shaping guidance for an OpenRouter model.

    `model_spec` is the raw model object from OpenRouter's /models catalog
    (keys: context_length, architecture, supported_parameters, pricing, ...).
    """
    model = (model_id or "auto").strip() or "auto"
    normalized = model.lower()
    spec = model_spec or {}
    architecture = spec.get("architecture") or {}
    supported = {str(item).lower() for item in (spec.get("supported_parameters") or [])}
    context_tokens = int(spec.get("context_length") or 0)
    instruct_type = str(architecture.get("instruct_type") or "").lower()

    family = _model_family(normalized)
    strengths: list[str] = []
    risks: list[str] = []
    guidance: list[str] = []
    controls: list[str] = [
        "Use explicit section headings.",
        "State assumptions separately from facts.",
        "Give the model a concrete output format.",
    ]

    if model == "auto":
        strengths.append("Lets the backend choose the strongest available OpenRouter text model.")
        guidance.append("Keep instructions provider-neutral and structured.")
        guidance.append("Avoid model-specific syntax unless the selected model is known.")

    if "reasoning" in supported or any(term in normalized for term in ["deepseek-r", "o1", "o3", "reason", "thinking"]):
        strengths.append("Good for multi-step reasoning and critique-heavy prompt optimization.")
        guidance.append("Ask for brief planning, verification, and failure-mode checks.")
        controls.append("Separate analysis goals from final output requirements.")

    if "response_format" in supported or "structured_outputs" in supported:
        strengths.append("Can follow structured-output requirements well.")
        guidance.append("Define strict JSON, Markdown, or table schemas when useful.")
        controls.append("Name required fields and allowed values.")

    if "tools" in supported or "tool_choice" in supported:
        strengths.append("Suitable for tool-oriented and agentic workflows.")
        guidance.append("Describe tool inputs, tool outputs, and handoff rules clearly.")

    if any(term in normalized for term in ["coder", "code", "qwen", "deepseek", "codestral"]):
        strengths.append("Strong fit for coding, debugging, and technical prompt tasks.")
        guidance.append("Include environment, files, commands, expected behavior, and tests.")
        controls.append("Require patch-size discipline and verification steps.")

    if any(term in normalized for term in ["mini", "flash", "lite", "small", "haiku", "8b", "7b", "3b"]):
        strengths.append("Fast and cost-efficient for lightweight prompt rewrites.")
        risks.append("May need tighter constraints for complex or ambiguous tasks.")
        guidance.append("Keep prompts compact and avoid too many competing objectives.")

    if any(term in normalized for term in ["uncensored", "dolphin", "role", "story"]) or instruct_type in {"airoboros", "alpaca"}:
        strengths.append("Flexible with style, voice, and creative role instructions.")
        risks.append("Needs stronger safety, scope, and factuality constraints for public use.")
        guidance.append("Add explicit boundaries, source-of-truth rules, and refusal behavior.")

    if context_tokens >= 128000:
        strengths.append("Large context window for long prompt histories and examples.")
        guidance.append("Use compact retrieved examples and label which examples are authoritative.")
    elif context_tokens and context_tokens < 32000:
        risks.append("Smaller context window; keep memory snippets short.")
        guidance.append("Prioritize the current request over long historical context.")

    if not strengths:
        strengths.append("General-purpose text model for structured prompt optimization.")
    if not guidance:
        guidance.append("Use clear role, objective, context, constraints, and output format sections.")

    return {
        "model_id": model,
        "family": family,
        "context_tokens": context_tokens or None,
        "optimization_style": _optimization_style(strengths, risks),
        "strengths": strengths,
        "risks": risks,
        "prompting_guidance": guidance,
        "recommended_prompt_controls": controls,
    }


def _model_family(normalized_model_id: str) -> str:
    # OpenRouter ids are "vendor/model" (e.g. "openai/gpt-4o", "anthropic/claude-3.5-sonnet").
    families = {
        "openai/": "OpenAI",
        "gpt-": "OpenAI",
        "anthropic/": "Anthropic",
        "claude": "Anthropic",
        "google/": "Google",
        "gemini": "Google",
        "gemma": "Google",
        "meta-llama/": "Llama",
        "llama": "Llama",
        "mistral": "Mistral",
        "qwen": "Qwen",
        "deepseek": "DeepSeek",
        "x-ai/": "Grok",
        "grok": "Grok",
        "cohere": "Cohere",
        "dolphin": "Dolphin",
    }
    for marker, family in families.items():
        if marker in normalized_model_id:
            return family
    if normalized_model_id == "auto":
        return "Auto-selected"
    return "General text"


def _optimization_style(strengths: list[str], risks: list[str]) -> str:
    joined = " ".join([*strengths, *risks]).lower()
    if "coding" in joined or "debugging" in joined:
        return "technical-structured"
    if "reasoning" in joined or "critique" in joined:
        return "verification-heavy"
    if "creative" in joined or "style" in joined:
        return "boundary-aware-creative"
    if "fast" in joined or "lightweight" in joined:
        return "compact-direct"
    return "balanced-structured"
