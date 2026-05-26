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
        target_model: str | None = None,
    ) -> dict[str, Any]:
        fallback = {
            "background": "The user wants a stronger prompt that another AI can follow reliably.",
            "assumptions": [
                "The prompt should remain faithful to the original user goal.",
                "The model should ask only important clarification questions.",
                "The output should be easy to evaluate.",
            ],
            "constraints": [
                "Do not invent facts the user did not provide.",
                "Make output format explicit.",
                "Include safety and quality checks when relevant.",
            ],
            "retrieved_patterns": memory_matches,
            "source": "local_fallback",
        }
        return self.client.chat_json(
            system_prompt=(
                "You are a context engineering agent. Add only useful context, constraints, "
                "assumptions, and missing background that make a prompt easier for an LLM to execute."
            ),
            user_prompt=f"""
Raw prompt:
{compact_text(raw_prompt)}

Intent:
{intent}

Successful past patterns:
{memory_matches}

Return JSON with background, assumptions, constraints, retrieved_patterns.
""",
            fallback=fallback,
            model=target_model,
        )

