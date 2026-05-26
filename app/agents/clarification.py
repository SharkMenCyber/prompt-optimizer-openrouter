from typing import Any


class ClarificationAgent:
    def decide(self, missing_info: dict[str, Any], force_clarification: bool = False) -> dict[str, Any]:
        questions = missing_info.get("critical_questions", [])[:3]
        can_continue = bool(missing_info.get("can_continue_with_assumptions", True))
        should_ask = force_clarification or (not can_continue and bool(questions))

        assumptions = []
        if missing_info.get("missing_fields"):
            assumptions.append("Proceed with reasonable assumptions for missing non-critical details.")
        if "output_format" in missing_info.get("missing_fields", []):
            assumptions.append("Use a structured Markdown output unless the user specifies another format.")
        if "audience" in missing_info.get("missing_fields", []):
            assumptions.append("Write for a general professional audience.")

        return {
            "should_ask_user": should_ask,
            "questions": questions,
            "assumptions": assumptions,
            "source": "local_rule",
        }

