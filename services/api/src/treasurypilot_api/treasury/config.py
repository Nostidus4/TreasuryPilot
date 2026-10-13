from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

REQUIRED_MODULE_DEPLOYMENT = "TREASURY_MODULE_IMPLEMENTATION"
MAX_POSTGRES_INTEGER = 2_147_483_647
MAX_POSTGRES_SMALLINT = 32_767

# RPC credentials (provider API keys, basic auth) are referenced as ${ENV_VAR}
# placeholders so only the template is stored; consumers expand it at use time.
_RPC_PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
_RPC_URL_ADAPTER: TypeAdapter[AnyUrl] = TypeAdapter(AnyUrl)
_HEX_PATTERN = re.compile(r"[0-9a-fA-F]*")


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(word.capitalize() for word in rest)


class PlatformConfigurationError(RuntimeError):
    """A safe-to-display platform configuration error."""


class _ConfigModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class AssetConfig(_ConfigModel):
    address: str
    symbol: str = Field(min_length=1, max_length=32)
    # Checked against the token's on-chain decimals() before the asset is added (M02-D9).
    decimals: int = Field(ge=0, le=255)
    issuer_label: str = Field(min_length=1, max_length=120)
    is_test: bool = False

    @field_validator("symbol", "issuer_label")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("address")
    @classmethod
    def _validate_address(cls, value: str) -> str:
        _parse_hex(value, byte_length=20, field_name="asset address")
        return "0x" + value.removeprefix("0x").lower()

    @property
    def address_bytes(self) -> bytes:
        return bytes.fromhex(self.address.removeprefix("0x"))


class ChainConfig(_ConfigModel):
    chain_id: int = Field(gt=0, le=MAX_POSTGRES_INTEGER)
    name: str = Field(min_length=1, max_length=120)
    is_testnet: bool
    confirmations: int = Field(ge=0, le=MAX_POSTGRES_SMALLINT)
    explorer_url: HttpUrl
    rpc_urls: tuple[str, ...]
    enabled: bool = True
    assets: tuple[AssetConfig, ...] = ()

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("rpc_urls")
    @classmethod
    def _validate_rpc_urls(cls, urls: tuple[str, ...]) -> tuple[str, ...]:
        for url in urls:
            _validate_rpc_url_template(url)
        if len(set(urls)) != len(urls):
            raise ValueError("RPC URLs must be distinct")
        return urls

    @model_validator(mode="after")
    def _require_rpc_failover(self) -> Self:
        minimum = 2 if self.enabled else 1
        if len(self.rpc_urls) < minimum:
            state = "enabled" if self.enabled else "disabled"
            raise ValueError(f"{state} chains require at least {minimum} RPC URL(s)")
        return self

    @model_validator(mode="after")
    def _unique_asset_addresses(self) -> Self:
        addresses = [asset.address for asset in self.assets]
        if len(addresses) != len(set(addresses)):
            raise ValueError("asset addresses must be unique per chain")
        return self


class ChainConfigFile(_ConfigModel):
    chains: tuple[ChainConfig, ...]

    @model_validator(mode="after")
    def _unique_chain_ids(self) -> Self:
        chain_ids = [chain.chain_id for chain in self.chains]
        if len(chain_ids) != len(set(chain_ids)):
            raise ValueError("chain IDs must be unique")
        return self


def _validate_rpc_url_template(template: str) -> None:
    """Reject RPC URLs that embed literal credentials.

    Userinfo and query values may only be ``${ENV_VAR}`` placeholders. A key in
    the path cannot be detected, so it must be a placeholder by convention.
    """

    probe = _RPC_PLACEHOLDER.sub("placeholder", template)
    try:
        url = _RPC_URL_ADAPTER.validate_python(probe)
    except ValidationError:
        raise ValueError("RPC URLs must be a valid URL") from None
    if url.scheme not in {"http", "https", "ws", "wss"}:
        raise ValueError("RPC URLs must use http, https, ws, or wss")
    authority = template.split("://", 1)[-1].split("/", 1)[0]
    userinfo = authority.rpartition("@")[0] if "@" in authority else ""
    query = template.partition("?")[2].partition("#")[0]
    literal_parts = [part for part in userinfo.split(":") if part]
    literal_parts += [pair.partition("=")[2] for pair in query.split("&") if pair]
    if any(not _RPC_PLACEHOLDER.fullmatch(part) for part in literal_parts):
        raise ValueError(
            "RPC URLs must not embed credentials; reference them as ${ENV_VAR} placeholders"
        )


def resolve_rpc_url(template: str, environ: Mapping[str, str]) -> str:
    """Expand ``${ENV_VAR}`` placeholders in a stored RPC URL template."""

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in environ:
            raise PlatformConfigurationError(f"RPC URL references unset variable {name}")
        return environ[name]

    return _RPC_PLACEHOLDER.sub(substitute, template)


def _parse_hex(value: str, *, byte_length: int, field_name: str) -> bytes:
    candidate = value.removeprefix("0x")
    if len(candidate) != byte_length * 2:
        raise ValueError(f"{field_name} must contain exactly {byte_length} bytes")
    # bytes.fromhex ignores whitespace, so check the digits before decoding.
    if not _HEX_PATTERN.fullmatch(candidate):
        raise ValueError(f"{field_name} must be hexadecimal")
    decoded = bytes.fromhex(candidate)
    if not any(decoded):
        raise ValueError(f"{field_name} must not be the zero value")
    return decoded


class DeploymentConfig(_ConfigModel):
    name: str = Field(min_length=1, max_length=120)
    address: str
    code_hash: str
    version: str = Field(min_length=1, max_length=64)

    @field_validator("name", "version")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("address")
    @classmethod
    def _validate_address(cls, value: str) -> str:
        _parse_hex(value, byte_length=20, field_name="deployment address")
        return "0x" + value.removeprefix("0x").lower()

    @field_validator("code_hash")
    @classmethod
    def _validate_code_hash(cls, value: str) -> str:
        _parse_hex(value, byte_length=32, field_name="deployment code hash")
        return "0x" + value.removeprefix("0x").lower()

    @property
    def address_bytes(self) -> bytes:
        return bytes.fromhex(self.address.removeprefix("0x"))

    @property
    def code_hash_bytes(self) -> bytes:
        return bytes.fromhex(self.code_hash.removeprefix("0x"))


class DeploymentManifest(_ConfigModel):
    chain_id: int = Field(gt=0, le=MAX_POSTGRES_INTEGER)
    deployments: tuple[DeploymentConfig, ...]

    @model_validator(mode="before")
    @classmethod
    def _accept_named_deployment_map(cls, value: Any) -> Any:
        if not isinstance(value, dict) or not isinstance(value.get("deployments"), dict):
            return value
        if not all(isinstance(item, dict) for item in value["deployments"].values()):
            return value
        copied = dict(value)
        copied["deployments"] = [
            {**deployment, "name": name} for name, deployment in copied["deployments"].items()
        ]
        return copied

    @model_validator(mode="after")
    def _validate_deployments(self) -> Self:
        keys = [(deployment.name, deployment.version) for deployment in self.deployments]
        if len(keys) != len(set(keys)):
            raise ValueError("deployment name/version pairs must be unique")
        module = next(
            (
                deployment
                for deployment in self.deployments
                if deployment.name == REQUIRED_MODULE_DEPLOYMENT
            ),
            None,
        )
        if module is None:
            raise ValueError(f"required deployment {REQUIRED_MODULE_DEPLOYMENT!r} is missing")
        return self


class PlatformConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    chains: tuple[ChainConfig, ...]
    manifests: tuple[DeploymentManifest, ...]

    @classmethod
    def load(cls, chain_config_path: Path, deployments_dir: Path) -> PlatformConfiguration:
        chain_config = _load_model(chain_config_path, ChainConfigFile, "chain configuration")
        manifests: list[DeploymentManifest] = []
        for chain in chain_config.chains:
            if not chain.enabled:
                continue
            manifest_path = deployments_dir / f"{chain.chain_id}.json"
            manifest = _load_model(
                manifest_path,
                DeploymentManifest,
                f"deployment manifest for chain {chain.chain_id}",
            )
            if manifest.chain_id != chain.chain_id:
                raise PlatformConfigurationError(
                    f"deployment manifest {manifest_path} declares chain ID "
                    f"{manifest.chain_id}, expected {chain.chain_id}"
                )
            manifests.append(manifest)
        return cls(chains=chain_config.chains, manifests=tuple(manifests))


def _load_model[ModelT: BaseModel](path: Path, model: type[ModelT], label: str) -> ModelT:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise PlatformConfigurationError(f"{label} file is missing: {path}") from error
    except (OSError, UnicodeError) as error:
        raise PlatformConfigurationError(f"cannot read {label} file: {path}") from error
    except json.JSONDecodeError as error:
        raise PlatformConfigurationError(
            f"{label} file is not valid JSON: {path} (line {error.lineno})"
        ) from error
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        problems = "; ".join(
            _format_validation_issue(issue)
            for issue in error.errors(include_url=False, include_input=False)
        )
        # Pydantic's original exception renders input values. Suppress its traceback so an
        # authenticated RPC URL or token can never leak from startup validation failures.
        raise PlatformConfigurationError(f"invalid {label} at {path}: {problems}") from None


def _format_validation_issue(issue: Mapping[str, Any]) -> str:
    location = ".".join(str(part) for part in issue["loc"])
    return f"{location}: {issue['msg']}" if location else str(issue["msg"])
