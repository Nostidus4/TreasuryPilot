from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="TP_", case_sensitive=False)

    environment: str = "local"
    cors_origins: str = "http://localhost:5173"
    database_url: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("TP_DATABASE_URL", "DATABASE_URL"),
    )
    session_secret: SecretStr | None = None
    redis_url: SecretStr | None = None
    magic_link_base_url: str = "http://localhost:5173/auth/verify"
    resend_api_key: SecretStr | None = None
    resend_from_email: str | None = None
    session_cookie_name: str = "tp_session"
    csrf_cookie_name: str = "tp_csrf"
    csrf_header_name: str = "X-CSRF-Token"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
