import re
from typing import Any

from app.services.openrouter_client import OpenRouterClient
from app.utils.json_tools import compact_text


class DeepInterpreterAgent:
    def __init__(self, client: OpenRouterClient):
        self.client = client

    def interpret(
        self,
        raw_prompt: str,
        intent: dict[str, Any],
        target_model: str | None = None,
    ) -> dict[str, Any]:
        fallback = self._local_interpret(raw_prompt, intent)
        result = self.client.chat_json(
            system_prompt=(
                "You are the deep-interpretation agent in a prompt-optimization pipeline. "
                "Your job is not to rewrite the prompt. Your job is to read the raw request like a "
                "domain expert, infer what the user is really trying to accomplish, and identify the "
                "specific depth that the final optimized prompt must force. Do not pad with generic "
                "prompt-engineering advice. Every field must be grounded in the user's wording, likely "
                "intent, task type, and realistic best practice.\n"
                "Return strict JSON only."
            ),
            user_prompt=f"""
Raw prompt:
{compact_text(raw_prompt, limit=9000)}

Intent analysis:
{intent}

Return JSON with these fields:
- essence: one sentence capturing the user's real aim
- literal_request: what the user explicitly asked for
- deeper_intent: what the user likely needs beneath the literal wording
- domain_signals: concrete topics, tools, roles, constraints, or domain clues found in the prompt
- implied_requirements: requirements the prompt strongly implies but does not spell out
- hidden_decisions: decisions the downstream AI should surface instead of silently assuming
- expansion_targets: areas where the optimized prompt should go deeper, specific to this request
- quality_dimensions: what a strong answer to this prompt must optimize for
- likely_failure_modes: ways a generic answer would fail this user
- constraints_to_preserve: boundaries, wording, preferences, or scope that should not be lost
- prompt_angle: the best framing strategy for the final optimized prompt
""",
            fallback=fallback,
            model=target_model,
            temperature=0.15,
            # This agent keeps the model's reasoning phase (it drives the depth),
            # so its budget must cover hidden reasoning tokens (~500-900) PLUS the
            # 11-field JSON answer. 2200 occasionally truncated the JSON mid-object
            # and forced a local fallback; 4000 leaves comfortable headroom.
            max_tokens=4000,
        )
        return self._normalize(result, fallback)

    def _local_interpret(self, raw_prompt: str, intent: dict[str, Any]) -> dict[str, Any]:
        text = raw_prompt.strip()
        lowered = text.lower()
        task_type = str(intent.get("task_type") or "general")
        domain_signals = self._signals(lowered)
        expected_output = str(intent.get("expected_output") or "").strip()
        deeper_intent = expected_output or "A stronger prompt that deeply understands the user's request."
        if not expected_output or "improved prompt" in expected_output.lower():
            deeper_intent = "A stronger prompt that deeply understands the user's request."

        implied = [
            "Preserve the user's actual idea instead of replacing it with a generic assistant template.",
            "Turn vague wording into concrete instructions, assumptions, constraints, and output expectations.",
            "Make the downstream AI explain important tradeoffs instead of silently choosing a path.",
        ]
        expansion_targets = [
            "Clarify what the user is trying to achieve and who the output is for.",
            "Add task-specific criteria for depth, correctness, and usefulness.",
            "Force the downstream answer to address risks, edge cases, and missing decisions.",
        ]
        hidden_decisions = [
            "What scope should the answer cover?",
            "What output format will be easiest for the user to use?",
            "Which assumptions are safe, and which require clarification?",
        ]
        likely_failure_modes = [
            "The answer becomes a polished but generic Role/Objectives/Instructions wrapper.",
            "The answer misses domain-specific implications in the raw wording.",
            "The answer hides assumptions instead of naming them.",
        ]

        if task_type == "software" or any(term in lowered for term in ["app", "system", "agent", "api", "desktop", "database"]):
            deeper_intent = (
                "A realistic implementation blueprint that turns the rough software idea into concrete "
                "architecture, workflows, permissions, memory, testing, and build phases."
            )
            implied.extend(
                [
                    "Define concrete modules, data flow, integrations, storage, error handling, and testing.",
                    "Separate MVP behavior from advanced or production behavior.",
                    "Include realistic security, permissions, and operational limits.",
                ]
            )
            expansion_targets.extend(
                [
                    "Architecture decisions and tradeoffs.",
                    "Data model, API boundaries, and integration assumptions.",
                    "Build phases with verification steps and failure handling.",
                ]
            )
            hidden_decisions.extend(
                [
                    "Which platform and runtime should be targeted first?",
                    "What should be built locally, what should use external services, and what should be deferred?",
                    "How should secrets, file access, memory, and user approvals be handled?",
                ]
            )
        elif task_type == "creative" or any(term in lowered for term in ["design", "ui", "css", "image", "visual"]):
            deeper_intent = (
                "A visually specific design or implementation prompt that translates the user's rough style "
                "goal into layout, typography, color, states, and responsive behavior."
            )
            implied.extend(
                [
                    "Translate style goals into layout, hierarchy, typography, color, spacing, states, and responsive behavior.",
                    "Keep the output visually specific and implementable instead of mood-board vague.",
                ]
            )
            expansion_targets.extend(
                [
                    "Visual direction and component behavior.",
                    "Responsive layout rules and polish checks.",
                    "Concrete implementation output when code is requested.",
                ]
            )
        elif task_type == "research" or any(term in lowered for term in ["research", "compare", "sources", "github"]):
            deeper_intent = (
                "A research prompt that forces source verification, meaningful comparison criteria, tradeoffs, "
                "and a recommendation grounded in the user's goal."
            )
            implied.extend(
                [
                    "Require verifiable sources and prevent invented projects, claims, or citations.",
                    "Compare options with criteria that match the user's goal.",
                ]
            )
            expansion_targets.extend(
                [
                    "Evaluation criteria.",
                    "Source verification rules.",
                    "Tradeoffs, limitations, and recommendation logic.",
                ]
            )

        return {
            "essence": intent.get("goal") or text,
            "literal_request": text,
            "deeper_intent": deeper_intent,
            "domain_signals": domain_signals,
            "implied_requirements": implied,
            "hidden_decisions": hidden_decisions,
            "expansion_targets": expansion_targets,
            "quality_dimensions": [
                "Specificity",
                "Domain relevance",
                "Completeness",
                "Usability",
                "Assumption transparency",
                "Safety and realism",
            ],
            "likely_failure_modes": likely_failure_modes,
            "constraints_to_preserve": intent.get("constraints") or ["Stay faithful to the raw request."],
            "prompt_angle": "Deep task brief with domain-specific requirements, hidden decisions, and output controls.",
            "source": "local_fallback",
        }

    def _signals(self, lowered: str) -> list[str]:
        markers = [
            "app",
            "api",
            "agent",
            "assistant",
            "coding",
            "coder",
            "desktop",
            "files",
            "local",
            "web",
            "database",
            "memory",
            "openrouter",
            "hermes",
            "prompt",
            "ui",
            "css",
            "research",
            "github",
            "security",
            "beginner",
            "project",
            "projects",
            "tool",
            "workflow",
        ]
        hits = [marker for marker in markers if re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", lowered)]
        return hits or ["general task requirements"]

    def _normalize(self, result: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            result = {}
        normalized = dict(fallback)
        normalized.update({key: value for key, value in result.items() if value not in (None, "")})

        for key in [
            "domain_signals",
            "implied_requirements",
            "hidden_decisions",
            "expansion_targets",
            "quality_dimensions",
            "likely_failure_modes",
            "constraints_to_preserve",
        ]:
            normalized[key] = self._string_list(normalized.get(key), fallback.get(key, []))

        for key in ["essence", "literal_request", "deeper_intent", "prompt_angle"]:
            value = str(normalized.get(key) or fallback.get(key) or "").strip()
            normalized[key] = value

        normalized.setdefault("source", result.get("source", "openrouter") if isinstance(result, dict) else "local_fallback")
        return normalized

    def _string_list(self, value: Any, default: Any) -> list[str]:
        if isinstance(value, list):
            items = value
        elif value:
            items = [value]
        else:
            items = default if isinstance(default, list) else [default]

        normalized: list[str] = []
        for item in items:
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("requirement") or item.get("decision") or item.get("name") or "").strip()
            else:
                text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized or [str(default).strip() or "Use the raw prompt as the source of truth."]
