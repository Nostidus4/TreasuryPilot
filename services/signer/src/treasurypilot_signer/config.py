import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from eth_utils import to_checksum_address
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from treasurypilot_core.observability import LogFormat


class Settings(BaseSettings):
    """Runtime configuration for the internal signing boundary."""

    model_config = SettingsConfigDict(env_prefix="TP_", case_sensitive=False)

    log_level: str = "INFO"
    log_format: LogFormat = "json"
    signer_shared_secret: str = ""
    allowed_chain_ids: list[int] = Field(default_factory=lambda: [31337, 11155111])
    trusted_policy_signers: list[str] = Field(default_factory=list)
    executor_keystore_map: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)
    executor_keystore_password_file: Path | None = None
    # Sentinel (pause-only) key; separate from the executor key. Targets map treasury UUID ->
    # {"guardianSafe": 0x.., "module": 0x..}; the sentinel is idle until targets are set.
    sentinel_keystore_path: Path | None = None
    sentinel_keystore_password_file: Path | None = None
    sentinel_targets: Annotated[dict[str, dict[str, str]], NoDecode] = Field(default_factory=dict)
    chain_rpc_url: str = Field(default="", validation_alias="CHAIN_RPC_URL")
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    signer_database_url: str | None = None
    # Signer-side ceiling on gas_limit * maxFeePerGas; the plan's feeCapWei is not covered by the
    # attested plan hash, so it can only lower this value.
    max_fee_cap_wei: int = Field(default=10**17, ge=0)

    @field_validator("executor_keystore_map", mode="before")
    @classmethod
    def parse_keystore_map(cls, value: Any) -> dict[str, str]:
        if value is None or value == "":
            return {}
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError("executor keystore map must be a JSON object")
        return {str(key): str(path) for key, path in value.items()}

    @field_validator("sentinel_targets", mode="before")
    @classmethod
    def parse_sentinel_targets(cls, value: Any) -> dict[str, dict[str, str]]:
        if value is None or value == "":
            return {}
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError("sentinel targets must be a JSON object")
        for target in value.values():
            if not isinstance(target, dict) or set(target) != {"guardianSafe", "module"}:
                raise ValueError("each sentinel target needs exactly guardianSafe and module")
        targets: dict[str, dict[str, str]] = {
            str(key).lower(): {
                name: to_checksum_address(address) for name, address in target.items()
            }
            for key, target in value.items()
        }
        for target in targets.values():
            if int(target["guardianSafe"], 16) == 0 or int(target["module"], 16) == 0:
                raise ValueError("sentinel target addresses must not be the zero address")
            if target["guardianSafe"] == target["module"]:
                raise ValueError("sentinel guardianSafe and module must differ")
        return targets

    @property
    def effective_database_url(self) -> str | None:
        return self.signer_database_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
