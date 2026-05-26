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
    risky = [
        "ignore previous",
        "bypass",
        "jailbreak",
        "secret key",
        "api key",
        "password",
        "keylogger",
        "malware",
        "ransomware",
        "spyware",
        "credential theft",
        "exfiltrate",
        "evade detection",
        "disable antivirus",
    ]
    score = 9
    if _contains_any(prompt, risky):
        score -= 6
    if _contains_any(prompt, ["safety", "privacy", "do not invent", "do not reveal", "safe alternative", "refuse"]):
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
        "context_strength": 9 if _blueprint_depth(prompt) >= 8 else 8 if "context" in prompt.lower() else 5,
        "constraint_quality": 9 if _contains_any(prompt, ["constraints", "must", "avoid", "do not", "protect api keys"]) else 5,
        "output_control": _output_control_score(prompt),
        "safety": _safety_score(prompt),
        "usefulness": 9 if _blueprint_depth(prompt) >= 8 and len(prompt) > 1800 else 8 if len(prompt) > 500 else 6,
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
