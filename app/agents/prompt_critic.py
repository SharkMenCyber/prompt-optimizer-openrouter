from typing import Any

from app.services.openrouter_client import OpenRouterClient


class PromptCriticAgent:
    def __init__(self, client: OpenRouterClient):
        self.client = client

    def critique(
        self,
        versions: list[dict[str, str]],
        intent: dict[str, Any],
        target_model: str | None = None,
    ) -> list[dict[str, Any]]:
        fallback = {"critiques": [self._local_critique(version) for version in versions]}
        result = self.client.chat_json(
            system_prompt=(
                "You are a prompt critic. Find ambiguity, weak wording, missing details, "
                "unclear output requirements, and practical risks."
            ),
            user_prompt=f"""
Intent:
{intent}

Prompt versions:
{versions}

Return JSON:
{{"critiques": [{{"label": "...", "strengths": [], "weaknesses": [], "fixes": [], "risk_level": "low|medium|high"}}]}}
""",
            fallback=fallback,
            model=target_model,
            max_tokens=2600,
        )
        critiques = result.get("critiques", fallback["critiques"])
        return critiques if isinstance(critiques, list) else fallback["critiques"]

    def _local_critique(self, version: dict[str, str]) -> dict[str, Any]:
        prompt = version.get("prompt_text", "")
        weaknesses = []
        fixes = []

        if "Output Format" not in prompt:
            weaknesses.append("Output format is not explicit enough.")
            fixes.append("Add a strict output format section.")
        if "Do not invent" not in prompt and "do not invent" not in prompt.lower():
            weaknesses.append("The prompt does not strongly prevent fabricated details.")
            fixes.append("Add a no-fabrication constraint.")
        if len(prompt) < 500:
            weaknesses.append("Prompt may be too short for complex tasks.")
            fixes.append("Add context, constraints, and a quality check.")
        blueprint_terms = [
            "architecture options",
            "agent design",
            "tech stack",
            "database",
            "roadmap",
            "security",
            "testing",
        ]
        if any(word in prompt.lower() for word in ["build", "system", "app", "agent", "api", "ide"]):
            hits = sum(1 for term in blueprint_terms if term in prompt.lower())
            if hits < 4:
                weaknesses.append("Complex system prompt is too generic and lacks blueprint-level sections.")
                fixes.append("Add architecture options, agent/component design, tech stack, database/memory design, roadmap, testing, and security sections.")
        if any(term in prompt.lower() for term in ["css", "visual", "image", "designer"]) and any(
            term in prompt.lower()
            for term in ["architecture options", "database", "safe terminal", "cybersecurity lab", "open-source tools research"]
        ):
            weaknesses.append("Prompt includes unrelated system-building sections for a visual design/CSS persona request.")
            fixes.append("Keep the prompt focused on role, visual input handling, CSS/HTML rules, output formats, and design quality checks.")

        return {
            "label": version.get("label", "unknown"),
            "strengths": ["Clear structure", "Includes task objective"],
            "weaknesses": weaknesses,
            "fixes": fixes,
            "risk_level": "medium" if weaknesses else "low",
        }
