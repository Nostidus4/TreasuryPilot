from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from eth_account import Account
from eth_account.messages import encode_defunct
from siwe import SiweMessage
from web3 import Web3

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity import wallets as wallet_module
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import Membership, Organization, User, WalletLink
from treasurypilot_api.identity.repository import SqlAlchemyAuthRepository
from treasurypilot_api.identity.wallets import (
    MAX_OPEN_SIWE_NONCES,
    SIWE_CHAIN_ID,
    OwnerContext,
    SiweNonceRecord,
    WalletLinkRecord,
    WalletLinkService,
    WalletRepository,
)

ORIGIN = "https://app.example.test"
API_ROOT = Path(__file__).parents[1]


class MemoryWalletRepository(WalletRepository):
    def __init__(self) -> None:
        self.challenges: dict[str, SiweNonceRecord] = {}
        self.links: dict[bytes, uuid.UUID] = {}
        self.audit_actions: list[str] = []
        self.contexts: tuple[OwnerContext, ...] = ()
        self.refreshed: list[dict[uuid.UUID, bool]] = []
        self.unlinked: list[dict[uuid.UUID, bool]] = []

    async def create_nonce(
        self, *, nonce: str, user_id: uuid.UUID, created_at: datetime
    ) -> SiweNonceRecord:
        challenge = SiweNonceRecord(nonce, user_id, created_at, created_at + timedelta(minutes=10))
        self.challenges[nonce] = challenge
        return challenge

    async def get_nonce(self, *, nonce: str, user_id: uuid.UUID) -> SiweNonceRecord | None:
        challenge = self.challenges.get(nonce)
        return challenge if challenge is not None and challenge.user_id == user_id else None

    async def owner_contexts(self, *, user_id: uuid.UUID) -> tuple[OwnerContext, ...]:
        return self.contexts

    async def has_active_wallet(self, *, user_id: uuid.UUID, address: bytes) -> bool:
        return self.links.get(address) == user_id

    async def update_owner_statuses(
        self,
        *,
        user_id: uuid.UUID,
        statuses: Mapping[uuid.UUID, bool],
        checked_at: datetime,
        started_at: datetime,
    ) -> None:
        self.refreshed.append(dict(statuses))

    async def unlink_wallet(
        self,
        *,
        user_id: uuid.UUID,
        address: bytes,
        now: datetime,
        owner_statuses: Mapping[uuid.UUID, bool],
    ) -> None:
        self.unlinked.append(dict(owner_statuses))
        del self.links[address]

    async def link_wallet(
        self,
        *,
        nonce: str,
        user_id: uuid.UUID,
        address: bytes,
        is_contract: bool,
        signature_hash: str,
        now: datetime,
        owner_statuses: Mapping[uuid.UUID, bool],
    ) -> WalletLinkRecord:
        if nonce not in self.challenges:
            raise AuthFailure(
                status=400, code="SIWE_NONCE_INVALID", title="Invalid nonce", detail="Already used"
            )
        if address in self.links and self.links[address] != user_id:
            raise AuthFailure(
                status=409,
                code="ADDRESS_LINKED_ELSEWHERE",
                title="Already linked",
                detail="Other user",
            )
        del self.challenges[nonce]
        self.links[address] = user_id
        self.audit_actions.append("wallet.linked")
        return WalletLinkRecord(address, is_contract, now)


def _message(account: object, nonce: str) -> SiweMessage:
    now = datetime.now(UTC)
    return SiweMessage(
        domain="app.example.test",
        address=Web3.to_checksum_address(account.address),  # type: ignore[attr-defined]
        uri=ORIGIN,
        version="1",
        chain_id=SIWE_CHAIN_ID,
        issued_at=now.isoformat(),
        nonce=nonce,
        statement="Link this wallet to TreasuryPilot",
        expiration_time=(now + timedelta(minutes=10)).isoformat(),
    )


def _signature(message: SiweMessage, account: object) -> str:
    return (
        "0x"
        + Account.sign_message(
            encode_defunct(text=message.prepare_message()),
            account.key,  # type: ignore[attr-defined]
        ).signature.hex()
    )


def _service(
    monkeypatch: pytest.MonkeyPatch, repository: MemoryWalletRepository
) -> WalletLinkService:
    service = WalletLinkService(repository, allowed_origins=[ORIGIN], platform_configuration=None)
    monkeypatch.setattr(service, "_rpc_urls", lambda: ("http://rpc.test",))
    return service


def test_real_eoa_signature_links_once_and_records_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MemoryWalletRepository()
    service = _service(monkeypatch, repository)
    user_id = uuid.uuid4()
    account = Account.create()
    challenge = asyncio.run(service.issue_nonce(user_id=user_id, origin=ORIGIN))
    message = _message(account, challenge.nonce)
    signature = _signature(message, account)

    linked = asyncio.run(
        service.link_wallet(
            user_id=user_id,
            origin=ORIGIN,
            message_text=message.prepare_message(),
            signature=signature,
        )
    )
    assert linked.address == bytes.fromhex(account.address[2:])
    assert linked.is_contract is False
    assert repository.audit_actions == ["wallet.linked"]

    with pytest.raises(AuthFailure) as replay:
        asyncio.run(
            service.link_wallet(
                user_id=user_id,
                origin=ORIGIN,
                message_text=message.prepare_message(),
                signature=signature,
            )
        )
    assert replay.value.code == "SIWE_INVALID"


def test_wallet_linked_to_another_user_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MemoryWalletRepository()
    service = _service(monkeypatch, repository)
    user_id = uuid.uuid4()
    account = Account.create()
    repository.links[bytes.fromhex(account.address[2:])] = uuid.uuid4()
    challenge = asyncio.run(service.issue_nonce(user_id=user_id, origin=ORIGIN))
    message = _message(account, challenge.nonce)

    with pytest.raises(AuthFailure) as linked_elsewhere:
        asyncio.run(
            service.link_wallet(
                user_id=user_id,
                origin=ORIGIN,
                message_text=message.prepare_message(),
                signature=_signature(message, account),
            )
        )
    assert linked_elsewhere.value.code == "ADDRESS_LINKED_ELSEWHERE"
    assert challenge.nonce in repository.challenges


def test_erc1271_signature_uses_contract_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = Account.create()
    signer = Account.create()
    message = _message(contract, "contract1234")
    signature = _signature(message, signer)
    checked: list[str] = []

    class FakeEth:
        chain_id = SIWE_CHAIN_ID

        def get_code(self, address: str) -> bytes:
            assert address == contract.address
            return b"\x60\x00"

    class FakeWeb3:
        def __init__(self, provider: object) -> None:
            self.eth = FakeEth()

        to_checksum_address = staticmethod(Web3.to_checksum_address)

    def verify_contract(*, address: str, message: object, signature: str, w3: object) -> bool:
        checked.append(address)
        return True

    monkeypatch.setattr(wallet_module, "Web3", FakeWeb3)
    monkeypatch.setattr("siwe.siwe.check_contract_wallet_signature", verify_contract)
    assert (
        wallet_module._verify_siwe_sync(
            "http://rpc.test",
            message,
            signature,
            "app.example.test",
            "contract1234",
            datetime.now(UTC),
        )
        is True
    )
    assert checked == [contract.address]


class FakeRepositorySession:
    def __init__(
        self, scalar_values: list[object], memberships: list[object] | None = None
    ) -> None:
        self.scalar_values = iter(scalar_values)
        self.memberships = memberships or []

    async def __aenter__(self) -> FakeRepositorySession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> FakeRepositorySession:
        return self

    async def scalar(self, query: object, parameters: object = None) -> object:
        return next(self.scalar_values)

    async def scalars(self, query: object) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: self.memberships)


def test_repository_rejects_wallet_owned_by_another_user_before_consuming_nonce() -> None:
    now = datetime.now(UTC)
    user_id = uuid.uuid4()
    challenge = SimpleNamespace(used_at=None, expires_at=now + timedelta(minutes=10))
    existing = SimpleNamespace(user_id=uuid.uuid4())
    session = FakeRepositorySession([challenge, existing])
    repository = WalletRepository(lambda: session)  # type: ignore[arg-type]

    with pytest.raises(AuthFailure) as conflict:
        asyncio.run(
            repository.link_wallet(
                nonce="abcdefgh",
                user_id=user_id,
                address=bytes.fromhex("11" * 20),
                is_contract=False,
                signature_hash="hash",
                now=now,
                owner_statuses={},
            )
        )
    assert conflict.value.code == "ADDRESS_LINKED_ELSEWHERE"
    assert challenge.used_at is None


def _unavailable() -> tuple[str, ...]:
    raise AuthFailure(status=503, code="WALLET_VERIFICATION_UNAVAILABLE", title="x", detail="x")


def _owner_context(*, safe: bool = True) -> OwnerContext:
    return OwnerContext(
        org_id=uuid.uuid4(),
        wallet_addresses=(bytes.fromhex("33" * 20),),
        safe_addresses=(bytes.fromhex("22" * 20),) if safe else (),
        owner_is_onchain=True,
        owner_checked_at=datetime.now(UTC),
    )


def test_eoa_link_does_not_need_the_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = MemoryWalletRepository()
    repository.contexts = (_owner_context(),)
    service = _service(monkeypatch, repository)
    monkeypatch.setattr(service, "_rpc_urls", _unavailable)
    user_id = uuid.uuid4()
    account = Account.create()
    challenge = asyncio.run(service.issue_nonce(user_id=user_id, origin=ORIGIN))
    message = _message(account, challenge.nonce)

    linked = asyncio.run(
        service.link_wallet(
            user_id=user_id,
            origin=ORIGIN,
            message_text=message.prepare_message(),
            signature=_signature(message, account),
        )
    )
    assert linked.is_contract is False


def test_contract_signature_during_an_rpc_outage_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(monkeypatch, MemoryWalletRepository())
    monkeypatch.setattr(service, "_rpc_urls", _unavailable)
    contract, signer = Account.create(), Account.create()
    message = _message(contract, "contract1234")

    with pytest.raises(AuthFailure) as failure:
        asyncio.run(
            service._verify_signature(
                message=message,
                signature=_signature(message, signer),
                domain="app.example.test",
                nonce="contract1234",
                timestamp=datetime.now(UTC),
            )
        )
    assert (failure.value.status, failure.value.code) == (503, "WALLET_VERIFICATION_UNAVAILABLE")


def test_enabled_chain_without_rpc_urls_is_unavailable_not_a_bad_signature() -> None:
    chain = SimpleNamespace(chain_id=SIWE_CHAIN_ID, enabled=True, rpc_urls=[])
    service = WalletLinkService(
        MemoryWalletRepository(),
        allowed_origins=[ORIGIN],
        platform_configuration=SimpleNamespace(chains=(chain,)),  # type: ignore[arg-type]
    )
    with pytest.raises(AuthFailure) as failure:
        service._rpc_urls()
    assert (failure.value.status, failure.value.code) == (503, "WALLET_VERIFICATION_UNAVAILABLE")


def test_unlinking_an_unknown_wallet_is_404_without_touching_the_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MemoryWalletRepository()
    repository.contexts = (_owner_context(),)
    service = _service(monkeypatch, repository)
    monkeypatch.setattr(service, "_rpc_urls", _unavailable)

    with pytest.raises(AuthFailure) as failure:
        asyncio.run(service.unlink_wallet(user_id=uuid.uuid4(), address="0x" + "44" * 20))
    assert (failure.value.status, failure.value.code) == (404, "WALLET_NOT_FOUND")
    assert repository.unlinked == []


def test_unlink_works_during_an_rpc_outage_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MemoryWalletRepository()
    context = _owner_context()
    repository.contexts = (context,)
    service = _service(monkeypatch, repository)
    monkeypatch.setattr(service, "_rpc_urls", _unavailable)
    user_id = uuid.uuid4()
    removed = bytes.fromhex("44" * 20)
    repository.links[removed] = user_id
    # A second wallet remains, so ownership could only be re-derived from the chain.
    asyncio.run(service.unlink_wallet(user_id=user_id, address="0x" + removed.hex()))

    assert repository.unlinked == [{context.org_id: False}]
    assert removed not in repository.links


def test_failed_owner_refresh_backs_off_instead_of_retrying_every_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wallet_module, "_owner_refresh_blocked_until", 0.0)
    repository = MemoryWalletRepository()
    repository.contexts = (replace(_owner_context(), owner_checked_at=None),)
    service = _service(monkeypatch, repository)
    calls: list[int] = []

    def unavailable() -> tuple[str, ...]:
        calls.append(1)
        return _unavailable()

    monkeypatch.setattr(service, "_rpc_urls", unavailable)
    for _ in range(3):
        asyncio.run(service.refresh_owner_statuses(user_id=uuid.uuid4()))
    assert calls == [1]
    assert repository.refreshed == []


def test_refresh_does_not_overwrite_a_newer_status() -> None:
    started = datetime.now(UTC)
    org_id = uuid.uuid4()
    newer = SimpleNamespace(
        org_id=org_id,
        roles=("Owner",),
        owner_is_onchain=False,
        owner_checked_at=started + timedelta(seconds=1),
    )
    older = SimpleNamespace(
        org_id=org_id,
        roles=("Owner",),
        owner_is_onchain=False,
        owner_checked_at=started - timedelta(hours=2),
    )
    for membership in (newer, older):
        WalletRepository._apply_owner_statuses(
            [membership],  # type: ignore[list-item]
            statuses={org_id: True},
            checked_at=started + timedelta(seconds=2),
            started_at=started,
        )
    assert newer.owner_is_onchain is False
    assert older.owner_is_onchain is True


def test_nonce_creation_takes_a_per_user_lock_before_counting() -> None:
    now = datetime.now(UTC)
    statements: list[str] = []

    class Session(FakeRepositorySession):
        def add(self, row: object) -> None:
            statements.append("insert")

        async def execute(self, query: object, parameters: object = None) -> None:
            statements.append(str(query))

        async def scalar(self, query: object, parameters: object = None) -> object:
            statements.append("count")
            return 0

    session = Session([])
    repository = WalletRepository(lambda: session)  # type: ignore[arg-type]
    asyncio.run(repository.create_nonce(nonce="abcdefgh", user_id=uuid.uuid4(), created_at=now))
    assert "pg_advisory_xact_lock" in statements[0]
    assert statements[-2:] == ["count", "insert"]


async def _exercise_postgres(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    try:
        user = User(email=f"{uuid.uuid4()}@example.com")
        org = Organization(name="Acme")
        async with sessions() as session, session.begin():
            session.add_all([user, org])
            await session.flush()
            session.add(
                Membership(org_id=org.id, user_id=user.id, roles=["Approver"], status="suspended")
            )
            session.add(
                WalletLink(
                    user_id=user.id,
                    address=bytes.fromhex("55" * 20),
                    chain_family="evm",
                    is_contract=False,
                    linked_at=datetime.now(UTC),
                )
            )
        profile = await SqlAlchemyAuthRepository(sessions).get_profile(user.id)
        assert profile is not None
        assert [item.signer_roles_active for item in profile.memberships] == [False]

        # Concurrent challenge requests cannot exceed the open-nonce cap.
        repository = WalletRepository(sessions)
        results = await asyncio.gather(
            *(
                repository.create_nonce(
                    nonce=f"nonce{index:04d}", user_id=user.id, created_at=datetime.now(UTC)
                )
                for index in range(MAX_OPEN_SIWE_NONCES * 3)
            ),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, Exception) for item in results) == MAX_OPEN_SIWE_NONCES
        assert all(isinstance(item, AuthFailure) for item in results if isinstance(item, Exception))
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL wallet integration test",
)
def test_postgres_suspended_signer_and_concurrent_nonce_cap() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise_postgres(database_url))
    finally:
        command.downgrade(config, "base")
