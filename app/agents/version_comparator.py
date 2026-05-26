from typing import Any


class VersionComparisonAgent:
    def compare(
        self,
        versions: list[dict[str, str]],
        scores: list[dict[str, Any]],
        critiques: list[dict[str, Any]],
        stress_tests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not scores:
            return {
                "winner_label": "",
                "reason": "No scores were produced.",
                "ranking": [],
                "tradeoffs": [],
                "decision_factors": [],
            }

        score_map = {score["label"]: score for score in scores}
        version_map = {version["label"]: version for version in versions}
        ranked = sorted(scores, key=lambda item: item.get("total", 0), reverse=True)
        winner = ranked[0]
        label = winner["label"]
        runner_up = ranked[1] if len(ranked) > 1 else None
        margin = winner.get("total", 0) - runner_up.get("total", 0) if runner_up else winner.get("total", 0)

        decision_factors = self._decision_factors(winner)
        tradeoffs = self._tradeoffs(ranked, critiques, stress_tests)
        return {
            "winner_label": label,
            "winner_prompt": version_map.get(label, {}).get("prompt_text", ""),
            "winner_score": winner.get("total", 0),
            "reason": (
                f"{label} scored highest at {winner.get('total', 0)}/100. "
                f"It beat the nearest alternative by {margin} point{'s' if margin != 1 else ''}."
            ),
            "score_details": score_map.get(label, {}),
            "ranking": [
                {
                    "label": item.get("label"),
                    "strategy": item.get("strategy"),
                    "total": item.get("total"),
                    "score_source": item.get("score_source", "deterministic"),
                }
                for item in ranked
            ],
            "decision_factors": decision_factors,
            "tradeoffs": tradeoffs,
        }

    def _decision_factors(self, winner: dict[str, Any]) -> list[str]:
        criteria = winner.get("criteria", {})
        if not criteria:
            return ["No detailed criteria were available."]

        sorted_criteria = sorted(criteria.items(), key=lambda item: item[1], reverse=True)
        top = sorted_criteria[:3]
        low = [item for item in sorted_criteria if item[1] <= 6]

        factors = [f"Strong {name.replace('_', ' ')} score ({score}/10)." for name, score in top]
        if low:
            factors.append(
                "Watch "
                + ", ".join(f"{name.replace('_', ' ')} ({score}/10)" for name, score in low[:2])
                + "."
            )
        if winner.get("ai_judge_rationale"):
            factors.append(f"AI judge note: {winner['ai_judge_rationale']}")
        return factors

    def _tradeoffs(
        self,
        ranked: list[dict[str, Any]],
        critiques: list[dict[str, Any]],
        stress_tests: list[dict[str, Any]],
    ) -> list[str]:
        critique_map = {item.get("label"): item for item in critiques}
        test_map = {item.get("label"): item for item in stress_tests}
        tradeoffs = []

        for item in ranked[:3]:
            label = item.get("label")
            critique = critique_map.get(label, {})
            test = test_map.get(label, {})
            weaknesses = critique.get("weaknesses") or []
            failure_modes = test.get("failure_modes") or []
            if weaknesses:
                tradeoffs.append(f"{label}: {weaknesses[0]}")
            elif failure_modes:
                tradeoffs.append(f"{label}: {failure_modes[0]}")
            else:
                tradeoffs.append(f"{label}: no major weakness found in current checks.")

        return tradeoffs
