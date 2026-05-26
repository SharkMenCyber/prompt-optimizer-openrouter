from typing import Any

from app.services.openrouter_client import OpenRouterClient
from app.utils.json_tools import compact_text


class MissingInformationDetectorAgent:
    def __init__(self, client: OpenRouterClient):
        self.client = client

    def detect(
        self,
        raw_prompt: str,
        intent: dict[str, Any],
        context: dict[str, Any],
        target_model: str | None = None,
    ) -> dict[str, Any]:
        fallback = self._local_detect(raw_prompt, intent)
        return self.client.chat_json(
            system_prompt=(
                "You detect missing information in rough prompts. "
                "Ask for clarification only when the missing detail would materially change the final prompt."
            ),
            user_prompt=f"""
Raw prompt:
{compact_text(raw_prompt)}

Intent:
{intent}

Context:
{context}

Return JSON with missing_fields, critical_questions, can_continue_with_assumptions, risk_level.
""",
            fallback=fallback,
            model=target_model,
        )

    def _local_detect(self, raw_prompt: str, intent: dict[str, Any]) -> dict[str, Any]:
        missing_fields: list[str] = []
        questions: list[str] = []
        text = raw_prompt.strip()

        if len(text.split()) < 8:
            missing_fields.append("goal_detail")
            questions.append("What result do you want the AI to produce?")
        if "format" not in text.lower() and "output" not in text.lower():
            missing_fields.append("output_format")
            questions.append("What output format do you want?")
        if intent.get("audience") == "not specified":
            missing_fields.append("audience")

        risk_level = "low"
        if len(missing_fields) >= 3:
            risk_level = "medium"

        return {
            "missing_fields": missing_fields,
            "critical_questions": questions[:3],
            "can_continue_with_assumptions": True,
            "risk_level": risk_level,
            "source": "local_fallback",
        }

