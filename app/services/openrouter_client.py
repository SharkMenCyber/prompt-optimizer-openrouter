import math
import time
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from app.config import Settings, get_settings
from app.security import safe_error_message
from app.utils.json_tools import extract_json_object


# The optimizer is intentionally locked to one concrete OpenRouter model so
# every agent in the pipeline uses the same context window, pricing envelope,
# and instruction-following profile.
LOCKED_TEXT_MODEL = "deepseek/deepseek-v4-pro"
FALLBACK_TEXT_MODEL = LOCKED_TEXT_MODEL

# Per-request HTTP timeout (seconds). The locked model is a reasoning model, so
# even its slowest legitimate call (the 8500-token builder) finishes well inside
# this window. The timeout exists to fail fast on a genuinely stuck request
# instead of letting the SDK default (~10 minutes) stall the whole pipeline.
REQUEST_TIMEOUT_SECONDS = 180.0

# OpenRouter catalog entries that are routers/meta-models, not concrete models.
# They can advertise placeholder pricing (for example -1) and very large
# context/capability metadata. Keep them out of automatic ranking so "auto"
# resolves to a real text model the app can report and reason about clearly.
ROUTER_META_MODEL_IDS = {
    "openrouter/auto",
    "openrouter/pareto-code",
    "openrouter/bodybuilder",
}


class OpenRouterClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client = None
        self._selected_auto_model: str | None = None
        if self.settings.openrouter_api_key:
            self._client = OpenAI(
                api_key=self.settings.openrouter_api_key,
                base_url=self.settings.openrouter_base_url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                default_headers={
                    "HTTP-Referer": self.settings.app_referer,
                    "X-Title": self.settings.app_title,
                },
            )

    @property
    def configured(self) -> bool:
        return self._client is not None

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1400,
        reasoning_enabled: bool = True,
    ) -> str:
        if self._client is None:
            raise RuntimeError("OpenRouter API key is not configured.")

        selected_model = self.select_model(model)
        last_error: Exception | None = None

        # The locked model is a reasoning model: its hidden reasoning phase adds
        # ~15-40s and 500-2000 tokens to every call, and those tokens count
        # against max_tokens (so reasoning overflow truncates the answer and
        # forces a fallback). Pure extraction/analysis agents pass
        # reasoning_enabled=False to skip it — ~3x faster and no truncation —
        # while depth-critical agents (deep interpreter, builder) keep it on.
        extra_args: dict[str, Any] = {}
        if not reasoning_enabled:
            extra_args["extra_body"] = {"reasoning": {"enabled": False}}

        for attempt in range(3):
            try:
                response = self._client.chat.completions.create(
                    model=selected_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **extra_args,
                )
                return response.choices[0].message.content or ""
            except RateLimitError as exc:
                last_error = exc
                time.sleep(2**attempt)
            except (APIConnectionError, APITimeoutError) as exc:
                last_error = exc
                time.sleep(2**attempt)
            except APIStatusError as exc:
                last_error = exc
                if exc.status_code in {429, 500, 502, 503, 504}:
                    time.sleep(2**attempt)
                    continue
                raise

        raise RuntimeError(f"OpenRouter request failed after retries: {safe_error_message(last_error)}")

    def list_models(self) -> list[dict[str, Any]]:
        if not self.settings.openrouter_api_key:
            return []

        url = f"{self.settings.openrouter_base_url.rstrip('/')}/models"
        with httpx.Client(timeout=12) as client:
            response = client.get(
                url,
                headers={
                    "Authorization": f"Bearer {self.settings.openrouter_api_key}",
                    "HTTP-Referer": self.settings.app_referer,
                    "X-Title": self.settings.app_title,
                },
            )
            response.raise_for_status()
            data = response.json().get("data", [])

        return [item for item in data if _produces_text(item)]

    def select_model(self, requested_model: str | None = None) -> str:
        """Return the single model this app is allowed to use.

        `requested_model` is accepted for backward-compatible API/UI payloads,
        but ignored so direct API calls cannot silently switch providers.
        """
        return LOCKED_TEXT_MODEL

    def _prompt_optimizer_model_score(self, model: dict[str, Any]) -> float:
        model_id = str(model.get("id") or "").lower()
        context_tokens = int(model.get("context_length") or 0)
        supported = {str(item).lower() for item in (model.get("supported_parameters") or [])}
        pricing = model.get("pricing") or {}
        prompt_cost = _to_float(pricing.get("prompt"))
        completion_cost = _to_float(pricing.get("completion"))

        if not _is_auto_selectable_model(model):
            return -1000

        score = 0.0
        # Context window.
        score += 10 if context_tokens >= 200000 else 8 if context_tokens >= 128000 else 5 if context_tokens >= 64000 else 3 if context_tokens >= 32000 else 0
        # Capabilities surfaced by OpenRouter's supported_parameters.
        score += 8 if "tools" in supported else 0
        score += 7 if "reasoning" in supported else 0
        score += 6 if ("response_format" in supported or "structured_outputs" in supported) else 0
        # Light preference for strong, well-known instruction-following families.
        score += 8 if any(term in model_id for term in [
            "gpt-4", "o1", "o3", "claude-3", "claude-sonnet", "claude-opus",
            "gemini-1.5-pro", "gemini-2", "llama-3.3", "llama-3.1-405b",
            "deepseek", "qwen-2.5-72b", "qwen2.5-72b", "grok",
        ]) else 0
        # Cost penalty, scaled to per-million-token price.
        cost_per_million = (prompt_cost + completion_cost) * 1_000_000
        score -= min(15.0, cost_per_million / 5.0)
        # ":free" models are great for cost but heavily rate-limited; mild penalty.
        score -= 3 if model_id.endswith(":free") else 0
        return score

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: dict[str, Any],
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1800,
        reasoning_enabled: bool = True,
    ) -> dict[str, Any]:
        if not self.configured:
            return fallback

        try:
            content = self.chat(
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt + "\nReturn only valid JSON.",
                    },
                    {"role": "user", "content": user_prompt},
                ],
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_enabled=reasoning_enabled,
            )
            parsed = extract_json_object(content)
            if parsed is None:
                fallback = dict(fallback)
                fallback["source"] = "local_fallback"
                fallback["warning"] = "OpenRouter response was not valid JSON; used local fallback."
                return fallback
            parsed.setdefault("source", "openrouter")
            return parsed
        except Exception as exc:
            fallback = dict(fallback)
            fallback["source"] = "local_fallback"
            fallback["warning"] = safe_error_message(exc)
            return fallback


def _produces_text(model: dict[str, Any]) -> bool:
    architecture = model.get("architecture") or {}
    output_modalities = [str(item).lower() for item in (architecture.get("output_modalities") or [])]
    if output_modalities:
        return "text" in output_modalities
    modality = str(architecture.get("modality") or "").lower()
    if modality:
        return modality.split("->")[-1].strip() == "text" or "text" in modality.split("->")[-1]
    # Older/sparse entries without architecture metadata: assume text-capable.
    return True


def _is_router_meta_model(model: dict[str, Any]) -> bool:
    return str(model.get("id") or "").strip().lower() in ROUTER_META_MODEL_IDS


def _is_auto_selectable_model(model: dict[str, Any]) -> bool:
    return _produces_text(model) and not _is_router_meta_model(model) and not _has_negative_pricing(model)


def _has_negative_pricing(model: dict[str, Any]) -> bool:
    pricing = model.get("pricing") or {}
    return _is_negative_number(pricing.get("prompt")) or _is_negative_number(pricing.get("completion"))


def _is_negative_number(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number < 0


def _to_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number) or number < 0:
        return 0.0
    return number
