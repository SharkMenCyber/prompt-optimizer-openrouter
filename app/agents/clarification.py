from typing import Any


class ClarificationAgent:
    def decide(self, missing_info: dict[str, Any], force_clarification: bool = False) -> dict[str, Any]:
        # Questions must be plain strings (the API contract is list[str]); upstream
        # models sometimes return them as objects like {"question": ..., "rationale": ...},
        # so flatten defensively rather than trusting the model's shape.
        questions = [self._as_question_text(q) for q in (missing_info.get("critical_questions") or [])[:3]]
        questions = [q for q in questions if q]
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

    @staticmethod
    def _as_question_text(question: Any) -> str:
        """Flatten a clarification question to plain text. Accepts a string, or an
        object like {"question": "...", "rationale": "..."} and returns its text."""
        if isinstance(question, dict):
            for key in ("question", "text", "q", "prompt"):
                value = question.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return ""
        return str(question).strip()

