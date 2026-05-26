from typing import Any

from app.services.hermes_adapter import HermesAdapter
from app.utils.json_tools import compact_text, extract_json_object


class HermesOrchestratorAgent:
    def __init__(self, adapter: HermesAdapter | None = None):
        self.adapter = adapter or HermesAdapter()

    def plan(self, raw_prompt: str, version_count: int) -> dict[str, Any]:
        fallback = {
            "enabled": False,
            "workflow_strategy": "Use the built-in deterministic Python multi-agent pipeline.",
            "agent_order": [
                "intent_analyzer",
                "context_engineer",
                "missing_information_detector",
                "prompt_builder",
                "prompt_critic",
                "adversarial_tester",
                "prompt_scorer",
                "version_comparator",
            ],
            "version_strategies": ["balanced", "high-structure", "verification-heavy"][:version_count],
            "risk_controls": [
                "Keep the prompt faithful to the user's original intent.",
                "Ask clarification only when a missing detail would materially change the result.",
                "Score and compare versions before choosing the winner.",
            ],
            "source": "local_fallback",
        }

        status = self.adapter.status()
        if not status.installed or not status.configured:
            fallback["warning"] = status.message
            return fallback

        response = self.adapter.chat(
            message=f"""
Create a run strategy for a prompt optimization pipeline.

Raw prompt:
{compact_text(raw_prompt)}

Number of prompt versions requested:
{version_count}

Return only JSON with:
enabled, workflow_strategy, agent_order, version_strategies, risk_controls.
""",
            system_prompt=(
                "You are Hermes Agent acting as the orchestration planner for a prompt optimization system. "
                "You do not rewrite the prompt directly. You decide how specialist agents should process it."
            ),
            max_iterations=4,
        )
        parsed = extract_json_object(response)
        if parsed is None:
            fallback["warning"] = "Hermes response was not valid JSON; used the local plan."
            return fallback
        parsed["enabled"] = True
        parsed["source"] = "hermes"
        return parsed

