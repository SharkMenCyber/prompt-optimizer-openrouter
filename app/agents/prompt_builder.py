import re
from typing import Any

from app.config import get_settings
from app.policy import assess_prompt_policy
from app.security import redact_text
from app.services.openrouter_client import OpenRouterClient
from app.utils.json_tools import compact_text


class PromptBuilderAgent:
    def __init__(self, client: OpenRouterClient):
        self.client = client

    def build_versions(
        self,
        raw_prompt: str,
        intent: dict[str, Any],
        context: dict[str, Any],
        clarification: dict[str, Any],
        version_count: int,
        target_model: str | None = None,
        model_profile: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        policy = assess_prompt_policy(raw_prompt, mode=get_settings().policy_mode)
        raw_prompt = redact_text(raw_prompt) or ""
        if policy.is_disallowed:
            return self._policy_redirect_versions(raw_prompt, policy.as_dict(), version_count)

        quality_mode = self._quality_mode(raw_prompt, intent)
        fallback_versions = self._local_versions(
            raw_prompt,
            intent,
            context,
            clarification,
            version_count,
            model_profile=model_profile,
            quality_mode=quality_mode,
        )
        fallback = {
            "versions": fallback_versions,
            "quality_mode": quality_mode,
        }
        mode_requirements = self._mode_requirements(quality_mode)
        result = self.client.chat_json(
            system_prompt=(
                "You are a senior prompt engineering architect. Your job is to rewrite rough user prompts "
                "into production-grade prompts that another advanced AI can follow. Do not answer the user's "
                "task. Build the prompt that will make another AI answer the task deeply. Avoid generic wrappers. "
                "For complex software, product, architecture, research, or system-building requests, produce "
                "blueprint-level prompts with architecture decisions, components, integrations, database/memory "
                "design, phase roadmaps, testing, safety/security controls, and exact output sections."
            ),
            user_prompt=f"""
Raw prompt:
{compact_text(raw_prompt)}

Intent:
{intent}

Context:
{context}

Clarification assumptions:
{clarification}

Model profile:
{model_profile or {}}

Create {version_count} distinct prompt versions.

Quality mode:
{quality_mode}

Requirements:
- Preserve the user's actual idea and wording where useful, but expand it into a complete expert prompt.
- Include domain-specific sections instead of only generic Role/Objectives/Instructions.
- Do not add architecture, database, API, terminal, cybersecurity, agent, roadmap, or research sections unless they are directly relevant to the raw prompt.
- Do not expose internal optimizer scaffolding in prompt_text. Never include target model names, optimization style labels, model-specific guidance sections, memory/reuse guidance sections, or "original idea to preserve" helper text.
- Follow these mode-specific requirements:
{mode_requirements}
- If research is relevant, require real open-source project research and tell the assistant not to invent tools.
- Include explicit constraints, output format, and quality checks.
- Make every version useful on its own. For advanced_system_blueprint only, minimum depth is about 1800 words.

Return JSON:
{{
  "versions": [
    {{"label": "v1_blueprint", "strategy": "advanced-blueprint", "prompt_text": "..."}}
  ]
}}
""",
            fallback=fallback,
            model=target_model,
            temperature=0.35,
            max_tokens=8500,
        )
        versions = result.get("versions", fallback_versions)
        source = result.get("source", "openrouter" if self.client.configured else "local_fallback")
        warning = result.get("warning")
        return self._normalize_versions(
            versions=versions,
            fallback_versions=fallback_versions,
            version_count=version_count,
            source=source,
            quality_mode=quality_mode,
            warning=warning,
        )

    def _local_versions(
        self,
        raw_prompt: str,
        intent: dict[str, Any],
        context: dict[str, Any],
        clarification: dict[str, Any],
        version_count: int,
        model_profile: dict[str, Any] | None = None,
        quality_mode: str | None = None,
    ) -> list[dict[str, str]]:
        if quality_mode == "advanced_system_blueprint":
            return self._blueprint_versions(
                raw_prompt=raw_prompt,
                intent=intent,
                context=context,
                clarification=clarification,
                version_count=version_count,
                model_profile=model_profile,
            )
        if quality_mode == "expert_persona_prompt":
            return self._persona_versions(
                raw_prompt=raw_prompt,
                intent=intent,
                context=context,
                clarification=clarification,
                version_count=version_count,
                model_profile=model_profile,
            )

        strategies = [
            ("v1_balanced", "balanced"),
            ("v2_detailed", "high-structure"),
            ("v3_critic_ready", "verification-heavy"),
            ("v4_concise", "compact"),
            ("v5_testable", "test-case-oriented"),
        ]
        versions: list[dict[str, str]] = []
        assumptions = "\n".join(f"- {item}" for item in clarification.get("assumptions", [])) or "- None."
        constraints = "\n".join(f"- {item}" for item in context.get("constraints", [])) or "- Stay faithful to the user's goal."
        profile = model_profile or {}
        profile_controls = "\n".join(
            f"- {item}" for item in profile.get("recommended_prompt_controls", [])
        ) or "- Keep output requirements concrete."

        for label, strategy in strategies[:version_count]:
            prompt_text = f"""# Role
You are an expert assistant specialized in {intent.get("task_type", "general")} tasks.

# Objective
Help the user accomplish this goal:
{raw_prompt.strip()}

# Context
{context.get("background", "Use the available user request as the primary source of truth.")}

# Assumptions
{assumptions}

# Instructions
1. Identify the user's real goal before producing the answer.
2. Fill small missing details with reasonable assumptions and state them briefly.
3. Break complex work into clear steps.
4. Prioritize correctness, usefulness, and directness.
5. Do not invent facts that are not provided or logically implied.

# Constraints
{constraints}

# Prompt Controls
{profile_controls}

# Output Format
Return a structured Markdown answer with:
1. Final Answer
2. Key Reasoning
3. Assumptions
4. Next Steps, only if useful

# Quality Check
Before finalizing, check that the answer is specific, complete, safe, and aligned with the original request."""
            if strategy == "compact":
                prompt_text = prompt_text.replace("2. Fill small missing details with reasonable assumptions and state them briefly.\n", "")
            if strategy == "verification-heavy":
                prompt_text += "\n\n# Verification\nList possible misunderstandings, then revise the answer to avoid them."
            versions.append(
                {
                    "label": label,
                    "strategy": strategy,
                    "prompt_text": prompt_text,
                    "builder_source": "local_fallback",
                    "quality_mode": quality_mode or "standard_prompt",
                }
            )
        return versions

    def _persona_versions(
        self,
        raw_prompt: str,
        intent: dict[str, Any],
        context: dict[str, Any],
        clarification: dict[str, Any],
        version_count: int,
        model_profile: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        strategies = [
            ("v1_persona_designer", "expert-persona"),
            ("v2_visual_workflow", "visual-input-workflow"),
            ("v3_code_output_focused", "css-html-output-control"),
            ("v4_concise_persona", "compact-role-prompt"),
            ("v5_quality_bar", "quality-heavy-design-review"),
        ]
        versions = []
        assumptions = "\n".join(f"- {item}" for item in clarification.get("assumptions", [])) or (
            "- The assistant should behave as a visual system designer and CSS specialist.\n"
            "- The assistant may work from either a written description or an image inspiration reference.\n"
            "- If an image or design goal is missing, ask only the minimum useful clarification questions."
        )
        constraints = self._persona_constraints(context)
        user_intent = self._persona_intent_to_preserve(raw_prompt, intent)
        for label, strategy in strategies[:version_count]:
            emphasis = self._persona_emphasis(strategy)
            prompt_text = f"""# Role
You are an elite visual system designer and CSS/HTML implementation specialist.

You create polished interfaces from rough ideas, screenshots, image inspiration, or your own design direction. You understand layout, spacing, typography, color systems, component states, responsive behavior, and production-quality CSS.

# Objective
Turn the user's design request into a visually impressive, usable interface or design system. If the user provides an image, analyze the visual style and recreate the relevant design language without copying unrelated details. If the user provides only an idea, create an original design direction that fits the product and audience.

# Original User Intent To Preserve
{user_intent}

# Capabilities
- Analyze visual inspiration and infer layout, spacing, typography, color, depth, hierarchy, and interaction style.
- Create original UI concepts when no image is provided.
- Produce clean HTML and CSS when code is requested.
- Explain design decisions in simple language when useful.
- Adapt the style to dashboards, tools, panels, landing sections, app screens, cards, forms, navigation, or full design systems.
- Improve rough UI ideas into polished, coherent interfaces.

# Design Workflow
1. Identify the type of interface or component the user wants.
2. Extract the visual style from the prompt or image inspiration.
3. Decide the layout, hierarchy, spacing, typography, color palette, and component states.
4. Build the design with practical CSS and semantic HTML when code is requested.
5. Make the result responsive and readable on desktop and mobile.
6. Check the final design for alignment, contrast, spacing, overflow, and visual polish.

# Visual Input Handling
- If an image is provided, describe the important visual traits before applying them.
- Use the image as inspiration for style, composition, spacing, colors, and mood.
- Do not claim exact pixel-perfect recreation unless exact measurements are provided.
- If the image is unclear, ask for one targeted clarification or proceed with stated assumptions.

# CSS And HTML Output Rules
- Prefer semantic HTML and modern CSS.
- Use CSS variables for reusable colors, spacing, shadows, and radii when helpful.
- Include responsive rules for smaller screens.
- Keep class names clear and practical.
- Avoid unnecessary frameworks unless the user asks for one.
- If the user asks for only design guidance, do not force code.
- If the user asks for code, return complete usable HTML/CSS or clearly separated snippets.

# Assumptions
{assumptions}

# Constraints
{constraints}

# Output Format
Return the response in the format that best matches the user's request:

1. If the user asks for code:
   - Design Summary
   - Complete HTML
   - Complete CSS
   - Responsive Notes
   - Quick Customization Tips

2. If the user asks for a design plan:
   - Visual Direction
   - Layout Plan
   - Typography And Color System
   - Component Details
   - Implementation Notes

3. If the user provides an image:
   - Visual Analysis
   - Design Translation
   - Implementation
   - Quality Checks

# Quality Bar
Before finalizing, verify that:
- the design matches the user's actual request
- the output is visually specific, not generic
- CSS choices are practical and coherent
- text will not overflow its containers
- spacing, contrast, and hierarchy feel intentional
- mobile behavior is considered
- unrelated system-building instructions are not included

# Style Emphasis
{emphasis}"""
            versions.append(
                {
                    "label": label,
                    "strategy": strategy,
                    "prompt_text": prompt_text,
                    "builder_source": "local_fallback",
                    "quality_mode": "expert_persona_prompt",
                }
            )
        return versions

    def _blueprint_versions(
        self,
        raw_prompt: str,
        intent: dict[str, Any],
        context: dict[str, Any],
        clarification: dict[str, Any],
        version_count: int,
        model_profile: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        strategies = [
            ("v1_blueprint", "advanced-blueprint"),
            ("v2_architecture_research", "architecture-and-open-source-research"),
            ("v3_build_roadmap", "phase-by-phase-builder"),
            ("v4_mvp_to_production", "mvp-to-production-plan"),
            ("v5_beginner_instructor", "beginner-friendly-technical-instructor"),
        ]
        versions = []
        role = self._blueprint_role(raw_prompt, intent)
        objective = self._blueprint_objective(raw_prompt, intent)
        integrations = self._detected_integrations(raw_prompt)
        assumptions = "\n".join(f"- {item}" for item in clarification.get("assumptions", [])) or (
            "- Proceed with reasonable assumptions for non-critical details.\n"
            "- Clearly separate assumptions from confirmed requirements.\n"
            "- Ask clarification questions only when a missing detail changes architecture, safety, or implementation."
        )
        constraints = "\n".join(f"- {item}" for item in context.get("constraints", [])) or (
            "- Do not invent tools, APIs, repositories, features, or capabilities.\n"
            "- Keep all implementation guidance legal, ethical, and authorization-bound.\n"
            "- Protect API keys and secrets.\n"
            "- Prefer practical beginner-buildable steps while preserving an advanced architecture."
        )
        integration_lines = "\n".join(f"- {item}" for item in integrations) or "- Identify useful integrations from the user's request."

        for label, strategy in strategies[:version_count]:
            emphasis = self._strategy_emphasis(strategy)
            prompt_text = f"""You are {role}

I want you to transform the following rough idea into a complete expert-level implementation blueprint.

## Project Brief

{raw_prompt.strip()}

---

## Main Objective

{objective}

The final response should help a beginner understand what to build, why each part exists, how the pieces connect, and how to implement the project phase by phase.

---

## Important Reality Rules

- Do not claim the system can magically self-improve, self-secure, or autonomously solve everything.
- Explain realistic improvement through saved history, feedback, tests, scoring, version comparison, logs, templates, and retrieval from successful past work.
- Do not invent fake open-source tools, fake APIs, fake documentation, or unsupported framework capabilities.
- If a feature depends on an external tool, explain the integration assumptions and limitations.
- Keep cybersecurity, terminal, OS, and automation features legal, ethical, user-approved, logged, and authorization-bound.
- Protect API keys, secrets, user files, and command execution permissions.

---

## Known Requirements And Integrations

{integration_lines}

---

## Assumptions

{assumptions}

---

## Constraints

{constraints}

---

## Required Analysis

Before giving the build plan, analyze the project in this order:

1. Restate the user's real goal in simple language.
2. Identify the target users and what they need to accomplish.
3. Identify hidden requirements, risks, and missing decisions.
4. Compare possible architectures and recommend the best practical path.
5. Explain what should be built first for an MVP and what should wait.
6. Explain how agents, tools, memory, and execution permissions should work together.
7. Explain what is realistic now and what belongs in a future version.

---

## Architecture Options To Compare

Compare realistic build paths that fit the user's idea. For each option, include pros, cons, difficulty, cost, scalability, and beginner suitability.

Include options such as:

- building from scratch
- extending an existing open-source platform
- creating a web app with a browser UI
- creating a desktop app
- using containers, virtual machines, or a controlled local runtime
- integrating agent frameworks and OpenAI-compatible model APIs

After comparing, recommend one practical path and explain why.

---

## Core System Design

Design the system with these sections:

1. High-level architecture
2. Frontend/UI modules
3. Backend/API modules
4. Agent orchestration layer
5. Model provider/API layer
6. Skill or plugin system
7. Memory/history/retrieval layer
8. Safe execution/tool layer
9. Project/file/workspace layer
10. Evaluation, testing, and feedback loop
11. Observability, logs, and admin controls
12. Security and permission boundaries

For each section, explain:

- purpose
- main features
- important files or modules
- data flow
- risks and limitations
- how to test it

---

## Agent Design

Design specialist agents that fit the project. For each agent include:

- name
- purpose
- inputs
- outputs
- permissions
- tools it may use
- safety limits
- example task
- success criteria

Include agents for planning, architecture, implementation, debugging, testing, documentation, security review, memory retrieval, skill creation, and controlled tool/terminal execution when relevant.

---

## Open-Source Research

Research existing open-source tools that could improve this system. Do not invent fake projects.

For each relevant project, provide:

- project name
- GitHub link
- what it does
- how it could help
- whether to integrate, fork, learn from, or avoid it
- limitations and risks
- how hard it would be to integrate

If current browsing is not available, clearly say what needs to be researched and provide a research checklist instead of pretending.

---

## Recommended Tech Stack

Recommend a practical stack with beginner and production paths:

- frontend framework
- editor/UI framework if relevant
- backend framework
- database for MVP
- database for production
- model API layer
- agent framework
- memory/vector search option
- sandbox/execution option
- deployment option
- logging/observability option

Explain why each tool is used and what alternatives exist.

---

## Database And Memory Design

Design tables or collections for the project. For each one include:

- purpose
- important fields
- example row
- privacy/security concerns

Include tables for users, projects, workspaces, agent sessions, agent messages, prompt/history records, skills/plugins, model configs, tool permissions, command logs, feedback, evaluations, and audit logs when relevant.

---

## Workflow Design

Show the main workflows step by step:

- user starts a task
- planner creates a plan
- agents choose tools and ask for approval
- files or project data are read
- implementation changes are proposed
- tests run
- results are summarized
- feedback is stored
- future runs retrieve useful history

Represent workflows with simple arrows or numbered steps.

---

## Phase-Based Roadmap

Break the build into phases from MVP to advanced production version.

For every phase include:

1. goal
2. features
3. tools needed
4. files to create
5. code examples
6. commands to run
7. how to test
8. common errors and fixes
9. completion checklist

Make the phases realistic. Start with a small usable MVP, then add agent workflows, memory, safety controls, integrations, and production packaging.

---

## Security And Safety Controls

Explain practical controls for:

- API key storage
- secret redaction
- safe command execution
- user approval before risky actions
- sandboxing
- file permissions
- audit logs
- role-based access
- cybersecurity lab boundaries
- prompt injection defense
- model output verification

---

## Output Format

Return the final answer in this exact structure:

1. Executive Summary
2. Architecture Options Comparison
3. Recommended Build Path
4. Core Features
5. System Architecture
6. Agent Design
7. API / Model Provider Integration
8. Skill / Plugin / Memory Design
9. Safe Tool And Execution Layer
10. Open-Source Tools Research
11. Recommended Tech Stack
12. Database / Memory Design
13. Workflow Diagrams
14. Phase-by-Phase Roadmap
15. Beginner Build Plan
16. Testing And Evaluation Plan
17. Security And Safety Controls
18. Risks, Limitations, And What Is Not Possible Yet
19. Final Recommendation

---

## Style Rules

- Use simple language.
- Do not skip steps.
- Assume the reader is new to building advanced AI systems.
- Be advanced but realistic.
- Give practical implementation details.
- Include code examples only where they help.
- Use tables when comparing options or tools.
- Be specific enough that a developer can begin building from the answer.
- {emphasis}

---

## Final Quality Check

Before finalizing, verify that the answer:

- preserves the original idea
- expands vague requirements into concrete architecture
- avoids generic advice
- includes implementation steps
- includes testing and safety controls
- clearly separates assumptions from facts
- does not invent unsupported tools or capabilities
- gives a practical beginner-friendly path forward"""
            versions.append(
                {
                    "label": label,
                    "strategy": strategy,
                    "prompt_text": prompt_text,
                    "builder_source": "local_fallback",
                    "quality_mode": "advanced_system_blueprint",
                }
            )
        return versions

    def _normalize_versions(
        self,
        versions: Any,
        fallback_versions: list[dict[str, str]],
        version_count: int,
        source: str,
        quality_mode: str,
        warning: str | None = None,
    ) -> list[dict[str, str]]:
        if not isinstance(versions, list):
            versions = []

        normalized = []
        for index in range(version_count):
            fallback = fallback_versions[index] if index < len(fallback_versions) else fallback_versions[-1]
            candidate = versions[index] if index < len(versions) and isinstance(versions[index], dict) else {}
            prompt_text = str(candidate.get("prompt_text") or "").strip()
            use_fallback = not prompt_text or self._too_shallow(prompt_text, quality_mode)
            item = dict(fallback if use_fallback else candidate)
            item.setdefault("label", fallback.get("label", f"v{index + 1}"))
            item.setdefault("strategy", fallback.get("strategy", "advanced"))
            item["prompt_text"] = self._clean_internal_scaffolding(
                str(item.get("prompt_text", fallback["prompt_text"])),
                quality_mode=quality_mode,
            )
            item["builder_source"] = "local_fallback_quality_guard" if use_fallback and source != "local_fallback" else source
            item["quality_mode"] = quality_mode
            if warning:
                item["builder_warning"] = warning
            if use_fallback and source != "local_fallback":
                item["builder_warning"] = (
                    "AI builder output was missing, too shallow, or off-topic, so the quality guard used "
                    f"the focused local builder for {quality_mode}."
                )
            normalized.append(item)
        return normalized

    def _quality_mode(self, raw_prompt: str, intent: dict[str, Any]) -> str:
        text = f"{raw_prompt} {intent.get('task_type', '')} {intent.get('expected_output', '')}".lower()
        if self._is_persona_prompt(text):
            return "expert_persona_prompt"
        # Two tiers, because counting all build-related words equally let three
        # incidental common words ("build a simple API dashboard") force the
        # heavy 1800-word blueprint. Structural terms signal a real system build
        # on their own; supporting terms only count when paired with structure.
        structural_terms = [
            "system",
            "platform",
            "ide",
            "agent",
            "framework",
            "architecture",
            "database",
            "roadmap",
            "open-source",
            "full-stack",
            "software",
        ]
        supporting_terms = [
            "build",
            "create",
            "design",
            "app",
            "api",
            "dashboard",
            "github",
        ]
        structural_hits = sum(1 for term in structural_terms if term in text)
        supporting_hits = sum(1 for term in supporting_terms if term in text)
        is_blueprint = (
            intent.get("task_type") in {"software", "research"}
            or structural_hits >= 2
            or (structural_hits >= 1 and supporting_hits >= 2)
        )
        if is_blueprint:
            return "advanced_system_blueprint"
        return "standard_prompt"

    def _too_shallow(self, prompt_text: str, quality_mode: str) -> bool:
        lowered = prompt_text.lower()
        generic_markers = [
            "help the user accomplish this goal",
            "you are an expert assistant specialized in",
            "return a structured markdown answer with",
        ]
        if quality_mode == "advanced_system_blueprint":
            required_sections = [
                "architecture options",
                "agent design",
                "recommended tech stack",
                "database",
                "roadmap",
                "security",
                "open-source",
                "output format",
            ]
            required_markers = [
                "architecture",
                "agent",
                "tech stack",
                "database",
                "roadmap",
                "security",
                "testing",
                "phase",
                "workflow",
                "open-source",
            ]
            marker_hits = sum(1 for marker in required_markers if marker in lowered)
            missing_required_sections = [section for section in required_sections if section not in lowered]
            leaked_internal_sections = [
                "additional model-specific guidance",
                "model-specific guidance",
                "target model:",
                "optimization style:",
                "memory and reuse guidance",
                "original user idea to preserve",
                "this must not become a generic answer",
            ]
            return (
                len(prompt_text) < 2400
                or marker_hits < 6
                or bool(missing_required_sections)
                or any(section in lowered for section in leaked_internal_sections)
            )
        if quality_mode == "expert_persona_prompt":
            required_sections = [
                "role",
                "objective",
                "capabilities",
                "design workflow",
                "visual input",
                "css",
                "output format",
                "quality",
            ]
            unrelated_sections = [
                "architecture options",
                "database",
                "api key",
                "safe terminal",
                "cybersecurity lab",
                "agent design",
                "open-source tools research",
                "phase-by-phase roadmap",
                "model-specific guidance",
                "target model:",
                "optimization style:",
            ]
            missing_required_sections = [section for section in required_sections if section not in lowered]
            unrelated_hits = [section for section in unrelated_sections if section in lowered]
            return len(prompt_text) < 1400 or bool(missing_required_sections) or bool(unrelated_hits)
        return len(prompt_text) < 650 and any(marker in lowered for marker in generic_markers)

    def _is_persona_prompt(self, text: str) -> bool:
        explicit_design_prompt_request = any(
            marker in text
            for marker in [
                "create a prompt for an expert css designer",
                "prompt for an expert css designer",
                "expert css designer",
                "expert css/html",
                "expert visual system designer",
                "expert system designer",
                "ai model to act as an expert css designer",
                "act as an expert css designer",
            ]
        )
        design_output_request = any(
            marker in text
            for marker in [
                "clean html and css",
                "html and css",
                "dashboard screenshot",
                "from a screenshot",
                "analyze a screenshot",
                "analyze the screenshot",
                "improve a dashboard",
                "dashboard redesign",
                "visual redesign",
            ]
        )
        if explicit_design_prompt_request and design_output_request:
            return True

        persona_markers = [
            "you are",
            "you're",
            "your a",
            "youre a",
            "act as",
            "behave as",
            "persona",
            "system prompt",
            "assistant specialized",
            "expert assistant",
            "expert designer",
            "expert css designer",
            "expert system designer",
        ]
        visual_markers = [
            "css",
            "html",
            "designer",
            "design",
            "screenshot",
            "dashboard",
            "visual",
            "picture",
            "image",
            "inspiration",
            "look",
            "amazing",
            "interface",
            "ui",
        ]
        build_markers = [
            "build an app",
            "build a system",
            "create an app",
            "create a system",
            "database",
            "backend",
            "api integration",
            "roadmap",
            "phase",
        ]
        return (
            any(marker in text for marker in persona_markers)
            and any(marker in text for marker in visual_markers)
            and not any(marker in text for marker in build_markers)
        )

    def _persona_intent_to_preserve(self, raw_prompt: str, intent: dict[str, Any]) -> str:
        text = raw_prompt.strip()
        brief_match = re.search(
            r"##\s*Project Brief\s*\n+(.*?)(?=\n---|\n##\s|\Z)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if brief_match:
            text = brief_match.group(1).strip()

        direct_patterns = [
            r"(Create a prompt for an expert CSS designer[^.\n]*(?:\.[^\n]*)?)",
            r"(prompt for an expert CSS designer[^.\n]*(?:\.[^\n]*)?)",
            r"(expert CSS designer[^.\n]*(?:\.[^\n]*)?)",
        ]
        for pattern in direct_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                text = match.group(1).strip()
                break

        if len(text) > 700:
            goal = str(intent.get("goal") or "").strip()
            if goal and len(goal) < len(text):
                text = goal
        return compact_text(text, limit=700)

    def _mode_requirements(self, quality_mode: str) -> str:
        if quality_mode == "advanced_system_blueprint":
            return (
                "- This is a system/software blueprint prompt. Include architecture options, recommended path, "
                "core features, agent/component roles, integrations, tech stack, database or memory design, "
                "workflow, phase-by-phase roadmap, testing, security, and beginner build plan."
            )
        if quality_mode == "expert_persona_prompt":
            return (
                "- This is a persona/instruction prompt, not a software architecture build. Focus on role, "
                "design capabilities, visual input handling, CSS/HTML output rules, interaction workflow, "
                "constraints, output formats, and visual quality checks. Do not include architecture options, "
                "database design, API key storage, terminal execution, cybersecurity labs, open-source research, "
                "phase roadmaps, model identifiers, or model-specific guidance unless the raw prompt explicitly asks for them."
            )
        return "- This is a standard prompt rewrite. Keep the structure specific to the user's actual task."

    def _clean_internal_scaffolding(self, prompt_text: str, quality_mode: str) -> str:
        """Remove builder-only helper sections that should never appear in final prompts."""
        text = prompt_text.strip()
        block_patterns = [
            r"\n?#{1,6}\s*Model-Specific Guidance\s*\n.*?(?=\n#{1,6}\s|\n---|\Z)",
            r"\n?Additional model-specific guidance:\s*\n.*?(?=\n#{1,6}\s|\n---|\Z)",
            r"\n?Memory and reuse guidance:\s*\n.*?(?=\n#{1,6}\s|\n---|\Z)",
        ]
        if quality_mode == "advanced_system_blueprint":
            block_patterns.extend(
                [
                    r"\n?Original user idea to preserve:\s*\n.*?(?=\n---|\n#{1,6}\s|\Z)",
                    r"\n?This must NOT become a generic answer\..*?(?=\n---|\n#{1,6}\s|\Z)",
                ]
            )
        for pattern in block_patterns:
            text = re.sub(pattern, "\n", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"(?:\n\s*---\s*){2,}", "\n\n---", text)
        return text.strip()

    def _blueprint_role(self, raw_prompt: str, intent: dict[str, Any]) -> str:
        text = raw_prompt.lower()
        roles = ["an advanced AI systems architect", "prompt engineering researcher", "autonomous agent designer"]
        if "ide" in text or "editor" in text:
            roles.insert(0, "an advanced IDE architect")
        if "cyber" in text or "kali" in text or "security" in text:
            roles.append("cybersecurity lab designer")
        if any(word in text for word in ["beginner", "new", "step by step", "explain"]):
            roles.append("beginner-friendly full-stack instructor")
        else:
            roles.append("beginner-friendly technical instructor")
        return ", ".join(dict.fromkeys(roles)) + "."

    def _blueprint_objective(self, raw_prompt: str, intent: dict[str, Any]) -> str:
        goal = intent.get("goal") or raw_prompt.strip()
        expected = intent.get("expected_output") or "a complete implementation blueprint"
        return (
            "Design a complete, realistic, beginner-friendly but advanced blueprint for this project: "
            f"{goal}\n\nThe expected output is {expected}."
        )

    def _detected_integrations(self, raw_prompt: str) -> list[str]:
        text = raw_prompt.lower()
        integrations = []
        known = {
            "Hermes Agent": ["hermes"],
            "OpenRouter API": ["openrouter"],
            "OpenRouter or other OpenAI-compatible APIs": ["openrouter", "openai-compatible", "ai api", "llm api"],
            "Kali Linux or a controlled Linux lab environment": ["kali", "linux"],
            "Monaco Editor or a similar code editor engine": ["monaco", "ide", "editor"],
            "Skill/plugin system with versioned reusable instructions": ["skill", "plugin"],
            "Open-source GitHub tools, with real repository verification": ["github", "open-source", "open source"],
            "Safe terminal/tool execution with approval, logging, and sandboxing": ["terminal", "command", "shell", "os"],
        }
        for label, needles in known.items():
            if any(needle in text for needle in needles):
                integrations.append(label)
        return integrations

    def _persona_constraints(self, context: dict[str, Any]) -> str:
        raw_constraints = context.get("constraints") if isinstance(context, dict) else []
        if not isinstance(raw_constraints, list):
            raw_constraints = []
        allowed_terms = [
            "css",
            "html",
            "style",
            "design",
            "visual",
            "image",
            "picture",
            "responsive",
            "aesthetic",
            "language",
            "output",
            "complete",
            "omit",
            "links",
            "numbered",
        ]
        blocked_terms = [
            "uncensored",
            "api key",
            "terminal",
            "database",
            "cybersecurity",
            "kali",
            "agent",
            "roadmap",
            "backend",
            "audit",
            "sandbox",
        ]
        filtered = []
        for item in raw_constraints:
            text = str(item).strip()
            lowered = text.lower()
            if not text:
                continue
            if any(term in lowered for term in blocked_terms):
                continue
            if any(term in lowered for term in allowed_terms):
                filtered.append(f"- {text}")
        defaults = [
            "- Stay focused on visual design, CSS, HTML, layout, and usability.",
            "- Do not add unrelated architecture, backend, database, agent, API, terminal, or cybersecurity instructions.",
            "- If a requested design detail is missing, state a reasonable design assumption or ask one focused question.",
            "- Keep the final answer practical and directly usable for design implementation.",
        ]
        return "\n".join(filtered or defaults)

    def _strategy_emphasis(self, strategy: str) -> str:
        if strategy == "architecture-and-open-source-research":
            return "Emphasize architecture comparison, open-source tool research, integration decisions, and limitations."
        if strategy == "phase-by-phase-builder":
            return "Emphasize concrete phases, files to create, commands, tests, common errors, and completion checklists."
        if strategy == "mvp-to-production-plan":
            return "Emphasize the path from small MVP to production hardening, deployment, observability, and maintainability."
        if strategy == "beginner-friendly-technical-instructor":
            return "Explain terms simply and guide the reader step by step without dumbing down the architecture."
        return "Balance architecture, implementation, research, safety, testing, and roadmap detail."

    def _persona_emphasis(self, strategy: str) -> str:
        if strategy == "visual-input-workflow":
            return "Emphasize how to analyze image inspiration and translate it into layout, color, typography, and CSS."
        if strategy == "css-html-output-control":
            return "Emphasize complete usable HTML/CSS output, responsive behavior, and clean implementation details."
        if strategy == "compact-role-prompt":
            return "Keep the persona prompt concise while preserving strong visual design and CSS behavior rules."
        if strategy == "quality-heavy-design-review":
            return "Emphasize visual QA: spacing, hierarchy, contrast, responsiveness, overflow, and polish."
        return "Balance visual creativity, practical CSS implementation, image-inspired design, and clear output control."

    def _policy_redirect_versions(
        self,
        raw_prompt: str,
        policy: dict[str, Any],
        version_count: int,
    ) -> list[dict[str, str]]:
        strategies = [
            ("v1_policy_redirect", "policy-redirection"),
            ("v2_defensive_learning", "defensive-education"),
            ("v3_policy_bounded", "policy-bounded"),
            ("v4_incident_response", "defensive-workflow"),
            ("v5_security_review", "review-and-hardening"),
        ]
        matched = ", ".join(policy.get("matched_terms") or ["disallowed intent"])
        versions = []
        for label, strategy in strategies[:version_count]:
            prompt_text = f"""# Role
You are a security-aware AI assistant that helps users safely.

# Objective
The user request contains disallowed security-abuse intent:
{raw_prompt.strip()}

Your job is to avoid improving or operationalizing harmful instructions. Redirect the user toward safe, defensive, educational, or authorized alternatives.

# Policy Context
Policy mode: {policy.get("mode") or "standard"}
Detected risk category: {policy.get("category") or "unknown"}
Detected risky terms: {matched}

# Instructions
1. Do not provide instructions, code, workflows, or optimization details that enable malware, credential theft, stealth, unauthorized access, or abuse.
2. Briefly explain that you cannot help create or improve harmful instructions.
3. Offer safe alternatives such as threat modeling, defensive detection, secure coding, incident response, lab-only ethics, or how to protect systems from the described threat.
4. If the user claims authorization, ask for defensive scope and constraints before giving any technical help.
5. Keep the response practical, calm, and useful.

# Constraints
- Do not include evasion, persistence, credential capture, exfiltration, or stealth steps.
- Do not transform the unsafe request into a stronger harmful prompt.
- Keep any cybersecurity guidance defensive and authorization-bound.

# Output Format
Return Markdown with:
1. Safety Boundary
2. Safe Alternative Prompt
3. Defensive Checklist
4. Clarifying Questions for Authorized Work

# Quality Check
Before finalizing, verify that the prompt cannot be used as a direct guide for harm and that it gives the user a constructive safe path."""
            if strategy == "defensive-education":
                prompt_text += "\n\n# Emphasis\nFocus on learning how to detect, prevent, and report this class of threat."
            if strategy == "defensive-workflow":
                prompt_text += "\n\n# Emphasis\nFrame the answer as an incident-response and system-hardening workflow."
            versions.append(
                {
                    "label": label,
                    "strategy": strategy,
                    "prompt_text": prompt_text,
                    "builder_source": "local_policy_redirect",
                    "quality_mode": "policy_redirect",
                }
            )
        return versions
