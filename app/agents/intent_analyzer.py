from typing import Any

from app.services.openrouter_client import OpenRouterClient
from app.utils.json_tools import compact_text


class IntentAnalyzerAgent:
    # task_type is load-bearing: the builder routes prompt modes on it and memory
    # retrieval matches on it. Constrain it to a fixed vocabulary so the model
    # cannot silently break that routing by returning "coding", "dev", etc.
    ALLOWED_TASK_TYPES = ("software", "writing", "research", "creative", "general")
    _TASK_TYPE_SYNONYMS = {
        "code": "software", "coding": "software", "programming": "software",
        "development": "software", "dev": "software", "engineering": "software",
        "technical": "software", "app": "software", "system": "software", "api": "software",
        "copy": "writing", "copywriting": "writing", "marketing": "writing",
        "email": "writing", "content": "writing", "blog": "writing",
        "analysis": "research", "analytics": "research", "data": "research",
        "comparison": "research", "investigation": "research",
        "design": "creative", "ui": "creative", "ux": "creative",
        "art": "creative", "image": "creative", "visual": "creative",
    }

    def __init__(self, client: OpenRouterClient):
        self.client = client

    def analyze(self, raw_prompt: str, target_model: str | None = None) -> dict[str, Any]:
        fallback = self._local_analyze(raw_prompt, target_model)
        result = self.client.chat_json(
            system_prompt=(
                "You are the intent-analysis agent in a prompt-optimization pipeline. Your reading of "
                "the request decides how every later agent treats it, so be precise. Surface the user's "
                "true underlying goal (not just the literal words), the hidden requirements they did not "
                "state, what a great output looks like, and the target AI platform.\n"
                "Classify task_type as EXACTLY ONE of: software (apps, systems, code, APIs, agents), "
                "writing (emails, copy, content, marketing), research (analysis, comparison, sourcing), "
                "creative (visual/UI/design, art, naming), or general (anything else). When unsure, use "
                "general. Return strict JSON only."
            ),
            user_prompt=f"""
Analyze this rough prompt.

Raw prompt:
{compact_text(raw_prompt)}

Target model, if provided:
{target_model or "not specified"}

Return JSON with these fields:
- goal: the real underlying objective, in one sentence
- task_type: exactly one of [software, writing, research, creative, general]
- audience: who the output is for, or "not specified"
- target_ai_platform: the AI that will run the final prompt
- hidden_requirements: list of unstated but important needs
- expected_output: what a strong result looks like
- constraints: list of hard limits the final prompt must respect
- confidence: 0.0-1.0 for how clearly the request is specified
""",
            fallback=fallback,
            model=target_model,
            reasoning_enabled=False,
        )
        result["task_type"] = self._normalize_task_type(result.get("task_type"))
        return result

    def _normalize_task_type(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in self.ALLOWED_TASK_TYPES:
            return text
        return self._TASK_TYPE_SYNONYMS.get(text, "general")

    def _local_analyze(self, raw_prompt: str, target_model: str | None) -> dict[str, Any]:
        text = raw_prompt.lower()
        task_type = "general"
        if any(word in text for word in ["code", "coding", "coder", "developer", "app", "api", "python", "javascript", "bug", "agent", "assistant"]):
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
