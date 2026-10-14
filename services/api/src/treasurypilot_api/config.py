import ipaddress
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from treasurypilot_core.observability import LogFormat

# services/api/src/treasurypilot_api/config.py -> repository root
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="TP_", case_sensitive=False)

    environment: str = "local"
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    log_format: LogFormat = "json"
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
    platform_chain_config_path: Path = REPOSITORY_ROOT / "deployments" / "chains.json"
    deployments_dir: Path = REPOSITORY_ROOT / "deployments"
    admin_staff_token: SecretStr | None = None
    admin_staff_id: str | None = None
    admin_ip_allowlist: str = ""

    @field_validator("admin_ip_allowlist")
    @classmethod
    def _validate_admin_ip_allowlist(cls, value: str) -> str:
        # Fail at startup on a malformed CIDR instead of silently disabling admin.
        for item in value.split(","):
            if item.strip():
                ipaddress.ip_network(item.strip(), strict=False)
        return value

    @property
    def admin_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        return [
            ipaddress.ip_network(item.strip(), strict=False)
            for item in self.admin_ip_allowlist.split(",")
            if item.strip()
        ]

    @property
    def admin_configured(self) -> bool:
        return (
            self.admin_staff_token is not None
            and len(self.admin_staff_token.get_secret_value().encode()) >= 32
            and bool(self.admin_staff_id)
            and bool(self.admin_networks)
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
