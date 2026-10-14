from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from eth_abi import decode as abi_decode
from eth_utils import keccak
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from treasurypilot_api.audit.models import AuditLog
from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity import rbac
from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import Membership, Organization, User
from treasurypilot_api.treasury import safe as safe_module
from treasurypilot_api.treasury.api import router
from treasurypilot_api.treasury.config import (
    AssetConfig,
    ChainConfig,
    DeploymentConfig,
    DeploymentManifest,
    PlatformConfiguration,
)
from treasurypilot_api.treasury.models import (
    Asset,
    Chain,
    Coverage,
    SafeConfigSnapshot,
    Treasury,
    TreasuryStatus,
    TreasuryWallet,
    WalletRole,
)
from treasurypilot_api.treasury.safe import (
    RpcUnavailable,
    SafeDeploymentCodeMismatch,
    SafeInfo,
    SafeVerificationError,
    UnsupportedChain,
    build_safe_deployment_transaction,
    verify_safe_deployment_code,
)
from treasurypilot_api.treasury.service import (
    TreasuryNotFound,
    TreasuryRecord,
    TreasuryRequestError,
    TreasuryService,
    TreasurySummaryRecord,
    WalletInput,
    WalletRecord,
    owner_set_warnings,
)
from treasurypilot_api.treasury.sync import asset_id

API_ROOT = Path(__file__).parents[1]
CHAIN_ID = 31337
TOKEN = "0x" + "ab" * 20
ASSET = asset_id(CHAIN_ID, TOKEN)
ORG = uuid.uuid4()
USER = uuid.uuid4()
SAFES = ["0x" + f"{i:040x}" for i in (0x501, 0x502, 0x503)]
OWNERS = ["0x" + f"{i:040x}" for i in (0xA1, 0xA2, 0xA3)]


def _payload(addresses: Sequence[str] = SAFES, asset: uuid.UUID = ASSET) -> dict[str, Any]:
    roles = ["SOURCE", "OPERATIONAL", "OPERATIONAL"]
    return {
        "chainId": CHAIN_ID,
        "assetId": str(asset),
        "wallets": [
            {"role": role, "safeAddress": address}
            for role, address in zip(roles, addresses, strict=False)
        ],
    }


def _record(treasury_id: uuid.UUID | None = None) -> TreasuryRecord:
    wallets = tuple(
        WalletRecord(uuid.uuid4(), role, label, address, tuple(OWNERS), 2)
        for role, label, address in zip(
            (WalletRole.SOURCE, WalletRole.OPERATIONAL), ("T", "O1"), SAFES, strict=False
        )
    )
    return TreasuryRecord(
        id=treasury_id or uuid.uuid4(),
        org_id=ORG,
        chain_id=CHAIN_ID,
        asset_id=ASSET,
        status=TreasuryStatus.DRAFT,
        coverage=Coverage.UNKNOWN,
        module_address=None,
        created_at=datetime.now(UTC),
        wallets=wallets,
        warnings=(),
    )


class FakeService:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.created: list[dict[str, Any]] = []
        self.coverage_refreshes: list[dict[str, Any]] = []
        self.coverage_acknowledgments: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> TreasuryRecord:
        if self.error is not None:
            raise self.error
        self.created.append(kwargs)
        return _record()

    async def get(self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID) -> TreasuryRecord:
        if self.error is not None:
            raise self.error
        return _record(treasury_id)

    async def list_for_org(
        self, *, organization_id: uuid.UUID
    ) -> tuple[TreasurySummaryRecord, ...]:
        assert organization_id == ORG
        return (
            TreasurySummaryRecord(
                uuid.UUID(int=1),
                31337,
                ASSET,
                TreasuryStatus.DRAFT,
                Coverage.UNKNOWN,
                datetime.now(UTC),
            ),
            TreasurySummaryRecord(
                uuid.UUID(int=2),
                84532,
                uuid.UUID(int=2),
                TreasuryStatus.READY,
                Coverage.COMPLETE,
                datetime.now(UTC),
            ),
        )

    async def refresh_coverage(self, **kwargs: Any) -> TreasuryRecord:
        self.coverage_refreshes.append(kwargs)
        return _record(kwargs["treasury_id"])

    async def acknowledge_coverage(self, **kwargs: Any) -> TreasuryRecord:
        self.coverage_acknowledgments.append(kwargs)
        return _record(kwargs["treasury_id"])


class Roles:
    def __init__(self, roles: set[str] | None) -> None:
        self.roles = roles

    async def member_roles(self, *, organization_id: uuid.UUID, user_id: uuid.UUID) -> Any:
        return None if self.roles is None else frozenset(self.roles)


def _client(
    monkeypatch: pytest.MonkeyPatch, roles: set[str] | None, service: FakeService
) -> TestClient:
    async def authenticated(
        request: Any, require_csrf: bool = False, allow_scoped: bool = False
    ) -> Any:
        return SimpleNamespace(user=SimpleNamespace(id=USER), organization_scope_id=None)

    monkeypatch.setattr(rbac, "_authenticated", authenticated)
    app = FastAPI()
    app.include_router(router)
    app.state.organization_repository = Roles(roles)
    app.state.treasury_service = service
    app.state.platform_configuration = _configuration()

    @app.exception_handler(AuthFailure)
    async def handler(request: Any, exc: AuthFailure) -> Any:
        return problem_response(request, exc)

    return TestClient(app)


@pytest.mark.parametrize("role", ["Owner", "OrgAdmin"])
def test_owner_and_admin_create_a_treasury(monkeypatch: pytest.MonkeyPatch, role: str) -> None:
    service = FakeService()
    response = _client(monkeypatch, {role}, service).post(
        f"/v1/orgs/{ORG}/treasuries", json=_payload()
    )
    assert response.status_code == 201
    body = response.json()
    assert body["treasury"]["status"] == "Draft"
    assert [w["label"] for w in body["wallets"]] == ["T", "O1"]
    assert service.created[0]["organization_id"] == ORG and service.created[0]["user_id"] == USER


@pytest.mark.parametrize("role", ["Finance", "Auditor", "Approver", "Guardian"])
def test_other_roles_cannot_create_but_can_read(monkeypatch: pytest.MonkeyPatch, role: str) -> None:
    client = _client(monkeypatch, {role}, FakeService())
    denied = client.post(f"/v1/orgs/{ORG}/treasuries", json=_payload())
    assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")
    assert client.get(f"/v1/orgs/{ORG}/treasuries/{uuid.uuid4()}").status_code == 200


def test_non_members_get_404(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, None, FakeService())
    for response in (
        client.post(f"/v1/orgs/{ORG}/treasuries", json=_payload()),
        client.get(f"/v1/orgs/{ORG}/treasuries/{uuid.uuid4()}"),
        client.get(f"/v1/orgs/{ORG}/treasuries"),
    ):
        assert (response.status_code, response.json()["code"]) == (404, "ORG_NOT_FOUND")


def test_treasury_list_keeps_chain_and_asset_rows_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _client(monkeypatch, {"Finance"}, FakeService()).get(f"/v1/orgs/{ORG}/treasuries")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [(item["chainId"], item["assetId"]) for item in items] == [
        (31337, str(ASSET)),
        (84532, str(uuid.UUID(int=2))),
    ]
    assert [item["status"] for item in items] == ["Draft", "Ready"]


def test_safe_deployment_endpoint_fails_closed_without_verified_deployments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _client(monkeypatch, {"Owner"}, FakeService()).post(
        f"/v1/orgs/{ORG}/safes/deploy-tx",
        json={"chainId": CHAIN_ID, "owners": OWNERS[:2], "threshold": 2},
    )
    assert (response.status_code, response.json()["code"]) == (
        503,
        "SAFE_DEPLOYMENT_UNAVAILABLE",
    )


def test_safe_deployment_endpoint_requires_owner_role(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _client(monkeypatch, {"Finance"}, FakeService()).post(
        f"/v1/orgs/{ORG}/safes/deploy-tx",
        json={"chainId": CHAIN_ID, "owners": OWNERS[:2], "threshold": 2},
    )
    assert (response.status_code, response.json()["code"]) == (403, "FORBIDDEN")


def _without_fallback_handler(
    deployments: tuple[DeploymentConfig, ...],
) -> tuple[DeploymentConfig, ...]:
    # The base config already pins a fallback handler; Safe deploy tests supply their own.
    return tuple(d for d in deployments if d.name != "SAFE_FALLBACK_HANDLER")


def test_safe_deployment_transaction_uses_manifest_factory_and_safe_setup() -> None:
    base = _configuration()
    current = base.manifests[0]
    deployments = (
        *_without_fallback_handler(current.deployments),
        *(
            DeploymentConfig(
                name=name,
                address="0x" + f"{index:040x}",
                code_hash="0x" + f"{index:064x}",
                version="1.4.1",
            )
            for name, index in (
                ("SAFE_SINGLETON_L1", 0x601),
                ("SAFE_PROXY_FACTORY", 0x602),
                ("SAFE_FALLBACK_HANDLER", 0x603),
            )
        ),
    )
    configuration = PlatformConfiguration(
        chains=base.chains,
        manifests=(DeploymentManifest(chain_id=CHAIN_ID, deployments=deployments),),
    )
    transaction = build_safe_deployment_transaction(configuration, CHAIN_ID, OWNERS[:2], 2, 123)
    assert transaction["to"] == "0x" + f"{0x602:040x}"
    assert transaction["value"] == "0"
    factory_call = bytes.fromhex(transaction["data"][2:])
    assert factory_call[:4] == keccak(text="createProxyWithNonce(address,bytes,uint256)")[:4]
    singleton, setup_data, salt_nonce = abi_decode(
        ["address", "bytes", "uint256"], factory_call[4:]
    )
    assert singleton == "0x" + f"{0x601:040x}"
    assert salt_nonce == 123
    assert (
        setup_data[:4]
        == keccak(text="setup(address[],uint256,address,bytes,address,address,uint256,address)")[:4]
    )
    owners, threshold, _, _, fallback_handler, _, _, _ = abi_decode(
        ["address[]", "uint256", "address", "bytes", "address", "address", "uint256", "address"],
        setup_data[4:],
    )
    assert [owner.lower() for owner in owners] == [owner.lower() for owner in OWNERS[:2]]
    assert threshold == 2 and fallback_handler == "0x" + f"{0x603:040x}"


def test_safe_deployment_manifest_hashes_must_match_live_runtime_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _configuration()
    runtime_code = b"verified Safe deployment bytecode"
    runtime_hash = "0x" + keccak(runtime_code).hex()
    deployment_values = (
        ("SAFE_SINGLETON_L1", 0x601),
        ("SAFE_PROXY_FACTORY", 0x602),
        ("SAFE_FALLBACK_HANDLER", 0x603),
    )

    def configuration(code_hash: str) -> PlatformConfiguration:
        entries = (
            *_without_fallback_handler(base.manifests[0].deployments),
            *(
                DeploymentConfig(
                    name=name,
                    address="0x" + f"{index:040x}",
                    code_hash=code_hash,
                    version="1.4.1",
                )
                for name, index in deployment_values
            ),
        )
        return PlatformConfiguration(
            chains=base.chains,
            manifests=(DeploymentManifest(chain_id=CHAIN_ID, deployments=entries),),
        )

    def rpc(url: str, method: str, params: list[object]) -> str:
        if method == "eth_chainId":
            return hex(CHAIN_ID)
        assert method == "eth_getCode"
        return "0x" + runtime_code.hex()

    monkeypatch.setattr(safe_module, "_rpc", rpc)
    asyncio.run(verify_safe_deployment_code(configuration(runtime_hash), CHAIN_ID, {}))
    with pytest.raises(SafeDeploymentCodeMismatch):
        asyncio.run(verify_safe_deployment_code(configuration("0x" + "ff" * 32), CHAIN_ID, {}))
    with pytest.raises(UnsupportedChain):
        asyncio.run(verify_safe_deployment_code(configuration(runtime_hash), 999, {}))


def test_safe_deployment_prefers_l2_singleton_off_l1_chains_and_checks_owner_format() -> None:
    base = _configuration()
    entries = (
        *_without_fallback_handler(base.manifests[0].deployments),
        *(
            DeploymentConfig(
                name=name,
                address="0x" + f"{index:040x}",
                code_hash="0x" + f"{index:064x}",
                version="1.4.1",
            )
            for name, index in (
                ("SAFE_SINGLETON_L1", 0x601),
                ("SAFE_SINGLETON_L2", 0x604),
                ("SAFE_PROXY_FACTORY", 0x602),
                ("SAFE_FALLBACK_HANDLER", 0x603),
            )
        ),
    )
    configuration = PlatformConfiguration(
        chains=base.chains,
        manifests=(DeploymentManifest(chain_id=CHAIN_ID, deployments=entries),),
    )
    data = bytes.fromhex(
        build_safe_deployment_transaction(configuration, CHAIN_ID, OWNERS[:1], 1, 1)["data"][2:]
    )
    assert abi_decode(["address", "bytes", "uint256"], data[4:])[0] == "0x" + f"{0x604:040x}"
    for bad in (OWNERS[0][2:], "0x" + "aB" * 20):
        with pytest.raises(ValueError, match="valid Ethereum addresses"):
            build_safe_deployment_transaction(configuration, CHAIN_ID, [bad], 1, 1)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (TreasuryRequestError("NOT_A_SAFE", "x"), 422, "NOT_A_SAFE"),
        (TreasuryRequestError("DUPLICATE_WALLET", "x"), 422, "DUPLICATE_WALLET"),
        (TreasuryRequestError("SAFE_VERSION_UNSUPPORTED", "x"), 422, "SAFE_VERSION_UNSUPPORTED"),
        (RpcUnavailable("x"), 503, "RPC_UNAVAILABLE"),
    ],
)
def test_domain_errors_map_to_problem_responses(
    monkeypatch: pytest.MonkeyPatch, error: Exception, status: int, code: str
) -> None:
    service = FakeService()
    service.error = error
    response = _client(monkeypatch, {"Owner"}, service).post(
        f"/v1/orgs/{ORG}/treasuries", json=_payload()
    )
    assert (response.status_code, response.json()["code"]) == (status, code)


def test_non_safe_verification_error_identifies_the_wallet_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeService()
    service.error = TreasuryRequestError(
        "NOT_A_SAFE", "No Safe contract was found at this address.", address=SAFES[1]
    )
    payload = _payload()
    payload["wallets"][1]["label"] = "O1"
    response = _client(monkeypatch, {"Owner"}, service).post(
        f"/v1/orgs/{ORG}/treasuries", json=payload
    )
    assert response.status_code == 422
    assert response.json()["errors"] == [
        {
            "field": "wallets.O1",
            "message": "No Safe contract was found at this address.",
        }
    ]


def test_unknown_treasury_is_404_and_bad_input_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeService()
    client = _client(monkeypatch, {"Owner"}, service)
    service.error = TreasuryNotFound()
    missing = client.get(f"/v1/orgs/{ORG}/treasuries/{uuid.uuid4()}")
    assert (missing.status_code, missing.json()["code"]) == (404, "TREASURY_NOT_FOUND")
    bad = _payload()
    bad["wallets"][0]["safeAddress"] = "0x1234"
    assert client.post(f"/v1/orgs/{ORG}/treasuries", json=bad).status_code == 422
    assert client.post(f"/v1/orgs/{ORG}/treasuries", json=_payload(SAFES[:1])).status_code == 422


def test_coverage_refresh_is_available_to_owner_and_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeService()
    response = _client(monkeypatch, {"OrgAdmin"}, service).post(
        f"/v1/orgs/{ORG}/treasuries/{uuid.uuid4()}/coverage/refresh"
    )

    assert response.status_code == 200
    assert response.json()["coverage"]["status"] == "UNKNOWN"
    assert response.json()["coverage"]["executionAllowed"] is False
    assert service.coverage_refreshes[0]["organization_id"] == ORG


def test_only_owner_can_acknowledge_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeService()
    treasury_id = uuid.uuid4()
    denied = _client(monkeypatch, {"OrgAdmin"}, service).post(
        f"/v1/orgs/{ORG}/treasuries/{treasury_id}/coverage/acknowledge",
        json={"reason": "Reviewed the Safe setup"},
    )
    assert (denied.status_code, denied.json()["code"]) == (403, "FORBIDDEN")
    assert service.coverage_acknowledgments == []

    accepted = _client(monkeypatch, {"Owner"}, service).post(
        f"/v1/orgs/{ORG}/treasuries/{treasury_id}/coverage/acknowledge",
        json={"reason": "Reviewed the Safe setup"},
    )
    assert accepted.status_code == 200
    assert service.coverage_acknowledgments[0]["user_id"] == USER


def _wallet(label: str, owners: Sequence[str], threshold: int) -> WalletRecord:
    return WalletRecord(
        uuid.uuid4(), WalletRole.OPERATIONAL, label, SAFES[0], tuple(owners), threshold
    )


def test_generated_labels_skip_user_supplied_ones() -> None:
    service = TreasuryService(None, None, _configuration())  # type: ignore[arg-type]
    wallets = [
        WalletInput(WalletRole.SOURCE, SAFES[0], "O1"),
        WalletInput(WalletRole.OPERATIONAL, SAFES[1], None),
        WalletInput(WalletRole.OPERATIONAL, SAFES[2], "t"),
    ]
    labels = [label for _, _, label in service._validate(CHAIN_ID, ASSET, wallets)]
    assert labels == ["O1", "O2", "t"]
    wallets[0] = WalletInput(WalletRole.SOURCE, SAFES[0], None)
    labels = [label for _, _, label in service._validate(CHAIN_ID, ASSET, wallets)]
    assert labels == ["T2", "O1", "t"]


def test_differing_owner_sets_or_thresholds_warn() -> None:
    same = [
        _wallet("T", OWNERS, 2),
        _wallet("O1", [o.upper().replace("X", "x") for o in OWNERS], 2),
    ]
    assert owner_set_warnings(same) == ()
    for other in (_wallet("O1", OWNERS[:2], 2), _wallet("O1", OWNERS, 1)):
        (warning,) = owner_set_warnings([_wallet("T", OWNERS, 2), other])
        assert warning.code == "OWNER_SETS_DIFFER" and warning.wallets == ("T", "O1")


# --- PostgreSQL integration: persistence, tenant isolation, audit ---


class FakeVerifier:
    def __init__(self) -> None:
        self.owners: dict[str, tuple[str, ...]] = {}
        self.reject: tuple[str, str] | None = None
        self.calls = 0

    async def verify(self, chain_id: int, addresses: Sequence[str]) -> list[SafeInfo]:
        self.calls += 1
        if self.reject is not None:
            raise SafeVerificationError(*self.reject)
        return [
            SafeInfo(
                address=a,
                master_copy="0x" + "41" * 20,
                version="1.4.1",
                owners=self.owners.get(a, tuple(OWNERS)),
                threshold=2,
                block_number=7,
            )
            for a in addresses
        ]


def _configuration() -> PlatformConfiguration:
    chain = ChainConfig.model_validate(
        {
            "chainId": CHAIN_ID,
            "name": "Anvil",
            "isTestnet": True,
            "confirmations": 0,
            "explorerUrl": "https://explorer.example",
            "rpcUrls": ["http://a.test", "http://b.test"],
            "assets": [
                AssetConfig.model_validate(
                    {"address": TOKEN, "symbol": "tUSDC", "decimals": 6, "issuerLabel": "T"}
                ).model_dump(by_alias=True)
            ],
        }
    )
    manifest = DeploymentManifest(
        chain_id=CHAIN_ID,
        deployments=(
            DeploymentConfig(
                name="TREASURY_MODULE_IMPLEMENTATION",
                address="0x" + "11" * 20,
                code_hash="0x" + "22" * 32,
                version="1",
            ),
            DeploymentConfig(
                name="SAFE_FALLBACK_HANDLER",
                address="0x" + "33" * 20,
                code_hash="0x" + "44" * 32,
                version="1.4.1",
            ),
        ),
    )
    return PlatformConfiguration(chains=(chain,), manifests=(manifest,))


async def _exercise(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    try:
        user = User(email=f"{uuid.uuid4()}@example.com")
        org_a, org_b = Organization(name="A"), Organization(name="B")
        async with sessions() as session, session.begin():
            session.add_all([user, org_a, org_b])
            session.add(
                Chain(
                    chain_id=CHAIN_ID,
                    name="Anvil",
                    is_testnet=True,
                    confirmations=0,
                    explorer_url="https://explorer.example",
                    rpc_urls=["http://a.test", "http://b.test"],
                )
            )
            await session.flush()
            session.add(
                Asset(
                    id=ASSET,
                    chain_id=CHAIN_ID,
                    address=bytes.fromhex(TOKEN[2:]),
                    symbol="tUSDC",
                    decimals=6,
                    issuer_label="T",
                    is_test=True,
                )
            )
            for org in (org_a, org_b):
                session.add(Membership(org_id=org.id, user_id=user.id, roles=["OrgAdmin"]))
        verifier = FakeVerifier()
        service = TreasuryService(sessions, verifier, _configuration())

        def wallets(addresses: Sequence[str]) -> list[WalletInput]:
            roles = (WalletRole.SOURCE, WalletRole.OPERATIONAL, WalletRole.OPERATIONAL)
            return [WalletInput(r, a) for r, a in zip(roles, addresses, strict=False)]

        async def create(org: Organization, addresses: Sequence[str], **kw: Any) -> Any:
            args: dict[str, Any] = {"chain_id": CHAIN_ID, "asset": ASSET, **kw}
            return await service.create(
                organization_id=org.id, user_id=user.id, wallets=wallets(addresses), **args
            )

        async def rejected(
            code: str, org: Organization, addresses: Sequence[str], **kw: Any
        ) -> None:
            with pytest.raises(TreasuryRequestError) as raised:
                await create(org, addresses, **kw)
            assert raised.value.code == code

        # Valid set of three Safes creates the treasury with owners, thresholds and an audit entry.
        created = await create(org_a, SAFES)
        assert created.status is TreasuryStatus.DRAFT and created.coverage is Coverage.UNKNOWN
        assert [(w.label, w.role.value) for w in created.wallets] == [
            ("T", "SOURCE"),
            ("O1", "OPERATIONAL"),
            ("O2", "OPERATIONAL"),
        ]
        assert created.warnings == ()
        fetched = await service.get(organization_id=org_a.id, treasury_id=created.id)
        assert fetched.wallets == created.wallets
        second_addresses = ["0x" + f"{i:040x}" for i in (0x504, 0x505, 0x506)]
        second_created = await create(org_a, second_addresses)
        org_treasuries = await service.list_for_org(organization_id=org_a.id)
        assert {row.id for row in org_treasuries} == {created.id, second_created.id}
        assert {row.chain_id for row in org_treasuries} == {CHAIN_ID}
        assert await service.list_for_org(organization_id=org_b.id) == ()
        async with sessions() as session:
            entries = list(
                await session.scalars(select(AuditLog).where(AuditLog.org_id == org_a.id))
            )
        (entry,) = [e for e in entries if e.action == "treasury.created"]
        assert entry.entity_id == str(created.id) and entry.actor_id == str(user.id)
        assert entry.data["wallets"][0]["safeVersion"] == "1.4.1"

        module = bytes.fromhex("55" * 20)
        implementation = bytes.fromhex("11" * 20)
        fallback = bytes.fromhex("33" * 20)
        async with sessions() as session, session.begin():
            treasury_row = await session.get(Treasury, created.id)
            assert treasury_row is not None
            treasury_row.module_address = module
            treasury_wallets = list(
                await session.scalars(
                    select(TreasuryWallet).where(TreasuryWallet.treasury_id == created.id)
                )
            )
            for index, wallet in enumerate(treasury_wallets):
                session.add(
                    SafeConfigSnapshot(
                        org_id=org_a.id,
                        wallet_id=wallet.id,
                        block_number=100,
                        block_hash=bytes([index + 1]) * 32,
                        owners=list(OWNERS),
                        threshold=2,
                        modules=[module],
                        guard=None,
                        fallback_handler=fallback,
                        module_implementations={"0x" + module.hex(): "0x" + implementation.hex()},
                    )
                )
        complete = await service.refresh_coverage(organization_id=org_a.id, treasury_id=created.id)
        assert complete.coverage is Coverage.COMPLETE
        assert not complete.coverage_acknowledged

        extra_module = bytes.fromhex("66" * 20)
        async with sessions() as session, session.begin():
            first_wallet = treasury_wallets[0]
            session.add(
                SafeConfigSnapshot(
                    org_id=org_a.id,
                    wallet_id=first_wallet.id,
                    block_number=101,
                    block_hash=bytes.fromhex("aa" * 32),
                    owners=list(OWNERS),
                    threshold=2,
                    modules=[module, extra_module],
                    guard=None,
                    fallback_handler=fallback,
                    module_implementations={
                        "0x" + module.hex(): "0x" + implementation.hex(),
                        "0x" + extra_module.hex(): None,
                    },
                )
            )
        partial = await service.refresh_coverage(organization_id=org_a.id, treasury_id=created.id)
        assert partial.coverage is Coverage.PARTIAL
        acknowledged = await service.acknowledge_coverage(
            organization_id=org_a.id,
            treasury_id=created.id,
            user_id=user.id,
            reason="Reviewed the extra module risk",
        )
        assert acknowledged.coverage_acknowledged
        assert acknowledged.coverage_ack_reason == "Reviewed the extra module risk"
        async with sessions() as session:
            coverage_audits = list(
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.org_id == org_a.id,
                        AuditLog.action == "treasury.coverage.acknowledged",
                    )
                )
            )
        assert len(coverage_audits) == 1
        assert coverage_audits[0].data["reason"] == "Reviewed the extra module risk"

        # A new deviation (rogue guard) changes the details: the acknowledgment must not carry over.
        async with sessions() as session, session.begin():
            session.add(
                SafeConfigSnapshot(
                    org_id=org_a.id,
                    wallet_id=treasury_wallets[0].id,
                    block_number=102,
                    block_hash=bytes.fromhex("bb" * 32),
                    owners=list(OWNERS),
                    threshold=2,
                    modules=[module, extra_module],
                    guard=bytes.fromhex("99" * 20),
                    fallback_handler=fallback,
                    module_implementations={
                        "0x" + module.hex(): "0x" + implementation.hex(),
                        "0x" + extra_module.hex(): None,
                    },
                )
            )
        changed = await service.refresh_coverage(organization_id=org_a.id, treasury_id=created.id)
        assert changed.coverage is Coverage.PARTIAL
        assert not changed.coverage_acknowledged

        # Reads fail closed when snapshots go stale, even if the stored coverage is not UNKNOWN.
        async with sessions() as session, session.begin():
            await session.execute(
                update(SafeConfigSnapshot).values(
                    observed_at=datetime.now(UTC) - timedelta(minutes=30)
                )
            )
        stale = await service.get(organization_id=org_a.id, treasury_id=created.id)
        assert stale.coverage is Coverage.UNKNOWN

        # Tenant isolation: another org cannot read it.
        with pytest.raises(TreasuryNotFound):
            await service.get(organization_id=org_b.id, treasury_id=created.id)

        # A Safe already registered (even by another tenant) is a duplicate; no RPC is spent.
        calls = verifier.calls
        other = ["0x" + f"{i:040x}" for i in (0x601, 0x602, 0x603)]
        await rejected("DUPLICATE_WALLET", org_b, [other[0], SAFES[1], other[2]])
        assert verifier.calls == calls
        await rejected(
            "DUPLICATE_WALLET", org_b, [other[0], other[1], other[0].upper().replace("X", "x")]
        )
        await rejected("UNSUPPORTED_ASSET", org_b, other, asset=uuid.uuid4())
        await rejected("WRONG_CHAIN", org_b, other, chain_id=1)
        await rejected("INVALID_WALLET_SET", org_b, [])  # no wallets
        verifier.reject = ("NOT_A_SAFE", "eoa")
        await rejected("NOT_A_SAFE", org_b, other)
        verifier.reject = ("SAFE_VERSION_UNSUPPORTED", "old")
        await rejected("SAFE_VERSION_UNSUPPORTED", org_b, other)
        verifier.reject = None
        async with sessions() as session:
            assert await session.scalar(select(Organization.id).where(Organization.id == org_b.id))

        # Differing owner sets are a warning, not an error; the treasury is still created.
        verifier.owners[other[1]] = tuple(OWNERS[:2])
        warned = await create(org_b, other)
        assert [w.code for w in warned.warnings] == ["OWNER_SETS_DIFFER"]
        again = await service.get(organization_id=org_b.id, treasury_id=warned.id)
        assert [w.code for w in again.warnings] == ["OWNER_SETS_DIFFER"]
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL treasury integration test",
)
def test_postgres_treasury_creation() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise(database_url))
    finally:
        command.downgrade(config, "base")
