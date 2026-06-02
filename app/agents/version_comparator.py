from typing import Any


# Human-readable labels for rubric criteria names so the UI and comparator
# narrative don't expose internal snake_case identifiers.
CRITERIA_LABELS: dict[str, str] = {
    "clarity": "structure and readability",
    "specificity": "depth and specificity",
    "completeness": "section completeness",
    "context_strength": "role and context definition",
    "constraint_quality": "constraints and hard rules",
    "output_control": "output format control",
    "safety": "safety and risk controls",
    "usefulness": "practical usefulness",
}


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
        critique_map = {item.get("label"): item for item in critiques}
        test_map = {item.get("label"): item for item in stress_tests}
        ranked = sorted(scores, key=lambda item: item.get("total", 0), reverse=True)
        winner = ranked[0]
        label = winner["label"]
        runner_up = ranked[1] if len(ranked) > 1 else None
        margin = winner.get("total", 0) - runner_up.get("total", 0) if runner_up else winner.get("total", 0)

        winner_critique = critique_map.get(label, {})
        winner_test = test_map.get(label, {})
        decision_factors = self._decision_factors(winner, critique=winner_critique)
        tradeoffs = self._tradeoffs(ranked, critiques, stress_tests)
        return {
            "winner_label": label,
            "winner_prompt": version_map.get(label, {}).get("prompt_text", ""),
            "winner_score": winner.get("total", 0),
            "reason": self._build_reason(winner, runner_up, margin, winner_critique, winner_test),
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

    def _build_reason(
        self,
        winner: dict[str, Any],
        runner_up: dict[str, Any] | None,
        margin: int,
        critique: dict[str, Any],
        test: dict[str, Any],
    ) -> str:
        """Build a human-readable winner explanation that goes beyond raw numbers."""
        label = winner["label"]
        score = winner.get("total", 0)
        parts: list[str] = [f"{label} scored highest at {score}/100"]

        if runner_up is not None and margin > 0:
            parts.append(f"leading by {margin} point{'s' if margin != 1 else ''}")

        risk = critique.get("risk_level", "")
        if risk == "low":
            parts.append("the critic found no major concerns")
        elif risk == "high":
            parts.append("though the critic flagged high risk — review before deploying")

        if not test.get("high_risk_failures"):
            parts.append("and stress testing found no high-risk failure modes")

        strengths = critique.get("strengths") or []
        if strengths and isinstance(strengths[0], str):
            first = strengths[0].rstrip(".")
            parts.append(f"Key strength: {first[0].lower() + first[1:] if first else first}")

        return ". ".join(parts) + "."

    def _decision_factors(self, winner: dict[str, Any], critique: dict[str, Any] | None = None) -> list[str]:
        criteria = winner.get("criteria", {})
        if not criteria:
            return ["No detailed criteria were available."]

        sorted_criteria = sorted(criteria.items(), key=lambda item: item[1], reverse=True)
        top = sorted_criteria[:3]
        low = [item for item in sorted_criteria if item[1] <= 6]

        factors = [
            f"Strong {CRITERIA_LABELS.get(name, name.replace('_', ' '))} ({score}/10)."
            for name, score in top
        ]
        if low:
            factors.append(
                "Areas to watch: "
                + ", ".join(
                    f"{CRITERIA_LABELS.get(name, name.replace('_', ' '))} ({score}/10)"
                    for name, score in low[:2]
                )
                + "."
            )
        if critique:
            risk = critique.get("risk_level", "")
            if risk == "low":
                factors.append("Critic rated this prompt low-risk.")
            elif risk == "high":
                factors.append("⚠ Critic flagged high risk — review before use.")
            strengths = critique.get("strengths") or []
            if strengths and isinstance(strengths[0], str):
                factors.append(f"Critic highlight: {strengths[0]}")
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
