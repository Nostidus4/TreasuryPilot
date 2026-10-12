from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="TP_", case_sensitive=False)

    environment: str = "local"
    cors_origins: str = "http://localhost:5173"
    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "TP_DATABASE_URL"),
    )
    platform_chain_config_path: Path = Path("deployments/chains.json")
    deployments_dir: Path = Path("deployments")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
