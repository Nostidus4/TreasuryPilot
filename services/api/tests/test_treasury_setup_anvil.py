from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from treasurypilot_api.identity import rbac
from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import Membership, Organization, User, WalletLink
from treasurypilot_api.mandate.api import router as governance_router
from treasurypilot_api.mandate.governance_service import GovernanceService
from treasurypilot_api.treasury.api import router as treasury_router
from treasurypilot_api.treasury.config import (
    ChainConfig,
    DeploymentConfig,
    DeploymentManifest,
    PlatformConfiguration,
)
from treasurypilot_api.treasury.models import SafeConfigSnapshot, TreasuryWallet
from treasurypilot_api.treasury.safe import RpcSafeVerifier
from treasurypilot_api.treasury.service import TreasuryService
from treasurypilot_api.treasury.sync import asset_id, sync_platform_configuration
from treasurypilot_worker.chain.safe_config import refresh_safe_config_snapshots

API_ROOT = Path(__file__).parents[1]
REPO_ROOT = API_ROOT.parents[1]
CHAIN_ID = 31337
# Public test-only mnemonic used by Anvil's local accounts; the chain is ephemeral.
OWNER_MNEMONIC = "test test test test test test test test test test test junk"
Account.enable_unaudited_hdwallet_features()
OWNER_ACCOUNT = Account.from_mnemonic(OWNER_MNEMONIC)
OWNER_PRIVATE_KEY = "0x" + OWNER_ACCOUNT.key.hex()
OWNER = OWNER_ACCOUNT.address
ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _rpc(url: str, method: str, params: list[object]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.load(response)
    if "error" in payload:
        raise RuntimeError(f"Anvil RPC {method} failed: {payload['error']}")
    return payload["result"]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def anvil_url() -> Iterator[str]:
    if shutil.which("anvil") is None:
        pytest.skip("anvil is required for the live treasury setup integration")
    port = _free_port()
    process = subprocess.Popen(
        [
            "anvil",
            "--silent",
            "--port",
            str(port),
            "--chain-id",
            str(CHAIN_ID),
            "--mnemonic",
            OWNER_MNEMONIC,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try:
                assert int(_rpc(url, "eth_chainId", []), 16) == CHAIN_ID
                break
            except (OSError, RuntimeError, ValueError):
                time.sleep(0.1)
        else:
            pytest.fail("Anvil did not start")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=5)


def _deploy_fixture(anvil_url: str) -> dict[str, str]:
    if shutil.which("forge") is None:
        pytest.skip("forge is required to deploy the real Safe and module contracts")
    fixture_name = f"setup-wizard-{uuid.uuid4().hex}.json"
    fixture_path = REPO_ROOT / "deployments" / "predictions" / fixture_name
    relative_path = f"../deployments/predictions/{fixture_name}"
    env = {
        **os.environ,
        "SETUP_PRIVATE_KEY": OWNER_PRIVATE_KEY,
        "SETUP_SALT_NONCE": str(int(uuid.uuid4().hex[:8], 16)),
        "SETUP_FIXTURE_PATH": relative_path,
    }
    try:
        artifacts = subprocess.run(
            ["forge", "build", "script/SafeArtifactBundle.s.sol"],
            cwd=REPO_ROOT / "contracts",
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if artifacts.returncode != 0:
            raise AssertionError(
                f"forge Safe artifact build failed:\n{artifacts.stdout}\n{artifacts.stderr}"
            )
        result = subprocess.run(
            [
                "forge",
                "script",
                "script/SetupWizardFixture.s.sol:SetupWizardFixture",
                "--rpc-url",
                anvil_url,
                "--broadcast",
            ],
            cwd=REPO_ROOT / "contracts",
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"forge fixture deployment failed:\n{result.stdout}\n{result.stderr}"
            )
        return json.loads(fixture_path.read_text(encoding="utf-8"))
    finally:
        fixture_path.unlink(missing_ok=True)


def _configuration(anvil_url: str, fixture: dict[str, str]) -> PlatformConfiguration:
    def deployment(name: str, fixture_field: str, version: str) -> DeploymentConfig:
        address = fixture[fixture_field]
        code = bytes.fromhex(
            str(_rpc(anvil_url, "eth_getCode", [address, "latest"])).removeprefix("0x")
        )
        assert code, f"fixture deployment {name} has no runtime code"
        return DeploymentConfig(
            name=name,
            address=address,
            code_hash="0x" + keccak(code).hex(),
            version=version,
        )

    chain = ChainConfig.model_validate(
        {
            "chainId": CHAIN_ID,
            "name": "Setup wizard Anvil",
            "isTestnet": True,
            "confirmations": 0,
            "explorerUrl": "https://explorer.example.test",
            "rpcUrls": [anvil_url, f"http://127.0.0.1:{_free_port()}"],
            "assets": [
                {
                    "address": fixture["token"],
                    "symbol": "tUSDC",
                    "decimals": 6,
                    "issuerLabel": "Ephemeral Anvil asset",
                    "isTest": True,
                }
            ],
        }
    )
    manifest = DeploymentManifest(
        chain_id=CHAIN_ID,
        deployments=(
            deployment("SAFE_SINGLETON_L2", "safeSingleton", "1.4.1"),
            deployment("SAFE_PROXY_FACTORY", "safeProxyFactory", "1.4.1"),
            deployment("SAFE_MULTISEND_CALL_ONLY", "multiSendCallOnly", "1.4.1"),
            deployment("SAFE_FALLBACK_HANDLER", "fallbackHandler", "1.4.1"),
            deployment("TREASURY_MODULE_IMPLEMENTATION", "moduleImplementation", "1.0.0"),
            deployment("TREASURY_MODULE_FACTORY", "moduleFactory", "1.0.0"),
        ),
    )
    return PlatformConfiguration(chains=(chain,), manifests=(manifest,))


class _OrganizationRepository:
    async def member_roles(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> frozenset[str] | None:
        return frozenset({"Owner"}) if organization_id == ORG_ID and user_id == USER_ID else None


class _StepUp:
    def require_step_up(self, access: Any) -> None:
        return None


def _client(
    monkeypatch: pytest.MonkeyPatch,
    treasury_service: TreasuryService,
    governance_service: GovernanceService,
    configuration: PlatformConfiguration,
) -> TestClient:
    access = SimpleNamespace(
        user=SimpleNamespace(id=USER_ID),
        organization_scope_id=None,
        step_up_at=datetime.now(UTC),
    )

    async def authenticated(
        request: Any, require_csrf: bool = False, allow_scoped: bool = False
    ) -> Any:
        return access

    monkeypatch.setattr(rbac, "_authenticated", authenticated)
    monkeypatch.setattr(rbac, "_service", lambda request: _StepUp())
    app = FastAPI()
    app.include_router(treasury_router)
    app.include_router(governance_router)
    app.state.organization_repository = _OrganizationRepository()
    app.state.treasury_service = treasury_service
    app.state.governance_service = governance_service
    app.state.platform_configuration = configuration

    @app.exception_handler(AuthFailure)
    async def auth_failure(request: Any, exc: AuthFailure) -> Any:
        return problem_response(request, exc)

    return TestClient(app)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _prepare_database(
    database_url: str, configuration: PlatformConfiguration
) -> tuple[Any, Any]:
    # TestClient and the worker exercise separate event loops; avoid reusing asyncpg
    # connections across those loops.
    engine = create_async_engine(database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session, session.begin():
        session.add_all(
            [
                User(id=USER_ID, email=f"setup-{USER_ID}@example.test"),
                Organization(id=ORG_ID, name="Setup wizard Anvil"),
            ]
        )
    async with sessions() as session, session.begin():
        session.add_all(
            [
                Membership(id=uuid.uuid4(), org_id=ORG_ID, user_id=USER_ID, roles=["Owner"]),
                WalletLink(
                    id=uuid.uuid4(),
                    user_id=USER_ID,
                    address=bytes.fromhex(OWNER[2:]),
                    is_contract=False,
                ),
            ]
        )
    async with sessions() as session:
        await sync_platform_configuration(session, configuration, {})
    return engine, sessions


def _execute_setup_transaction(
    client: TestClient,
    anvil_url: str,
    tx: dict[str, Any],
    org_id: uuid.UUID,
) -> dict[str, Any]:
    tx_id = tx["id"]
    signature = (
        Account.from_key(OWNER_PRIVATE_KEY)
        .sign_message(encode_typed_data(full_message=tx["typedData"]))
        .signature
    )
    signed = client.post(
        f"/v1/orgs/{org_id}/governance-txs/{tx_id}/signatures",
        json={"signature": "0x" + bytes(signature).hex()},
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "Ready"

    exec_call = client.get(f"/v1/orgs/{org_id}/governance-txs/{tx_id}/exec-call")
    assert exec_call.status_code == 200, exec_call.text
    _rpc(anvil_url, "evm_setAutomine", [False])
    try:
        transaction_hash = str(
            _rpc(
                anvil_url,
                "eth_sendTransaction",
                [
                    {
                        "from": OWNER,
                        "to": exec_call.json()["to"],
                        "data": exec_call.json()["data"],
                        "gas": "0x989680",
                    }
                ],
            )
        )
        submitted = client.post(
            f"/v1/orgs/{org_id}/governance-txs/{tx_id}/submitted",
            json={"transactionHash": transaction_hash},
        )
        assert submitted.status_code == 200, submitted.text
        _rpc(anvil_url, "evm_mine", [])
    finally:
        _rpc(anvil_url, "evm_setAutomine", [True])

    refreshed = client.get(f"/v1/orgs/{org_id}/governance-txs/{tx_id}")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["status"] == "Executed", refreshed.text
    return refreshed.json()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL setup wizard integration",
)
def test_owner_setup_uses_live_api_safe_module_and_coverage(
    anvil_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _deploy_fixture(anvil_url)
    configuration = _configuration(anvil_url, fixture)
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    command.upgrade(_alembic_config(database_url), "head")
    engine, sessions = asyncio.run(_prepare_database(database_url, configuration))
    verifier = RpcSafeVerifier(configuration, {})
    client = _client(
        monkeypatch,
        TreasuryService(sessions, verifier, configuration),
        GovernanceService(sessions, verifier, configuration, {}),
        configuration,
    )
    token_id = asset_id(CHAIN_ID, fixture["token"])
    safe_t = fixture["safeT"]
    safe_o1 = fixture["safeO1"]

    try:
        invalid = client.post(
            f"/v1/orgs/{ORG_ID}/treasuries",
            json={
                "chainId": CHAIN_ID,
                "assetId": str(token_id),
                "wallets": [
                    {"role": "SOURCE", "safeAddress": safe_t, "label": "T"},
                    {"role": "OPERATIONAL", "safeAddress": OWNER, "label": "O1"},
                ],
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()["errors"][0]["field"] == "wallets.O1"

        created = client.post(
            f"/v1/orgs/{ORG_ID}/treasuries",
            json={
                "chainId": CHAIN_ID,
                "assetId": str(token_id),
                "wallets": [
                    {"role": "SOURCE", "safeAddress": safe_t, "label": "T"},
                    {"role": "OPERATIONAL", "safeAddress": safe_o1, "label": "O1"},
                ],
            },
        )
        assert created.status_code == 201, created.text
        treasury_id = created.json()["treasury"]["id"]
        assert created.json()["treasury"]["status"] == "Draft"
        assert [wallet["safeAddress"].lower() for wallet in created.json()["wallets"]] == [
            safe_t.lower(),
            safe_o1.lower(),
        ]

        now = datetime.now(UTC)
        setup = client.post(
            f"/v1/orgs/{ORG_ID}/treasuries/{treasury_id}/module/deploy-tx",
            json={
                "mandate": {
                    "validFrom": (now - timedelta(minutes=1)).isoformat(),
                    "expiresAt": (now + timedelta(days=7)).isoformat(),
                    "payeeCoolingSeconds": 60,
                    "executor": OWNER,
                    "guardian": None,
                    "pay": {"perRequest": "0", "daily": "0"},
                    "refill": {"perRequest": "0", "daily": "0"},
                    "supply": {"perRequest": "0", "daily": "0"},
                    "approvalMaxAge": 86400,
                    "approvers": [OWNER],
                },
                "buffers": [
                    {"wallet": safe_t, "minimum": "0", "target": "0"},
                    {"wallet": safe_o1, "minimum": "0", "target": "0"},
                ],
            },
        )
        assert setup.status_code == 201, setup.text
        assert setup.json()["status"] == "ModulePending"
        assert setup.json()["predictedModuleAddress"]

        transactions = [
            setup.json()["governanceTx"],
            *setup.json()["operationalGovernanceTxs"],
        ]
        assert len(transactions) == 2
        for tx in transactions:
            _execute_setup_transaction(client, anvil_url, tx, ORG_ID)

        treasury = client.get(f"/v1/orgs/{ORG_ID}/treasuries/{treasury_id}")
        assert treasury.status_code == 200, treasury.text
        assert treasury.json()["treasury"]["status"] == "Ready"
        assert (
            treasury.json()["treasury"]["moduleAddress"].lower()
            == setup.json()["predictedModuleAddress"].lower()
        )

        snapshot_count = asyncio.run(
            refresh_safe_config_snapshots(database_url, treasury_id=uuid.UUID(treasury_id))
        )
        assert snapshot_count == 2
        coverage = client.post(f"/v1/orgs/{ORG_ID}/treasuries/{treasury_id}/coverage/refresh")
        assert coverage.status_code == 200, coverage.text
        assert coverage.json()["coverage"]["status"] == "COMPLETE"
        assert coverage.json()["coverage"]["executionAllowed"] is True

        async def check_persisted_rows() -> tuple[int, int]:
            async with sessions() as session:
                wallet_ids = select(TreasuryWallet.id).where(
                    TreasuryWallet.treasury_id == uuid.UUID(treasury_id)
                )
                wallets = await session.scalar(
                    select(func.count())
                    .select_from(TreasuryWallet)
                    .where(TreasuryWallet.treasury_id == uuid.UUID(treasury_id))
                )
                snapshots = await session.scalar(
                    select(func.count())
                    .select_from(SafeConfigSnapshot)
                    .where(SafeConfigSnapshot.wallet_id.in_(wallet_ids))
                )
                return int(wallets or 0), int(snapshots or 0)

        # API-visible COMPLETE is backed by both registered Safes' persisted snapshots.
        assert asyncio.run(check_persisted_rows()) == (2, 2)
    finally:
        asyncio.run(engine.dispose())
