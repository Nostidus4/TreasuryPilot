from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from treasurypilot_core.observability import LogFormat


class Settings(BaseSettings):
    """Worker runtime settings. Queue-specific secrets stay outside this model."""

    model_config = SettingsConfigDict(env_prefix="TP_", case_sensitive=False)

    redis_url: str = "redis://localhost:6379/0"
    visibility_timeout_seconds: int = 3600
    # Relative to the working directory: the repo root locally, /app in the worker image.
    ai_config_path: Path = Path("config/ai.yaml")
    # Compose sets DATABASE_URL unprefixed; empty means this process has no DB access.
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    log_level: str = "INFO"
    log_format: LogFormat = "json"
    # Unset keeps the Prometheus endpoint off (tests, beat); compose serves it on the internal net.
    metrics_port: int | None = None
    # Docker secrets in the core worker only; unset means no attestation can be issued.
    policy_keystore_path: Path | None = None
    policy_keystore_password_file: Path | None = None
    # Separate publisher identity; configure only in the core worker after its
    # address has been allowlisted by AuditRootAnchor.setPublisher.
    audit_anchor_rpc_url: str | None = None
    audit_anchor_chain_id: int | None = None
    audit_anchor_contract_address: str | None = None
    audit_anchor_private_key: SecretStr | None = Field(
        default=None, validation_alias="TP_AUDIT_ANCHOR_PRIVATE_KEY"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
