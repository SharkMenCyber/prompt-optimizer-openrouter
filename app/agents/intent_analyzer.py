from typing import Any

from app.services.openrouter_client import OpenRouterClient
from app.utils.json_tools import compact_text


class IntentAnalyzerAgent:
    def __init__(self, client: OpenRouterClient):
        self.client = client

    def analyze(self, raw_prompt: str, target_model: str | None = None) -> dict[str, Any]:
        fallback = self._local_analyze(raw_prompt, target_model)
        return self.client.chat_json(
            system_prompt=(
                "You are an intent analysis agent for a prompt optimization system. "
                "Identify the real task, hidden requirements, user goal, expected output, and target AI platform."
            ),
            user_prompt=f"""
Analyze this rough prompt.

Raw prompt:
{compact_text(raw_prompt)}

Target model, if provided:
{target_model or "not specified"}

Return JSON with:
goal, task_type, audience, target_ai_platform, hidden_requirements, expected_output, constraints, confidence.
""",
            fallback=fallback,
            model=target_model,
        )

    def _local_analyze(self, raw_prompt: str, target_model: str | None) -> dict[str, Any]:
        text = raw_prompt.lower()
        task_type = "general"
        if any(word in text for word in ["code", "app", "api", "python", "javascript", "bug"]):
            task_type = "software"
        elif any(word in text for word in ["email", "sales", "marketing", "copy"]):
            task_type = "writing"
        elif any(word in text for word in ["research", "compare", "github", "sources"]):
            task_type = "research"
        elif any(word in text for word in ["image", "logo", "design", "ui"]):
            task_type = "creative"

        platform = "general LLM"
        for name in ["chatgpt", "claude", "gemini", "openrouter", "llama", "qwen"]:
            if name in text:
                platform = name
                break

        return {
            "goal": raw_prompt.strip(),
            "task_type": task_type,
            "audience": "not specified",
            "target_ai_platform": target_model or platform,
            "hidden_requirements": [
                "Preserve the user's original intent.",
                "Make the output format explicit.",
                "Add constraints that prevent vague or incomplete responses.",
            ],
            "expected_output": "An improved prompt with clear structure and output requirements.",
            "constraints": [],
            "confidence": 0.62,
            "source": "local_fallback",
        }

