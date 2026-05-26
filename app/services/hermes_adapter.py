from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.security import safe_error_message
from app.services.openrouter_client import OpenRouterClient


@dataclass
class HermesStatus:
    installed: bool
    configured: bool
    selected_model: str | None
    message: str


class HermesAdapter:
    """Optional bridge for using Hermes Agent as an orchestration layer."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.openrouter = OpenRouterClient(self.settings)

    def status(self) -> HermesStatus:
        try:
            self._load_agent_class()
        except Exception as exc:
            return HermesStatus(
                installed=False,
                configured=False,
                selected_model=None,
                message=f"Hermes is not installed or importable yet: {safe_error_message(exc)}",
            )

        if not self.openrouter.configured:
            return HermesStatus(
                installed=True,
                configured=False,
                selected_model=None,
                message="Hermes is installed, but OpenRouter is not configured.",
            )

        selected_model = self.openrouter.select_model()
        return HermesStatus(
            installed=True,
            configured=True,
            selected_model=selected_model,
            message="Hermes is installed and ready to use OpenRouter through the OpenAI-compatible endpoint.",
        )

    def chat(self, message: str, system_prompt: str | None = None, max_iterations: int = 8) -> str:
        agent_class = self._load_agent_class()
        selected_model = self.openrouter.select_model()

        agent = agent_class(
            model=selected_model,
            api_key=self.settings.openrouter_api_key,
            base_url=self.settings.openrouter_base_url,
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            disabled_toolsets=["terminal", "browser"],
            max_iterations=max_iterations,
            ephemeral_system_prompt=system_prompt,
        )
        return agent.chat(message)

    def _load_agent_class(self):
        from run_agent import AIAgent

        return AIAgent
