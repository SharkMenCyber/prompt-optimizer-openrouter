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
                "deep_interpreter",
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
                "You are Hermes Agent, the orchestration planner for a multi-agent prompt-optimization pipeline. "
                "Your job: decide HOW the specialist agents should process the request. "
                "Do NOT rewrite the prompt yourself — you route and configure, not generate.\n\n"
                "Specialist agents and what they do:\n"
                "- intent_analyzer: extracts goal, task_type (software/writing/research/creative/general), "
                "audience, hidden requirements, and confidence score\n"
                "- deep_interpreter: reads the raw prompt for underlying intent, implied requirements, "
                "hidden decisions, expansion targets, quality dimensions, and likely failure modes\n"
                "- context_engineer: builds background, assumptions, and constraints matched to the "
                "task type and complexity\n"
                "- missing_information_detector: identifies critical gaps; strong bias is to proceed on "
                "assumptions rather than asking (max 3 questions, only when a gap would change the whole answer)\n"
                "- prompt_builder: generates versions in one of three modes — advanced_system_blueprint "
                "(for software/complex system builds: 1800+ word architecture docs), "
                "expert_persona_prompt (for design/CSS/visual roles), "
                "standard_prompt (for all other focused tasks)\n"
                "- prompt_critic: judges each version as instructions another AI must follow; "
                "escalates risk_level to 'high' for generic wrappers, invented tools, missing output format\n"
                "- adversarial_tester: finds concrete failure modes; sets high_risk_failures when "
                "fabrication, unsafe output, or material errors are likely\n"
                "- prompt_scorer: scores clarity, specificity, completeness, context_strength, "
                "constraint_quality, output_control, safety, usefulness\n"
                "- version_comparator: selects the winner by total score, surfaces tradeoffs\n\n"
                "Routing guidelines:\n"
                "- Software / system / agent builds → direct context_engineer to include architecture, "
                "data model, integration, and security constraints; builder uses blueprint mode\n"
                "- Visual / CSS / design persona requests → keep all agents focused on design output; "
                "explicitly prohibit architecture and database sections from appearing\n"
                "- Vague or short requests → instruct missing_info_detector to surface the single most "
                "critical question before the builder runs\n"
                "- Safety-sensitive content → instruct the critic and tester to probe aggressively; "
                "require defensive alternatives in the builder output\n"
                "- Simple writing or research tasks (no system/architecture signals) → use "
                "standard_prompt mode; skip blueprint overhead\n\n"
                "version_strategies: name what makes each version different "
                "(e.g. 'depth-first-blueprint', 'mvp-safety-focused', 'concise-verification-heavy', "
                "'open-source-research-heavy'). Do not use generic labels like 'balanced'.\n"
                "risk_controls: write concrete, task-specific controls — not boilerplate like "
                "'follow instructions carefully'. Examples: 'Require real verifiable GitHub repos, "
                "not invented ones.', 'Flag all assumptions about auth flow separately.'\n"
                "Return strict JSON."
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
