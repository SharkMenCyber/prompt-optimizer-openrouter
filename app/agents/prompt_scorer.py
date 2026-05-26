from typing import Any

from app.scoring.rubric import score_prompt
from app.services.openrouter_client import OpenRouterClient
from app.utils.json_tools import compact_text


class PromptScoringAgent:
    def __init__(self, client: OpenRouterClient | None = None):
        self.client = client or OpenRouterClient()

    def score(
        self,
        versions: list[dict[str, str]],
        critiques: list[dict[str, Any]],
        stress_tests: list[dict[str, Any]],
        target_model: str | None = None,
        use_ai_judge: bool = False,
    ) -> list[dict[str, Any]]:
        critique_map = {item.get("label"): item for item in critiques}
        test_map = {item.get("label"): item for item in stress_tests}

        scores = []
        for version in versions:
            label = version.get("label", "unknown")
            result = score_prompt(
                version.get("prompt_text", ""),
                critique=critique_map.get(label),
                tests=test_map.get(label),
            )
            judge = None
            if use_ai_judge and self.client.configured:
                judge = self._judge_with_model(
                    version=version,
                    critique=critique_map.get(label, {}),
                    stress_test=test_map.get(label, {}),
                    target_model=target_model,
                )

            final = self._combine_scores(result, judge)
            scores.append(
                {
                    "label": label,
                    "strategy": version.get("strategy", ""),
                    "total": final["total"],
                    "criteria": final["criteria"],
                    "penalties": final["penalties"],
                    "score_source": final["score_source"],
                    "deterministic_total": result["total"],
                    "ai_judge_total": judge.get("total") if judge else None,
                    "ai_judge_rationale": judge.get("rationale") if judge else None,
                    "ai_judge": judge,
                }
            )
        return scores

    def _judge_with_model(
        self,
        version: dict[str, str],
        critique: dict[str, Any],
        stress_test: dict[str, Any],
        target_model: str | None,
    ) -> dict[str, Any] | None:
        fallback = {
            "total": None,
            "criteria": {},
            "rationale": "AI judge was requested, but no valid judge response was produced.",
            "penalties": [],
        }

        result = self.client.chat_json(
            system_prompt=(
                "You are a strict prompt quality judge. Score the prompt as an instruction that another "
                "LLM must follow. Be practical, not flattering. Penalize ambiguity, weak output control, "
                "missing constraints, hidden assumptions, and unsafe instructions."
            ),
            user_prompt=f"""
Prompt version label:
{version.get("label")}

Prompt:
{compact_text(version.get("prompt_text", ""), limit=9000)}

Critic notes:
{critique}

Stress test notes:
{stress_test}

Return JSON with:
{{
  "criteria": {{
    "clarity": 1-10,
    "specificity": 1-10,
    "completeness": 1-10,
    "context_strength": 1-10,
    "constraint_quality": 1-10,
    "output_control": 1-10,
    "safety": 1-10,
    "usefulness": 1-10
  }},
  "total": 1-100,
  "rationale": "short explanation",
  "penalties": ["specific penalty"]
}}
""",
            fallback=fallback,
            model=target_model,
            temperature=0,
            max_tokens=1200,
        )

        criteria = result.get("criteria") if isinstance(result.get("criteria"), dict) else {}
        normalized_criteria = {
            key: self._clamp_int(criteria.get(key), 1, 10)
            for key in [
                "clarity",
                "specificity",
                "completeness",
                "context_strength",
                "constraint_quality",
                "output_control",
                "safety",
                "usefulness",
            ]
            if criteria.get(key) is not None
        }
        total = self._clamp_int(result.get("total"), 1, 100)
        if total is None and normalized_criteria:
            total = round(sum(normalized_criteria.values()) / (len(normalized_criteria) * 10) * 100)
        if total is None:
            return None

        return {
            "criteria": normalized_criteria,
            "total": total,
            "rationale": result.get("rationale", ""),
            "penalties": result.get("penalties", []) if isinstance(result.get("penalties"), list) else [],
            "source": result.get("source", "openrouter"),
        }

    def _combine_scores(self, deterministic: dict[str, Any], judge: dict[str, Any] | None) -> dict[str, Any]:
        if not judge:
            return {
                "total": deterministic["total"],
                "criteria": deterministic["criteria"],
                "penalties": deterministic["penalties"],
                "score_source": "deterministic",
            }

        criteria = dict(deterministic["criteria"])
        for key, judge_value in judge.get("criteria", {}).items():
            if key in criteria:
                criteria[key] = round((criteria[key] * 0.6) + (judge_value * 0.4))

        total = round((deterministic["total"] * 0.65) + (judge["total"] * 0.35))
        penalties = list(dict.fromkeys(deterministic.get("penalties", []) + judge.get("penalties", [])))
        return {
            "total": max(1, min(100, total)),
            "criteria": criteria,
            "penalties": penalties,
            "score_source": "deterministic_plus_ai_judge",
        }

    def _clamp_int(self, value: Any, minimum: int, maximum: int) -> int | None:
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            return None
        return max(minimum, min(maximum, number))
