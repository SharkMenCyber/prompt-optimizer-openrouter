import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

from app.agents.adversarial_tester import AdversarialTesterAgent
from app.agents.clarification import ClarificationAgent
from app.agents.context_engineer import ContextEngineerAgent
from app.agents.deep_interpreter import DeepInterpreterAgent
from app.agents.hermes_orchestrator import HermesOrchestratorAgent
from app.agents.intent_analyzer import IntentAnalyzerAgent
from app.agents.memory_agent import MemoryAgent
from app.agents.missing_info_detector import MissingInformationDetectorAgent
from app.agents.prompt_builder import PromptBuilderAgent
from app.agents.prompt_critic import PromptCriticAgent
from app.agents.prompt_scorer import PromptScoringAgent
from app.agents.version_comparator import VersionComparisonAgent
from app.config import get_settings
from app.db.repository import PromptRepository
from app.model_profiles import profile_for_model
from app.policy import assess_prompt_policy
from app.schemas import OptimizeRequest
from app.security import contains_secret, redact_text, redact_value, safe_error_message
from app.services.openrouter_client import OpenRouterClient
from app.utils.json_tools import compact_text


T = TypeVar("T")


class PromptOptimizationPipeline:
    def __init__(self, repository: PromptRepository | None = None, client: OpenRouterClient | None = None):
        self.repository = repository or PromptRepository()
        self.client = client or OpenRouterClient()
        self.intent_analyzer = IntentAnalyzerAgent(self.client)
        self.deep_interpreter = DeepInterpreterAgent(self.client)
        self.context_engineer = ContextEngineerAgent(self.client)
        self.missing_detector = MissingInformationDetectorAgent(self.client)
        self.clarifier = ClarificationAgent()
        self.builder = PromptBuilderAgent(self.client)
        self.critic = PromptCriticAgent(self.client)
        self.tester = AdversarialTesterAgent(self.client)
        self.scorer = PromptScoringAgent(self.client)
        self.comparator = VersionComparisonAgent()
        self.memory = MemoryAgent(self.repository)
        self.hermes_orchestrator = HermesOrchestratorAgent()
        # Optional live-progress sink. When set (by the streaming endpoint), each
        # agent step emits start/done events so the UI can show what's running.
        self._progress: Callable[[dict[str, Any]], None] | None = None

    def _emit(self, event: dict[str, Any]) -> None:
        callback = self._progress
        if callback is None:
            return
        try:
            callback(event)
        except Exception:
            # Progress reporting must never break the optimization run.
            pass

    def run(self, request: OptimizeRequest, progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        self._progress = progress
        # A follow-up turn refines the previous winning prompt. That is an edit,
        # not a build-from-scratch, so it takes a focused path instead of the
        # full expand pipeline (which would treat the edit instruction as a new
        # idea and bury it in a blueprint template).
        if request.prior_prompt and request.prior_prompt.strip():
            return self.refine(request)

        run_trace: list[dict[str, Any]] = []
        submitted_prompt = request.raw_prompt.strip()
        if contains_secret(submitted_prompt):
            raw_prompt = self._trace_step(
                run_trace,
                "Secret Redaction",
                "Remove likely API keys, tokens, and passwords before storage or model calls.",
                lambda: redact_text(submitted_prompt) or "",
            )
        else:
            raw_prompt = submitted_prompt
        requested_model = request.target_model
        target_model = self._trace_step(
            run_trace,
            "Model Selector",
            "Select the OpenRouter model for this optimization run.",
            lambda: self.client.select_model(requested_model) if self.client.configured else requested_model,
        )
        model_profile = self._trace_step(
            run_trace,
            "Model Profile Agent",
            "Select prompt-shaping guidance for the target model family and capabilities.",
            lambda: profile_for_model(target_model),
        )

        policy = self._trace_step(
            run_trace,
            "Policy Layer",
            "Apply the project policy for disallowed abuse requests before optimization.",
            lambda: assess_prompt_policy(raw_prompt, mode=get_settings().policy_mode).as_dict(),
        )

        hermes_plan = None
        if request.use_hermes and not policy.get("is_disallowed"):
            hermes_plan = self._trace_step(
                run_trace,
                "Hermes Orchestrator",
                "Create a high-level run strategy before specialist agents execute.",
                lambda: self.hermes_orchestrator.plan(raw_prompt, request.versions),
            )
        elif request.use_hermes:
            self._trace_skip(
                run_trace,
                "Hermes Orchestrator",
                "Skipped because the policy layer redirected this request before orchestration.",
            )
        else:
            self._trace_skip(
                run_trace,
                "Hermes Orchestrator",
                "Skipped because Hermes orchestration was not enabled for this run.",
            )

        if policy.get("is_disallowed"):
            intent = self._trace_step(
                run_trace,
                "Intent Analyzer Agent",
                "Use a local policy intent instead of sending disallowed optimization details to the model.",
                lambda: {
                    "goal": "Redirect disallowed prompt optimization request to a safe alternative.",
                    "task_type": "policy_redirect",
                    "target_platform": target_model or "auto",
                    "hidden_requirements": [
                        "Do not strengthen harmful instructions.",
                        "Offer defensive, educational, or authorized alternatives.",
                    ],
                    "policy": policy,
                },
            )
            deep_interpretation = self._trace_step(
                run_trace,
                "Deep Interpreter Agent",
                "Create a safe redirection reading without deepening disallowed instructions.",
                lambda: {
                    "essence": "The request should be redirected to safe, defensive, or educational help.",
                    "literal_request": "[redacted by policy layer]",
                    "deeper_intent": "Avoid strengthening harmful content while preserving a constructive path.",
                    "domain_signals": ["policy_redirect"],
                    "implied_requirements": [
                        "Do not optimize harmful instructions.",
                        "Offer a defensive or authorization-bound alternative.",
                    ],
                    "hidden_decisions": ["Which safe alternative best matches the user's broader goal?"],
                    "expansion_targets": ["Safety boundary", "Defensive checklist", "Authorized-work clarification"],
                    "quality_dimensions": ["Safety", "Usefulness", "Policy compliance"],
                    "likely_failure_modes": ["Accidentally improving the harmful request."],
                    "constraints_to_preserve": ["Do not provide operational abuse guidance."],
                    "prompt_angle": "Policy-bounded redirection prompt.",
                    "source": "local_policy_redirect",
                },
            )
            memory_matches = self._trace_step(
                run_trace,
                "Memory Agent",
                "Skip retrieval for disallowed prompts so risky prior prompts are not reused.",
                lambda: [],
            )
            context = self._trace_step(
                run_trace,
                "Context Engineer Agent",
                "Create redirection context for disallowed prompt optimization requests.",
                lambda: {
                    "background": policy.get("guidance"),
                    "constraints": [
                        "Do not optimize or operationalize disallowed instructions.",
                        "Do not provide malware, credential theft, evasion, or unauthorized access guidance.",
                        "Redirect to defensive, educational, or authorization-bound alternatives.",
                    ],
                    "assumptions": [
                        "The request is disallowed by the local policy layer.",
                        "A safe redirect is more appropriate than clarification.",
                    ],
                },
            )
            missing_info = self._trace_step(
                run_trace,
                "Missing Information Detector",
                "Mark disallowed requests as requiring redirection instead of more detail.",
                lambda: {
                    "missing": [],
                    "critical_missing": [],
                    "can_continue": True,
                    "policy_redirect": True,
                },
            )
            clarification = self._trace_step(
                run_trace,
                "Clarification Agent",
                "Continue with a safe redirect without asking for details that could increase risk.",
                lambda: {
                    "should_ask_user": False,
                    "questions": [],
                    "assumptions": [
                        "Proceed with a safe redirect instead of optimizing the disallowed request."
                    ],
                },
            )
        else:
            intent = self._trace_step(
                run_trace,
                "Intent Analyzer Agent",
                "Detect goal, task type, audience, target platform, and hidden requirements.",
                lambda: self.intent_analyzer.analyze(raw_prompt, target_model=target_model),
            )
            deep_interpretation = self._trace_step(
                run_trace,
                "Deep Interpreter Agent",
                "Read the raw prompt for underlying intent, implied requirements, hidden decisions, and failure modes.",
                lambda: self.deep_interpreter.interpret(raw_prompt, intent=intent, target_model=target_model),
            )
            memory_matches = self._trace_step(
                run_trace,
                "Memory Agent",
                "Retrieve successful prior prompts and feedback patterns relevant to this request.",
                lambda: self.memory.retrieve_patterns(
                    user_id=request.user_id,
                    task_type=intent.get("task_type", "general"),
                    raw_prompt=raw_prompt,
                ),
            )
            context = self._trace_step(
                run_trace,
                "Context Engineer Agent",
                "Add background, constraints, assumptions, and retrieved memory patterns.",
                lambda: self.context_engineer.build_context(
                    raw_prompt=raw_prompt,
                    intent=intent,
                    memory_matches=memory_matches,
                    deep_interpretation=deep_interpretation,
                    target_model=target_model,
                ),
            )
            missing_info = self._trace_step(
                run_trace,
                "Missing Information Detector",
                "Find important missing details and decide whether assumptions are safe.",
                lambda: self.missing_detector.detect(
                    raw_prompt=raw_prompt,
                    intent=intent,
                    context=context,
                    target_model=target_model,
                ),
            )
            clarification = self._trace_step(
                run_trace,
                "Clarification Agent",
                "Ask only necessary questions or continue with explicit assumptions.",
                lambda: self.clarifier.decide(
                    missing_info=missing_info,
                    force_clarification=request.force_clarification,
                ),
            )
        versions = self._trace_step(
            run_trace,
            "Prompt Builder Agent",
            "Generate multiple optimized prompt versions with different strategies.",
            lambda: self.builder.build_versions(
                raw_prompt=raw_prompt,
                intent=intent,
                context=context,
                clarification=clarification,
                version_count=request.versions,
                target_model=target_model,
                model_profile=model_profile,
                deep_interpretation=deep_interpretation,
            ),
        )
        # Critic and tester are independent reads of the same versions, so run
        # them concurrently instead of back-to-back. On the locked reasoning
        # model that roughly halves this stage's wall-clock time.
        critiques, stress_tests = self._trace_steps_parallel(
            run_trace,
            [
                (
                    "Prompt Critic Agent",
                    "Critique ambiguity, missing details, weak wording, and unclear output requirements.",
                    lambda: self.critic.critique(versions=versions, intent=intent, target_model=target_model),
                ),
                (
                    "Adversarial Tester Agent",
                    "Stress-test versions for misunderstanding, vagueness, unsafe output, and missed constraints.",
                    lambda: self.tester.test(versions=versions, intent=intent, target_model=target_model),
                ),
            ],
        )
        scores = self._trace_step(
            run_trace,
            "Prompt Scoring Agent",
            "Score each version with deterministic prompt-quality checks.",
            lambda: self.scorer.score(
                versions=versions,
                critiques=critiques,
                stress_tests=stress_tests,
                target_model=target_model,
                use_ai_judge=False,
            ),
        )
        comparison = self._trace_step(
            run_trace,
            "Version Comparison Agent",
            "Rank prompt versions and choose the strongest final prompt.",
            lambda: self.comparator.compare(
                versions=versions,
                scores=scores,
                critiques=critiques,
                stress_tests=stress_tests,
            ),
        )

        agent_outputs = [
            {"agent_name": "run_trace", "output": {"events": run_trace}},
            {"agent_name": "hermes_orchestrator", "output": hermes_plan or {"enabled": False}},
            {"agent_name": "model_profile_agent", "output": model_profile},
            {"agent_name": "policy_layer", "output": policy},
            {"agent_name": "intent_analyzer", "output": intent},
            {"agent_name": "deep_interpreter", "output": deep_interpretation},
            {"agent_name": "memory_agent", "output": {"matches": memory_matches}},
            {"agent_name": "context_engineer", "output": context},
            {"agent_name": "missing_information_detector", "output": missing_info},
            {"agent_name": "clarification_agent", "output": clarification},
            {"agent_name": "prompt_critic", "output": {"critiques": critiques}},
            {"agent_name": "adversarial_tester", "output": {"stress_tests": stress_tests}},
            {"agent_name": "prompt_scorer", "output": {"scores": scores}},
            {"agent_name": "version_comparator", "output": comparison},
        ]

        saved = self.repository.save_optimization_run(
            user_id=request.user_id,
            raw_prompt=raw_prompt,
            intent=intent,
            target_model=target_model,
            versions=versions,
            scores=scores,
            agent_outputs=agent_outputs,
            winner_label=comparison["winner_label"],
            conversation_id=request.conversation_id,
        )

        version_ids = saved["version_ids"]
        for version in versions:
            version["version_id"] = version_ids.get(version["label"])
        for score in scores:
            score["version_id"] = version_ids.get(score["label"])

        winner_version_id = version_ids.get(comparison["winner_label"])

        return {
            "history_id": saved["history_id"],
            "conversation_id": request.conversation_id,
            "is_refinement": False,
            "model_used": target_model,
            "needs_clarification": clarification["should_ask_user"],
            "clarification_questions": clarification["questions"],
            "assumptions": clarification["assumptions"],
            "final_prompt": comparison["winner_prompt"],
            "winner_label": comparison["winner_label"],
            "winner_version_id": winner_version_id,
            "score": comparison["winner_score"],
            "versions": versions,
            "scores": scores,
            "critiques": critiques,
            "stress_tests": stress_tests,
            "comparison": comparison,
            "run_trace": run_trace,
            "intent": intent,
            "context": context,
            "hermes_plan": hermes_plan,
            "model_profile": model_profile,
            "deep_interpretation": deep_interpretation,
            "memory_matches": memory_matches,
        }

    def _trace_step(
        self,
        run_trace: list[dict[str, Any]],
        agent_name: str,
        description: str,
        action: Callable[[], T],
    ) -> T:
        self._emit({"type": "agent_start", "agent": agent_name, "description": description})
        start = time.perf_counter()
        try:
            output = action()
        except Exception as exc:
            duration = round((time.perf_counter() - start) * 1000)
            run_trace.append(
                {
                    "agent": agent_name,
                    "description": description,
                    "status": "failed",
                    "duration_ms": duration,
                    "summary": safe_error_message(exc),
                    "preview": "",
                }
            )
            self._emit({"type": "agent_done", "agent": agent_name, "status": "failed", "duration_ms": duration})
            raise
        output = redact_value(output)

        duration = round((time.perf_counter() - start) * 1000)
        run_trace.append(
            {
                "agent": agent_name,
                "description": description,
                "status": "completed",
                "duration_ms": duration,
                "summary": self._summarize_output(output),
                "preview": self._preview_output(output),
            }
        )
        self._emit({"type": "agent_done", "agent": agent_name, "status": "completed", "duration_ms": duration})
        return output

    def _trace_steps_parallel(
        self,
        run_trace: list[dict[str, Any]],
        steps: list[tuple[str, str, Callable[[], Any]]],
    ) -> list[Any]:
        """Run independent agent steps concurrently (they are I/O-bound model
        calls). Progress events and trace entries are emitted from the calling
        thread only — workers never touch the shared run_trace or progress sink,
        so ordering stays deterministic and the progress callback stays
        single-threaded. Outputs are redacted to match _trace_step."""
        for agent_name, description, _ in steps:
            self._emit({"type": "agent_start", "agent": agent_name, "description": description})

        results: list[Any] = [None] * len(steps)
        errors: list[Exception | None] = [None] * len(steps)
        durations: list[int] = [0] * len(steps)

        def _worker(index: int, action: Callable[[], Any]) -> None:
            start = time.perf_counter()
            try:
                results[index] = action()
            except Exception as exc:  # noqa: BLE001 - surfaced per-step below
                errors[index] = exc
            finally:
                durations[index] = round((time.perf_counter() - start) * 1000)

        with ThreadPoolExecutor(max_workers=len(steps)) as executor:
            futures = [executor.submit(_worker, i, step[2]) for i, step in enumerate(steps)]
            for future in futures:
                future.result()

        for index, (agent_name, description, _) in enumerate(steps):
            if errors[index] is not None:
                run_trace.append(
                    {
                        "agent": agent_name,
                        "description": description,
                        "status": "failed",
                        "duration_ms": durations[index],
                        "summary": safe_error_message(errors[index]),
                        "preview": "",
                    }
                )
                self._emit(
                    {"type": "agent_done", "agent": agent_name, "status": "failed", "duration_ms": durations[index]}
                )
            else:
                output = redact_value(results[index])
                results[index] = output
                run_trace.append(
                    {
                        "agent": agent_name,
                        "description": description,
                        "status": "completed",
                        "duration_ms": durations[index],
                        "summary": self._summarize_output(output),
                        "preview": self._preview_output(output),
                    }
                )
                self._emit(
                    {"type": "agent_done", "agent": agent_name, "status": "completed", "duration_ms": durations[index]}
                )

        for error in errors:
            if error is not None:
                raise error
        return results

    def refine(self, request: OptimizeRequest) -> dict[str, Any]:
        """Focused follow-up turn: apply the user's instruction to the previous
        winning prompt with a single editing call, then score the result. This
        edits the existing prompt instead of expanding the instruction from
        scratch, so the output stays a clean improved prompt."""
        run_trace: list[dict[str, Any]] = []
        instruction = request.raw_prompt.strip()
        prior_prompt = (request.prior_prompt or "").strip()
        display_prompt = redact_text(instruction) or instruction
        safe_prior = redact_text(prior_prompt) or prior_prompt

        target_model = self._trace_step(
            run_trace,
            "Model Selector",
            "Select the OpenRouter model for this refinement turn.",
            lambda: self.client.select_model(request.target_model) if self.client.configured else request.target_model,
        )

        # Police only the new instruction. The base prompt was already vetted
        # when it was created, and it may legitimately contain defensive security
        # wording ("API key storage", "credential", "injection defense") that
        # would otherwise trip a false positive on every refinement.
        policy = self._trace_step(
            run_trace,
            "Policy Layer",
            "Check the refinement instruction against the project policy.",
            lambda: assess_prompt_policy(instruction, mode=get_settings().policy_mode).as_dict(),
        )

        if policy.get("is_disallowed"):
            refined_text = self._trace_step(
                run_trace,
                "Policy Redirect",
                "Refinement requested disallowed content; return a safe redirect instead.",
                lambda: self.builder._policy_redirect_versions(instruction, policy, 1)[0]["prompt_text"],
            )
            strategy = "policy-redirection"
            label = "v1_policy_redirect"
        else:
            refined_text = self._trace_step(
                run_trace,
                "Prompt Refiner",
                "Apply the user's requested change to the existing prompt, preserving what works.",
                lambda: self._refine_prompt_text(safe_prior, instruction, target_model),
            )
            strategy = "refinement"
            label = "v1_refined"

        version = {"label": label, "strategy": strategy, "prompt_text": refined_text}
        scores = self._trace_step(
            run_trace,
            "Prompt Scoring Agent",
            "Score the refined prompt with deterministic prompt-quality checks.",
            lambda: self.scorer.score(
                versions=[version], critiques=[], stress_tests=[], target_model=target_model, use_ai_judge=False
            ),
        )
        score_total = scores[0].get("total", 0) if scores else 0
        intent = {"task_type": "refinement", "goal": instruction}

        agent_outputs = [
            {"agent_name": "run_trace", "output": {"events": run_trace}},
            {"agent_name": "prompt_refiner", "output": {"instruction": display_prompt, "is_refinement": True}},
            {"agent_name": "policy_layer", "output": policy},
            {"agent_name": "prompt_scorer", "output": {"scores": scores}},
        ]

        saved = self.repository.save_optimization_run(
            user_id=request.user_id,
            raw_prompt=display_prompt,
            intent=intent,
            target_model=target_model,
            versions=[version],
            scores=scores,
            agent_outputs=agent_outputs,
            winner_label=label,
            conversation_id=request.conversation_id,
        )
        version_id = saved["version_ids"].get(label)
        version["version_id"] = version_id
        if scores:
            scores[0]["version_id"] = version_id

        return {
            "history_id": saved["history_id"],
            "conversation_id": request.conversation_id,
            "is_refinement": True,
            "model_used": target_model,
            "needs_clarification": False,
            "clarification_questions": [],
            "assumptions": [],
            "final_prompt": refined_text,
            "winner_label": label,
            "winner_version_id": version_id,
            "score": score_total,
            "versions": [version],
            "scores": scores,
            "critiques": [],
            "stress_tests": [],
            "comparison": {"winner_label": label, "winner_prompt": refined_text, "winner_score": score_total},
            "run_trace": run_trace,
            "intent": intent,
            "context": {},
            "hermes_plan": None,
            "model_profile": None,
            "memory_matches": [],
        }

    def _refine_prompt_text(self, prior_prompt: str, instruction: str, target_model: str | None) -> str:
        """Single editing call: improve the existing prompt per the instruction.
        Returns ONLY the improved prompt. Falls back to an appended requirement
        if the model is unavailable or returns nothing usable."""
        fallback_text = f"{prior_prompt}\n\n# Additional Requirement\n{instruction}"
        result = self.client.chat_json(
            system_prompt=(
                "You are a precision prompt editor. You receive an EXISTING optimized prompt and a user's "
                "requested change. Apply the change surgically: integrate it where it belongs and keep "
                "everything else that already works — preserve the prompt's structure, depth, section "
                "headings, and formatting. If the existing prompt is a detailed blueprint, the result must "
                "stay an equally detailed blueprint, not a shortened summary; do not drop sections, weaken "
                "constraints, or invent tools or APIs. Output ONLY the improved prompt itself: no preamble, "
                "no explanation, no meta-commentary, and never mention 'existing prompt', 'refinement', or "
                "these instructions."
            ),
            user_prompt=(
                f"EXISTING PROMPT:\n{compact_text(prior_prompt, limit=9000)}\n\n"
                f"REQUESTED CHANGE:\n{instruction}\n\n"
                'Return JSON: {"prompt_text": "the full improved prompt"}'
            ),
            fallback={"prompt_text": fallback_text},
            model=target_model,
            temperature=0.3,
            max_tokens=6000,
        )
        text = str(result.get("prompt_text") or "").strip() or fallback_text
        # Refinement preserves the prior prompt's structure, so if that prior
        # prompt carried the internal "Deep Reading" dump (e.g. it was built by
        # an older version), a surgical edit faithfully carries it forward. Strip
        # the same scaffolding the builder removes so refined prompts stay clean.
        return self.builder._clean_internal_scaffolding(text, quality_mode="advanced_system_blueprint")

    def _trace_skip(self, run_trace: list[dict[str, Any]], agent_name: str, description: str) -> None:
        run_trace.append(
            {
                "agent": agent_name,
                "description": description,
                "status": "skipped",
                "duration_ms": 0,
                "summary": description,
                "preview": "",
            }
        )
        self._emit({"type": "agent_start", "agent": agent_name, "description": description})
        self._emit({"type": "agent_done", "agent": agent_name, "status": "skipped", "duration_ms": 0})

    def _summarize_output(self, output: Any) -> str:
        if isinstance(output, list):
            return f"Produced {len(output)} item{'s' if len(output) != 1 else ''}."
        if isinstance(output, dict):
            keys = ", ".join(list(output.keys())[:6])
            return f"Produced fields: {keys}."
        if output is None:
            return "No output."
        return f"Produced {type(output).__name__}."

    def _preview_output(self, output: Any, limit: int = 900) -> str:
        try:
            text = json.dumps(redact_value(output), ensure_ascii=True, default=str, indent=2)
        except TypeError:
            text = str(redact_value(output))
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."
