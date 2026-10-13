from __future__ import annotations

import asyncio
import json
import os
import traceback
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api.config import Settings
from treasurypilot_api.treasury.config import (
    PlatformConfiguration,
    PlatformConfigurationError,
    resolve_rpc_url,
)
from treasurypilot_api.treasury.models import Chain, Deployment
from treasurypilot_api.treasury.sync import deployment_id, sync_platform_configuration

API_ROOT = Path(__file__).parents[1]
CHAIN_ID = 11155111
ADDRESS = "0x1111111111111111111111111111111111111111"
CODE_HASH = "0x" + "22" * 32


def _chain(**overrides: Any) -> dict[str, Any]:
    chain = {
        "chainId": CHAIN_ID,
        "name": "Ethereum Sepolia",
        "isTestnet": True,
        "confirmations": 3,
        "explorerUrl": "https://sepolia.etherscan.io",
        "rpcUrls": ["https://rpc-one.example", "wss://rpc-two.example/ws"],
        "enabled": True,
    }
    chain.update(overrides)
    return chain


def _manifest(**deployment_overrides: Any) -> dict[str, Any]:
    deployment = {
        "address": ADDRESS,
        "codeHash": CODE_HASH,
        "version": "1.0.0",
    }
    deployment.update(deployment_overrides)
    return {
        "chainId": CHAIN_ID,
        "deployments": {"TREASURY_MODULE_IMPLEMENTATION": deployment},
    }


def _write_configuration(
    root: Path,
    *,
    chain: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    config_path = root / "chains.json"
    config_path.write_text(json.dumps({"chains": [chain or _chain()]}), encoding="utf-8")
    if manifest is not None:
        (root / f"{CHAIN_ID}.json").write_text(json.dumps(manifest), encoding="utf-8")
    return config_path, root


def test_loads_valid_chain_and_deployment_manifest(tmp_path: Path) -> None:
    config_path, deployments_dir = _write_configuration(tmp_path, manifest=_manifest())

    configuration = PlatformConfiguration.load(config_path, deployments_dir)

    assert configuration.chains[0].chain_id == CHAIN_ID
    assert len(configuration.chains[0].rpc_urls) == 2
    assert configuration.manifests[0].deployments[0].address_bytes == bytes.fromhex("11" * 20)
    assert configuration.manifests[0].deployments[0].code_hash_bytes == bytes.fromhex("22" * 32)


@pytest.mark.parametrize("chain_id", [0, -1, 2_147_483_648])
def test_rejects_invalid_chain_id(tmp_path: Path, chain_id: int) -> None:
    config_path, deployments_dir = _write_configuration(tmp_path, chain=_chain(chainId=chain_id))

    with pytest.raises(PlatformConfigurationError, match="chainId"):
        PlatformConfiguration.load(config_path, deployments_dir)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"confirmations": -1}, "confirmations"),
        ({"confirmations": 32_768}, "confirmations"),
        ({"explorerUrl": "ftp://explorer.example"}, "explorerUrl"),
        ({"explorerUrl": ""}, "explorerUrl"),
    ],
)
def test_rejects_invalid_confirmation_or_explorer_values(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    config_path, deployments_dir = _write_configuration(tmp_path, chain=_chain(**overrides))

    with pytest.raises(PlatformConfigurationError, match=message):
        PlatformConfiguration.load(config_path, deployments_dir)


@pytest.mark.parametrize(
    ("rpc_urls", "message"),
    [
        ([], "at least 2 RPC"),
        (["https://only-one.example"], "at least 2 RPC"),
        (
            ["https://duplicate.example", "https://duplicate.example"],
            "must be distinct",
        ),
        (["", "https://valid.example"], "valid URL"),
    ],
)
def test_rejects_missing_duplicate_or_insufficient_rpc_urls(
    tmp_path: Path, rpc_urls: list[str], message: str
) -> None:
    config_path, deployments_dir = _write_configuration(tmp_path, chain=_chain(rpcUrls=rpc_urls))

    with pytest.raises(PlatformConfigurationError, match=message):
        PlatformConfiguration.load(config_path, deployments_dir)


def test_validation_error_does_not_echo_rpc_credentials(tmp_path: Path) -> None:
    secret = "do-not-log-this-token"
    config_path, deployments_dir = _write_configuration(
        tmp_path,
        chain=_chain(rpcUrls=[f"not-a-url-{secret}", "https://valid.example"]),
    )

    with pytest.raises(PlatformConfigurationError) as caught:
        PlatformConfiguration.load(config_path, deployments_dir)

    assert secret not in str(caught.value)
    assert secret not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__suppress_context__ is True


@pytest.mark.parametrize(
    "rpc_url",
    [
        "https://user:secret@rpc.example",
        "https://rpc.example/?apikey=secret",
        "wss://rpc.example/ws?token=secret&x=${OK}",
    ],
)
def test_rejects_rpc_urls_with_literal_credentials(tmp_path: Path, rpc_url: str) -> None:
    config_path, deployments_dir = _write_configuration(
        tmp_path, chain=_chain(rpcUrls=[rpc_url, "https://valid.example"])
    )

    with pytest.raises(PlatformConfigurationError, match="must not embed credentials") as caught:
        PlatformConfiguration.load(config_path, deployments_dir)

    assert "secret" not in str(caught.value)


def test_rpc_credentials_are_stored_as_placeholders_and_resolved_at_use(tmp_path: Path) -> None:
    templates = [
        "https://eth-sepolia.example/v2/${ALCHEMY_API_KEY}",
        "https://${RPC_USER}:${RPC_PASSWORD}@rpc.example/?key=${RPC_KEY}",
    ]
    config_path, deployments_dir = _write_configuration(
        tmp_path, chain=_chain(rpcUrls=templates), manifest=_manifest()
    )

    configuration = PlatformConfiguration.load(config_path, deployments_dir)

    assert configuration.chains[0].rpc_urls == tuple(templates)
    assert (
        resolve_rpc_url(templates[0], {"ALCHEMY_API_KEY": "abc"})
        == "https://eth-sepolia.example/v2/abc"
    )
    with pytest.raises(PlatformConfigurationError, match="unset variable RPC_USER"):
        resolve_rpc_url(templates[1], {})


def test_default_configuration_paths_do_not_depend_on_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TP_PLATFORM_CHAIN_CONFIG_PATH", raising=False)
    monkeypatch.delenv("TP_DEPLOYMENTS_DIR", raising=False)

    settings = Settings()

    assert settings.platform_chain_config_path.is_absolute()
    PlatformConfiguration.load(settings.platform_chain_config_path, settings.deployments_dir)


def test_requires_chain_configuration_file(tmp_path: Path) -> None:
    with pytest.raises(PlatformConfigurationError, match="configuration file is missing"):
        PlatformConfiguration.load(tmp_path / "missing.json", tmp_path)


def test_requires_enabled_chain_manifest(tmp_path: Path) -> None:
    config_path, deployments_dir = _write_configuration(tmp_path)

    with pytest.raises(PlatformConfigurationError, match="manifest.*missing"):
        PlatformConfiguration.load(config_path, deployments_dir)


def test_requires_module_implementation(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["deployments"] = {
        "TREASURY_MODULE_FACTORY": manifest["deployments"]["TREASURY_MODULE_IMPLEMENTATION"]
    }
    config_path, deployments_dir = _write_configuration(tmp_path, manifest=manifest)

    with pytest.raises(PlatformConfigurationError, match="IMPLEMENTATION.*missing"):
        PlatformConfiguration.load(config_path, deployments_dir)


@pytest.mark.parametrize("field", ["address", "codeHash"])
def test_requires_module_address_and_code_hash(tmp_path: Path, field: str) -> None:
    manifest = _manifest()
    del manifest["deployments"]["TREASURY_MODULE_IMPLEMENTATION"][field]
    config_path, deployments_dir = _write_configuration(tmp_path, manifest=manifest)

    with pytest.raises(PlatformConfigurationError, match=f"{field}.*Field required"):
        PlatformConfiguration.load(config_path, deployments_dir)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"address": "0x1234"}, "address.*20 bytes"),
        ({"address": "0x" + "00" * 20}, "address.*zero"),
        ({"codeHash": "0x1234"}, "code hash.*32 bytes"),
        ({"codeHash": "0x" + "gg" * 32}, "code hash.*hexadecimal"),
        ({"codeHash": "0x" + "00" * 32}, "code hash.*zero"),
        ({"address": "0x" + "11" * 19 + "  "}, "address.*hexadecimal"),
    ],
)
def test_rejects_invalid_deployment_address_or_code_hash(
    tmp_path: Path, overrides: dict[str, str], message: str
) -> None:
    config_path, deployments_dir = _write_configuration(tmp_path, manifest=_manifest(**overrides))

    with pytest.raises(PlatformConfigurationError, match=message):
        PlatformConfiguration.load(config_path, deployments_dir)


def test_rejects_manifest_chain_mismatch(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["chainId"] = CHAIN_ID + 1
    config_path, deployments_dir = _write_configuration(tmp_path, manifest=manifest)

    with pytest.raises(PlatformConfigurationError, match="declares chain ID.*expected"):
        PlatformConfiguration.load(config_path, deployments_dir)


def _asset(**overrides: Any) -> dict[str, Any]:
    asset = {
        "address": "0x" + "AB" * 20,
        "symbol": "tUSDC",
        "decimals": 6,
        "issuerLabel": "TreasuryPilot test token",
        "isTest": True,
    }
    asset.update(overrides)
    return asset


def test_loads_chain_assets_with_normalized_address(tmp_path: Path) -> None:
    config_path, deployments_dir = _write_configuration(
        tmp_path, chain=_chain(assets=[_asset()]), manifest=_manifest()
    )

    asset = PlatformConfiguration.load(config_path, deployments_dir).chains[0].assets[0]

    assert asset.address == "0x" + "ab" * 20
    assert (asset.symbol, asset.decimals, asset.is_test) == ("tUSDC", 6, True)


@pytest.mark.parametrize(
    ("assets", "message"),
    [
        ([_asset(address="0x1234")], "asset address.*20 bytes"),
        ([_asset(decimals=256)], "decimals"),
        ([_asset(symbol=" ")], "blank"),
        ([_asset(), _asset(address="0x" + "ab" * 20)], "asset addresses must be unique"),
    ],
)
def test_rejects_invalid_or_duplicate_assets(
    tmp_path: Path, assets: list[dict[str, Any]], message: str
) -> None:
    config_path, deployments_dir = _write_configuration(
        tmp_path, chain=_chain(assets=assets), manifest=_manifest()
    )

    with pytest.raises(PlatformConfigurationError, match=message):
        PlatformConfiguration.load(config_path, deployments_dir)


def test_deployment_id_is_stable_and_keyed_by_natural_key() -> None:
    first = deployment_id(CHAIN_ID, "TREASURY_MODULE_IMPLEMENTATION", "1.0.0")

    assert first == deployment_id(CHAIN_ID, "TREASURY_MODULE_IMPLEMENTATION", "1.0.0")
    assert first != deployment_id(CHAIN_ID, "TREASURY_MODULE_IMPLEMENTATION", "1.0.1")


def _alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _assert_idempotent_sync(database_url: str, configuration: PlatformConfiguration) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await sync_platform_configuration(session, configuration)
            await sync_platform_configuration(session, configuration)
            chain_count = await session.scalar(
                select(func.count()).select_from(Chain).where(Chain.chain_id == CHAIN_ID)
            )
            deployment_count = await session.scalar(
                select(func.count()).select_from(Deployment).where(Deployment.chain_id == CHAIN_ID)
            )
            chain_version = await session.scalar(
                select(Chain.version).where(Chain.chain_id == CHAIN_ID)
            )
            deployment_version = await session.scalar(
                select(Deployment.row_version).where(Deployment.chain_id == CHAIN_ID)
            )
            await session.delete(
                (
                    await session.execute(select(Deployment).where(Deployment.chain_id == CHAIN_ID))
                ).scalar_one()
            )
            await session.delete(
                (
                    await session.execute(select(Chain).where(Chain.chain_id == CHAIN_ID))
                ).scalar_one()
            )
            await session.commit()
    finally:
        await engine.dispose()

    assert chain_count == 1
    assert deployment_count == 1
    assert chain_version == 1
    assert deployment_version == 1


async def _assert_removed_chain_is_disabled(
    database_url: str, configuration: PlatformConfiguration
) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await sync_platform_configuration(session, configuration)
            await sync_platform_configuration(
                session, PlatformConfiguration(chains=(), manifests=())
            )
            enabled = await session.scalar(select(Chain.enabled).where(Chain.chain_id == CHAIN_ID))
            version = await session.scalar(select(Chain.version).where(Chain.chain_id == CHAIN_ID))
            await sync_platform_configuration(
                session, PlatformConfiguration(chains=(), manifests=())
            )
            version_after_noop = await session.scalar(
                select(Chain.version).where(Chain.chain_id == CHAIN_ID)
            )
    finally:
        await engine.dispose()

    assert enabled is False
    assert version == 2
    assert version_after_noop == 2


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL synchronization test",
)
def test_platform_configuration_sync_is_idempotent_on_postgres(tmp_path: Path) -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config_path, deployments_dir = _write_configuration(tmp_path, manifest=_manifest())
    configuration = PlatformConfiguration.load(config_path, deployments_dir)
    alembic_config = _alembic_config(database_url)

    command.upgrade(alembic_config, "head")
    try:
        asyncio.run(_assert_idempotent_sync(database_url, configuration))
        asyncio.run(_assert_removed_chain_is_disabled(database_url, configuration))
    finally:
        command.downgrade(alembic_config, "base")
