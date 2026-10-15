from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
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
    # Private invoice document storage, read by worker-ai for extraction (same names as the API).
    s3_endpoint_url: str | None = Field(
        default=None, validation_alias=AliasChoices("TP_S3_ENDPOINT_URL", "S3_ENDPOINT_URL")
    )
    s3_bucket: str | None = Field(
        default=None, validation_alias=AliasChoices("TP_S3_BUCKET", "S3_BUCKET")
    )
    s3_access_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("TP_S3_ACCESS_KEY", "S3_ACCESS_KEY")
    )
    s3_secret_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("TP_S3_SECRET_KEY", "S3_SECRET_KEY")
    )
    # Environment-only credentials for notification email, held by the egress worker.
    environment: str = "local"
    resend_api_key: SecretStr | None = None
    resend_from_email: str | None = None
    # Shared with the API: signs List-Unsubscribe links (at least 32 bytes).
    email_unsubscribe_key: SecretStr | None = None
    public_api_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"
    log_format: LogFormat = "json"
    # Unset keeps the Prometheus endpoint off (tests, beat); compose serves it on the internal net.
    metrics_port: int | None = None
    # Docker secrets in the core worker only; unset means no attestation can be issued.
    policy_keystore_path: Path | None = None
    policy_keystore_password_file: Path | None = None
    # Internal signer service (EXE-007): base URL and the shared secret it requires.
    signer_url: str | None = None
    signer_shared_secret: SecretStr | None = None
    # Planning pipeline (EXE-004): the signer's executor address, the AI proposal switch and
    # timeout (BR-055: 20 s), and the lead time before a deadline when a request becomes eligible.
    executor_address: str | None = None
    planning_ai_enabled: bool = True
    planning_ai_timeout_seconds: float = 20.0
    execution_lead_time_seconds: int = 86_400
    # Swap-for-gas on the test router (EXE-011): off unless the per-swap cap is set. The cap
    # mirrors the module's configureSwap limit, which has no on-chain getter; it must be <= the
    # on-chain perRequest (and daily) limit. Test router only: it models 1 tokenOut unit = 1 wei
    # (raw base units) and does not actually fund executor gas.
    gas_swap_max_amount_in: int | None = None
    gas_swap_slippage_bps: int = 100
    # Telegram bot token: environment only, never logged (SecretStr masks repr).
    telegram_bot_token: SecretStr | None = None
    # Base of the deep links sent in notifications; the app enforces login and permissions.
    app_base_url: str = "http://localhost:5173"
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
