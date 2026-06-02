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
                "You are an adversarial tester in a prompt-optimization pipeline. For each candidate "
                "PROMPT, imagine a capable but literal AI executing it and find the ways it goes wrong: "
                "misread intent, vague or generic output, ignored constraints, missing output format, or "
                "unsafe content. Name concrete failure modes, not generic categories.\n"
                "For software/system (blueprint) prompts, probe specifically for: shallow architecture "
                "(headers without decisions), invented or unverifiable tools/APIs/repos, missing build "
                "phases or tests, and unsafe or unauthorized technical steps.\n"
                "Also probe whether the prompt merely wraps the raw request in generic prompt-engineering "
                "sections instead of carrying a deep interpretation, implied requirements, hidden decisions, "
                "and failure modes into the final instructions.\n"
                "Set high_risk_failures to true when at least one failure mode would likely yield "
                "fabricated, unsafe, or materially wrong output (e.g. the prompt invites invented tools, "
                "omits all output control, or enables harmful actions); otherwise false. Return strict JSON."
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
            reasoning_enabled=False,
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
        if not any(marker in prompt.lower() for marker in ["task understanding", "deep reading", "underlying intent", "implied requirements"]):
            failure_modes.append("The model may produce a generic answer because the prompt lacks a deep reading of the request.")
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
