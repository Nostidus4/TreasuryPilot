from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from treasurypilot_core.observability import LogFormat


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="TP_", case_sensitive=False)

    log_level: str = "INFO"
    log_format: LogFormat = "json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
