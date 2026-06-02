import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


def _resource_dir() -> Path:
    """Where bundled, read-only resources live (static/, assets/, docs/, app code)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    """Where writable user data lives (.env, the SQLite db, logs). For a frozen
    install this must live outside the (read-only) program folder."""
    if getattr(sys, "frozen", False):
        base = os.getenv("LOCALAPPDATA") or str(Path.home())
        path = Path(base) / "PromptOptimizerOpenRouter"
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(__file__).resolve().parent.parent


RESOURCE_DIR = _resource_dir()
DATA_DIR = _data_dir()
# Backwards-compatible alias; used for bundled resources (static/, docs/).
ROOT_DIR = RESOURCE_DIR

load_dotenv(DATA_DIR / ".env", override=True)

# OpenRouter asks clients to identify themselves for attribution/ranking.
APP_TITLE = "Hermes Prompt Optimizer"
APP_REFERER = "https://github.com/local/hermes-prompt-optimizer"


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str
    openrouter_base_url: str
    openrouter_model: str
    app_referer: str
    app_title: str
    database_path: Path
    policy_mode: str
    enable_local_restart: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    database_path = os.getenv("DATABASE_PATH", "data/prompt_optimizer.db")
    return Settings(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip(),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro").strip(),
        app_referer=os.getenv("OPENROUTER_APP_REFERER", APP_REFERER).strip(),
        app_title=os.getenv("OPENROUTER_APP_TITLE", APP_TITLE).strip(),
        database_path=(DATA_DIR / database_path).resolve(),
        policy_mode=os.getenv("PROMPT_OPTIMIZER_POLICY_MODE", "strict").strip().lower(),
        enable_local_restart=os.getenv("PROMPT_OPTIMIZER_ENABLE_LOCAL_RESTART", "true").strip().lower()
        in {"1", "true", "yes", "on"},
    )
