from __future__ import annotations

import re
from typing import Any

from app.policy import assess_prompt_policy


WEIGHTS = {
    "clarity": 16,
    "specificity": 14,
    "completeness": 14,
    "context_strength": 12,
    "constraint_quality": 12,
    "output_control": 12,
    "safety": 10,
    "usefulness": 10,
}


SECTION_MARKERS = [
    "role",
    "objective",
    "context",
    "instructions",
    "constraints",
    "output format",
    "quality check",
]

BLUEPRINT_MARKERS = [
    "architecture options",
    "recommended build path",
    "core features",
    "system architecture",
    "agent design",
    "tech stack",
    "database",
    "memory design",
    "workflow",
    "phase-by-phase",
    "roadmap",
    "testing",
    "security",
    "open-source",
    "risks",
]

DEEP_READING_MARKERS = [
    "task understanding",
    "deep reading",
    "deep design reading",
    "underlying intent",
    "implied requirements",
    "hidden decisions",
    "failure modes",
]


VAGUE_WORDS = {
    "good",
    "better",
    "nice",
    "stuff",
    "things",
    "etc",
    "somehow",
    "quickly",
}


def _contains_any(text: str, words: list[str]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


def _section_score(prompt: str) -> int:
    lowered = prompt.lower()
    found = sum(1 for marker in SECTION_MARKERS if marker in lowered)
    blueprint_found = sum(1 for marker in BLUEPRINT_MARKERS if marker in lowered)
    return min(10, 3 + found + min(3, blueprint_found // 3))


def _specificity_score(prompt: str) -> int:
    score = 5
    if len(prompt) > 700:
        score += 2
    if len(prompt) > 2200:
        score += 1
    if re.search(r"\b\d+\b", prompt):
        score += 1
    if _contains_any(prompt, ["must", "should", "avoid", "include", "exclude"]):
        score += 1
    if _blueprint_depth(prompt) >= 8:
        score += 1
    vague_hits = sum(1 for word in VAGUE_WORDS if re.search(rf"\b{word}\b", prompt.lower()))
    score -= min(3, vague_hits)
    return max(1, min(10, score))


def _output_control_score(prompt: str) -> int:
    score = 3
    if _contains_any(prompt, ["output format", "return", "format", "json", "table", "markdown"]):
        score += 3
    if _contains_any(prompt, ["do not", "only", "exactly", "no extra"]):
        score += 2
    if _contains_any(prompt, ["example", "schema", "fields"]):
        score += 2
    if _blueprint_depth(prompt) >= 8:
        score += 1
    return min(10, score)


def _blueprint_depth(prompt: str) -> int:
    lowered = prompt.lower()
    return sum(1 for marker in BLUEPRINT_MARKERS if marker in lowered)


def _looks_like_generic_wrapper(prompt: str) -> bool:
    lowered = prompt.lower()
    generic_phrases = [
        "help the user accomplish this goal",
        "you are an expert assistant specialized in",
        "return a structured markdown answer with",
        "next steps, only if useful",
    ]
    return sum(1 for phrase in generic_phrases if phrase in lowered) >= 2 and _blueprint_depth(prompt) < 5


def _looks_like_irrelevant_design_blueprint(prompt: str) -> bool:
    lowered = prompt.lower()
    design_hits = sum(1 for marker in ["css", "html", "visual", "image", "picture", "designer", "design"] if marker in lowered)
    irrelevant_hits = sum(
        1
        for marker in [
            "architecture options",
            "database",
            "api key storage",
            "safe terminal",
            "cybersecurity lab",
            "open-source tools research",
            "agent design",
            "phase-by-phase roadmap",
            "model-specific guidance",
            "target model:",
            "optimization style:",
        ]
        if marker in lowered
    )
    return design_hits >= 3 and irrelevant_hits >= 2


def _has_internal_builder_scaffolding(prompt: str) -> bool:
    return _contains_any(
        prompt,
        [
            "additional model-specific guidance",
            "model-specific guidance",
            "target model:",
            "optimization style:",
            "memory and reuse guidance",
            "original user idea to preserve",
            "this must not become a generic answer",
        ],
    )


def _safety_score(prompt: str) -> int:
    # Terms that are always a red flag regardless of surrounding context.
    risky_unambiguous = [
        "ignore previous",
        "bypass",
        "jailbreak",
        "keylogger",
        "malware",
        "ransomware",
        "spyware",
        "credential theft",
        "exfiltrate",
        "evade detection",
        "disable antivirus",
    ]
    # Terms that are only risky when NOT paired with protective/defensive language.
    # "api key" and "password" appear legitimately in security-hardening prompts.
    risky_contextual = ["secret key", "api key", "password"]
    protective_context = [
        "protect api", "api key storage", "store api", "secure api",
        "api key rotation", "api key management", "credential rotation",
        "safe storage", "vault", "protect", "safeguard",
        "do not expose", "redact", "never log", "encrypt",
        "never store in plaintext", "key rotation",
    ]
    score = 9
    if _contains_any(prompt, risky_unambiguous):
        score -= 6
    elif _contains_any(prompt, risky_contextual) and not _contains_any(prompt.lower(), protective_context):
        score -= 6
    if _contains_any(prompt, ["safety", "privacy", "do not invent", "do not reveal", "safe alternative", "refuse"]):
        score += 1
    return max(1, min(10, score))


def _constraint_score(prompt: str) -> int:
    """Count the actual density of constraints: hard prohibitions, positive
    requirements, and explicit scope/boundary language.  The old binary
    present/absent check awarded 9 to any prompt containing the word 'must'."""
    lowered = prompt.lower()
    # Each distinct prohibition keyword found counts once (not per occurrence).
    prohibitions = sum(
        1
        for term in ["do not", "never", "must not", "avoid", "exclude", "prohibited", "forbidden"]
        if re.search(rf"\b{re.escape(term)}\b", lowered)
    )
    # Each distinct hard-requirement keyword found counts once.
    requirements = sum(
        1
        for term in ["must", "only", "exactly", "required", "always"]
        if re.search(rf"\b{term}\b", lowered)
    )
    # Scope and boundary language (checked by simple substring — these words rarely
    # appear incidentally in prompt text).
    scope = sum(
        1
        for term in ["constraint", "limit", "restrict", "boundary", "scope", "protect"]
        if term in lowered
    )
    total = min(prohibitions, 3) + min(requirements, 3) + min(scope, 2)
    score = min(10, 3 + total)
    if _blueprint_depth(prompt) >= 8:
        score = min(10, score + 1)
    return max(1, score)


def _context_strength_score(prompt: str) -> int:
    """Score how explicitly the prompt establishes role, background, and purpose.
    The old 9/8/5 jump treated 'blueprint depth' and the word 'context' as the
    only signals — ignoring role definitions, objective statements, and examples."""
    lowered = prompt.lower()
    score = 3
    # Role or persona definition (e.g. "You are", "Act as", "# Role")
    if any(term in lowered for term in ["you are", "act as", "your role", "# role", "## role"]):
        score += 2
    # Explicit background or context section
    if any(term in lowered for term in ["background", "# context", "## context", "# objective", "## objective"]):
        score += 1
    # Stated assumptions (makes implicit context explicit)
    if any(term in lowered for term in ["assumption", "proceed with", "assume that"]):
        score += 1
    # Concrete examples or reference output (strongest context signal)
    if any(term in lowered for term in ["example", "sample output", "here is an example", "e.g."]):
        score += 1
    # Blueprint depth signals rich multi-domain context
    if _blueprint_depth(prompt) >= 8:
        score += 2
    elif _blueprint_depth(prompt) >= 4:
        score += 1
    if _contains_any(prompt, DEEP_READING_MARKERS):
        score += 1
    return max(1, min(10, score))


def _usefulness_score(prompt: str) -> int:
    """Score how actionable and purpose-driven the prompt is.  The old version
    used length as a proxy for usefulness, which over-rewarded long generic
    wrappers and under-rewarded tight, well-structured shorter prompts."""
    lowered = prompt.lower()
    score = 3
    # Has a clear role / persona
    if any(term in lowered for term in ["you are", "act as", "# role", "your role"]):
        score += 1
    # Has a clear objective or task statement
    if any(term in lowered for term in ["objective", "goal", "your job", "# objective", "# task"]):
        score += 1
    # Has explicit output control (format, schema, structure)
    if any(term in lowered for term in ["output format", "return", "format", "markdown", "json", "table"]):
        score += 1
    # Depth signals — length is still a reasonable proxy, but weighted less
    if len(prompt) > 500:
        score += 1
    if len(prompt) > 1800:
        score += 1
    # Self-verification step (quality check) significantly raises usefulness
    if any(term in lowered for term in ["quality check", "verify", "before finalizing", "quality bar"]):
        score += 1
    # Blueprint-level depth
    if _blueprint_depth(prompt) >= 8:
        score += 1
    if _contains_any(prompt, DEEP_READING_MARKERS):
        score += 1
    return max(1, min(10, score))


def score_prompt(prompt: str, critique: dict[str, Any] | None = None, tests: dict[str, Any] | None = None) -> dict[str, Any]:
    prompt = prompt.strip()
    critique = critique or {}
    tests = tests or {}

    criteria = {
        "clarity": _section_score(prompt),
        "specificity": _specificity_score(prompt),
        "completeness": min(10, _section_score(prompt) + (1 if len(prompt) > 900 else 0) + (1 if _blueprint_depth(prompt) >= 8 else 0)),
        "context_strength": _context_strength_score(prompt),
        "constraint_quality": _constraint_score(prompt),
        "output_control": _output_control_score(prompt),
        "safety": _safety_score(prompt),
        "usefulness": _usefulness_score(prompt),
    }

    penalties: list[str] = []
    if tests.get("high_risk_failures"):
        criteria["safety"] = max(1, criteria["safety"] - 2)
        penalties.append("Stress test found high-risk failure modes.")
    if critique.get("risk_level") == "high":
        criteria["clarity"] = max(1, criteria["clarity"] - 2)
        penalties.append("Critic marked this prompt as high risk.")
    policy = assess_prompt_policy(prompt)
    if policy.is_disallowed and not _contains_any(prompt, ["safe alternative", "refuse", "cannot help", "defensive"]):
        criteria["safety"] = 1
        criteria["usefulness"] = max(1, criteria["usefulness"] - 3)
        penalties.append(f"Policy layer detected risky terms: {', '.join(policy.matched_terms)}.")
    if "output format" not in prompt.lower():
        penalties.append("Output format is not explicit.")
    if _looks_like_generic_wrapper(prompt):
        criteria["specificity"] = max(1, criteria["specificity"] - 3)
        criteria["completeness"] = max(1, criteria["completeness"] - 3)
        criteria["context_strength"] = max(1, criteria["context_strength"] - 2)
        criteria["usefulness"] = max(1, criteria["usefulness"] - 2)
        penalties.append("Prompt appears to be a generic wrapper instead of a deep task-specific optimized prompt.")
    if not _contains_any(prompt, DEEP_READING_MARKERS):
        criteria["specificity"] = max(1, criteria["specificity"] - 2)
        criteria["context_strength"] = max(1, criteria["context_strength"] - 2)
        criteria["usefulness"] = max(1, criteria["usefulness"] - 1)
        penalties.append("Prompt lacks a deep task-reading section with implied requirements or hidden decisions.")
    if 900 < len(prompt) < 1800 and _blueprint_depth(prompt) < 5 and _contains_any(prompt, ["build", "system", "app", "agent", "api"]):
        criteria["completeness"] = max(1, criteria["completeness"] - 2)
        penalties.append("Complex system prompt lacks blueprint-level sections such as architecture, roadmap, database, testing, and safety.")
    if _looks_like_irrelevant_design_blueprint(prompt):
        criteria["specificity"] = max(1, criteria["specificity"] - 3)
        criteria["context_strength"] = max(1, criteria["context_strength"] - 3)
        criteria["usefulness"] = max(1, criteria["usefulness"] - 3)
        penalties.append("Design/CSS persona prompt includes unrelated system-architecture, database, terminal, API, or cybersecurity sections.")
    if _has_internal_builder_scaffolding(prompt):
        criteria["clarity"] = max(1, criteria["clarity"] - 2)
        criteria["specificity"] = max(1, criteria["specificity"] - 2)
        criteria["usefulness"] = max(1, criteria["usefulness"] - 2)
        penalties.append("Prompt exposes internal optimizer scaffolding such as model, memory, or preservation helper notes.")

    total = 0.0
    for key, weight in WEIGHTS.items():
        total += (criteria[key] / 10) * weight

    return {
        "criteria": criteria,
        "total": max(1, min(100, round(total))),
        "penalties": penalties,
    }
