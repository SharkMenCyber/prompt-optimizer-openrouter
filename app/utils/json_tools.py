import json
import re
from typing import Any


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object extraction for model responses.

    Returns the parsed object, or None when no JSON object can be recovered so
    callers can decide how to build and label their own fallback. Also repairs
    the common reasoning-model failure where a long JSON answer is cut off by
    the token limit mid-object, by closing any unterminated string/brackets
    before a final parse attempt.
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
    if start == -1:
        return None

    end = cleaned.rfind("}")
    if end > start:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    # Last resort: the response was truncated (the model hit max_tokens
    # mid-object). Repair the fragment from the first brace, then parse again.
    repaired = _repair_truncated_json(cleaned[start:])
    if repaired is None:
        return None
    try:
        parsed = json.loads(repaired)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _open_bracket_stack(text: str) -> list[str]:
    """Return the still-open brackets ('{'/'[') for a (partial) JSON string."""
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    return stack


def _close_brackets(stack: list[str]) -> str:
    return "".join("}" if opener == "{" else "]" for opener in reversed(stack))


def _repair_truncated_json(fragment: str) -> str | None:
    """Close a truncated JSON object so it can be parsed.

    Scans the fragment tracking string state and bracket depth. If it was cut
    mid-string on a value, that string is closed to salvage the partial text;
    otherwise the dangling partial token is trimmed back to the last complete
    value. Missing closing quotes/brackets are then appended. Returns None when
    the fragment is not an unterminated object (nothing useful to repair).
    """
    stack: list[str] = []
    in_string = False
    escape = False
    expect_key = False  # meaningful only while the top container is an object
    current_string_is_value = False
    safe_end = 0  # index we can safely truncate to (just past a complete value)

    i = 0
    length = len(fragment)
    while i < length:
        ch = fragment[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
                if current_string_is_value:
                    safe_end = i + 1
            i += 1
            continue
        if ch == '"':
            in_string = True
            current_string_is_value = (not stack) or stack[-1] == "[" or not expect_key
            i += 1
            continue
        if ch in "{[":
            stack.append(ch)
            if ch == "{":
                expect_key = True
            i += 1
            continue
        if ch in "}]":
            if stack:
                stack.pop()
            expect_key = bool(stack) and stack[-1] == "{"
            safe_end = i + 1
            i += 1
            continue
        if ch == ":":
            expect_key = False
            i += 1
            continue
        if ch == ",":
            safe_end = i  # cut before a dangling comma
            if stack and stack[-1] == "{":
                expect_key = True
            i += 1
            continue
        if ch in "-+0123456789.eE":
            j = i
            while j < length and fragment[j] in "-+0123456789.eE":
                j += 1
            safe_end = j
            i = j
            continue
        if ch in "tfn":  # true / false / null
            matched = False
            for literal in ("true", "false", "null"):
                if fragment.startswith(literal, i):
                    safe_end = i + len(literal)
                    i += len(literal)
                    matched = True
                    break
            if not matched:
                i += 1
            continue
        i += 1

    if not stack and not in_string:
        return None  # a complete (or non-object) fragment: nothing to repair

    if in_string and current_string_is_value:
        # Cut mid-value: drop a dangling escape, close the string, close brackets.
        salvage = (fragment[:-1] if escape else fragment) + '"'
        return salvage + _close_brackets(_open_bracket_stack(salvage))

    trimmed = fragment[:safe_end].rstrip().rstrip(",").rstrip()
    if not trimmed:
        return None
    return trimmed + _close_brackets(_open_bracket_stack(trimmed))


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

