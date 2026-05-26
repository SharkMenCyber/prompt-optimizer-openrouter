import json
import re
from typing import Any


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object extraction for model responses.

    Returns the parsed object, or None when no JSON object can be recovered so
    callers can decide how to build and label their own fallback.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(cleaned[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def compact_text(value: str, limit: int = 5000) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def derive_title(text: str | None, empty_default: str) -> str:
    """Turn a raw prompt into a short conversation title: single-line, capped at
    60 chars with an ellipsis. Callers pass their own fallback for empty input."""
    cleaned = (text or "").strip().replace("\n", " ")
    if not cleaned:
        return empty_default
    return cleaned[:60] + "..." if len(cleaned) > 60 else cleaned

