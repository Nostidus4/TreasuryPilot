from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Worker runtime settings. Queue-specific secrets stay outside this model."""

    model_config = SettingsConfigDict(env_prefix="TP_", case_sensitive=False)

    redis_url: str = "redis://localhost:6379/0"
    visibility_timeout_seconds: int = 3600
    # Relative to the working directory: the repo root locally, /app in the worker image.
    ai_config_path: Path = Path("config/ai.yaml")


@lru_cache
def get_settings() -> Settings:
    return Settings()
