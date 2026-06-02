from typing import Any

from app.services.openrouter_client import OpenRouterClient
from app.utils.json_tools import compact_text


class ContextEngineerAgent:
    def __init__(self, client: OpenRouterClient):
        self.client = client

    def build_context(
        self,
        raw_prompt: str,
        intent: dict[str, Any],
        memory_matches: list[dict[str, Any]],
        deep_interpretation: dict[str, Any] | None = None,
        target_model: str | None = None,
    ) -> dict[str, Any]:
        deep = deep_interpretation or {}
        fallback = {
            "background": deep.get("essence") or "The user wants a stronger prompt that another AI can follow reliably.",
            "assumptions": [
                "The prompt should remain faithful to the original user goal.",
                "The model should ask only important clarification questions.",
                "The output should be easy to evaluate.",
            ],
            "constraints": [
                "Do not invent facts the user did not provide.",
                "Make output format explicit.",
                "Include safety and quality checks when relevant.",
            ]
            + [str(item) for item in deep.get("constraints_to_preserve", []) if str(item).strip()],
            "depth_targets": deep.get("expansion_targets", []),
            "hidden_decisions": deep.get("hidden_decisions", []),
            "deep_interpretation": deep,
            "retrieved_patterns": memory_matches,
            "source": "local_fallback",
        }
        return self.client.chat_json(
            system_prompt=(
                "You are a context-engineering agent in a prompt-optimization pipeline. Using the request "
                "and detected intent, supply the background, constraints, and assumptions that make the "
                "final prompt easier for another AI to execute well. Add only context grounded in the "
                "request or safe general best practice — never invent facts, tools, numbers, or "
                "requirements the user did not imply.\n"
                "Make constraints concrete and testable (explicit output format, no-fabrication rules, "
                "scope limits). Match depth to the task: for software/system requests include architecture, "
                "integration, data, and security considerations; for design/persona requests stay on visual "
                "and output concerns; for everyday requests keep it lean. State assumptions plainly so they "
                "can be verified. Return strict JSON."
            ),
            user_prompt=f"""
Raw prompt:
{compact_text(raw_prompt)}

Intent:
{intent}

Deep interpretation of the raw prompt:
{deep}

Successful past patterns:
{memory_matches}

Return JSON with background, assumptions, constraints, depth_targets, hidden_decisions, retrieved_patterns.
""",
            fallback=fallback,
            model=target_model,
            reasoning_enabled=False,
        )
