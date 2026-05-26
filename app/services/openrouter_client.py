import time
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from app.config import Settings, get_settings
from app.security import safe_error_message
from app.utils.json_tools import extract_json_object


# Sensible default when "auto" selection can't reach the catalog: capable,
# inexpensive, widely available on OpenRouter, supports tools + JSON output.
FALLBACK_TEXT_MODEL = "openai/gpt-4o-mini"


class OpenRouterClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client = None
        self._selected_auto_model: str | None = None
        if self.settings.openrouter_api_key:
            self._client = OpenAI(
                api_key=self.settings.openrouter_api_key,
                base_url=self.settings.openrouter_base_url,
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
    ) -> str:
        if self._client is None:
            raise RuntimeError("OpenRouter API key is not configured.")

        selected_model = self.select_model(model)
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                response = self._client.chat.completions.create(
                    model=selected_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
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
        selected = (requested_model or self.settings.openrouter_model or "auto").strip()
        if selected and selected.lower() != "auto":
            return selected

        if self._selected_auto_model:
            return self._selected_auto_model

        try:
            models = self.list_models()
        except Exception:
            self._selected_auto_model = FALLBACK_TEXT_MODEL
            return self._selected_auto_model

        if not models:
            self._selected_auto_model = FALLBACK_TEXT_MODEL
            return self._selected_auto_model

        self._selected_auto_model = max(models, key=self._prompt_optimizer_model_score).get("id", FALLBACK_TEXT_MODEL)
        return self._selected_auto_model

    def _prompt_optimizer_model_score(self, model: dict[str, Any]) -> float:
        model_id = str(model.get("id") or "").lower()
        context_tokens = int(model.get("context_length") or 0)
        supported = {str(item).lower() for item in (model.get("supported_parameters") or [])}
        pricing = model.get("pricing") or {}
        prompt_cost = _to_float(pricing.get("prompt"))
        completion_cost = _to_float(pricing.get("completion"))

        if not _produces_text(model):
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


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
