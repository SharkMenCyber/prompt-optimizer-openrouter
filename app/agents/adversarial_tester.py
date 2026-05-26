from typing import Any

from app.services.openrouter_client import OpenRouterClient


class AdversarialTesterAgent:
    def __init__(self, client: OpenRouterClient):
        self.client = client

    def test(
        self,
        versions: list[dict[str, str]],
        intent: dict[str, Any],
        target_model: str | None = None,
    ) -> list[dict[str, Any]]:
        fallback = {"stress_tests": [self._local_test(version) for version in versions]}
        result = self.client.chat_json(
            system_prompt=(
                "You are an adversarial prompt tester. Test how a prompt could be misunderstood, "
                "produce vague output, miss constraints, or create unsafe output."
            ),
            user_prompt=f"""
Intent:
{intent}

Prompt versions:
{versions}

Return JSON:
{{"stress_tests": [{{"label": "...", "tests": [], "failure_modes": [], "high_risk_failures": false}}]}}
""",
            fallback=fallback,
            model=target_model,
            max_tokens=2600,
        )
        tests = result.get("stress_tests", fallback["stress_tests"])
        return tests if isinstance(tests, list) else fallback["stress_tests"]

    def _local_test(self, version: dict[str, str]) -> dict[str, Any]:
        prompt = version.get("prompt_text", "")
        failure_modes = []

        if "Assumptions" not in prompt:
            failure_modes.append("The model may silently assume missing details.")
        if "Constraints" not in prompt:
            failure_modes.append("The model may ignore boundaries or exclusions.")
        if "Quality Check" not in prompt:
            failure_modes.append("The model may not verify the answer before final output.")
        if any(word in prompt.lower() for word in ["build", "system", "app", "agent", "api", "ide"]):
            blueprint_terms = ["architecture", "tech stack", "database", "roadmap", "testing", "security"]
            if sum(1 for term in blueprint_terms if term in prompt.lower()) < 4:
                failure_modes.append("A complex system request may receive a shallow answer because blueprint sections are missing.")
        if any(term in prompt.lower() for term in ["css", "visual", "image", "designer"]) and any(
            term in prompt.lower()
            for term in ["architecture options", "database", "safe terminal", "cybersecurity lab", "open-source tools research"]
        ):
            failure_modes.append("The model may answer an unrelated system-architecture task instead of acting as a CSS/design specialist.")

        return {
            "label": version.get("label", "unknown"),
            "tests": [
                "Ambiguity test",
                "Missing context test",
                "Output format test",
                "Safety/privacy test",
            ],
            "failure_modes": failure_modes,
            "high_risk_failures": False,
        }
