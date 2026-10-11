from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Worker runtime settings. Queue-specific secrets stay outside this model."""

    model_config = SettingsConfigDict(env_prefix="TP_", case_sensitive=False)

    redis_url: str = "redis://localhost:6379/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
