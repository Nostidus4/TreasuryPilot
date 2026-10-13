from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from siwe import SiweMessage
from web3 import Web3

from treasurypilot_api.identity import wallets as wallet_module
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.wallets import (
    SIWE_CHAIN_ID,
    SiweNonceRecord,
    WalletLinkRecord,
    WalletLinkService,
    WalletRepository,
)

ORIGIN = "https://app.example.test"


class MemoryWalletRepository(WalletRepository):
    def __init__(self) -> None:
        self.challenges: dict[str, SiweNonceRecord] = {}
        self.links: dict[bytes, uuid.UUID] = {}
        self.audit_actions: list[str] = []

    async def create_nonce(
        self, *, nonce: str, user_id: uuid.UUID, created_at: datetime
    ) -> SiweNonceRecord:
        challenge = SiweNonceRecord(nonce, user_id, created_at, created_at + timedelta(minutes=10))
        self.challenges[nonce] = challenge
        return challenge

    async def get_nonce(self, *, nonce: str, user_id: uuid.UUID) -> SiweNonceRecord | None:
        challenge = self.challenges.get(nonce)
        return challenge if challenge is not None and challenge.user_id == user_id else None

    async def owner_contexts(self, *, user_id: uuid.UUID) -> tuple[()]:
        return ()

    async def link_wallet(
        self,
        *,
        nonce: str,
        user_id: uuid.UUID,
        address: bytes,
        is_contract: bool,
        signature_hash: str,
        now: datetime,
        owner_statuses: dict[uuid.UUID, bool],
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

    def verify_eoa(
        rpc_url: str,
        message: SiweMessage,
        signature: str,
        domain: str,
        nonce: str,
        timestamp: datetime,
    ) -> bool:
        message.verify(signature, domain=domain, nonce=nonce, timestamp=timestamp)
        return False

    monkeypatch.setattr(wallet_module, "_verify_siwe_sync", verify_eoa)
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


def test_repository_keeps_last_signer_wallet_with_pending_items() -> None:
    now = datetime.now(UTC)
    wallet = SimpleNamespace(unlinked_at=None)
    membership = SimpleNamespace(org_id=uuid.uuid4(), roles=("Owner",))
    # Wallet lookup, active-wallet count, review_items table, pending-item check.
    session = FakeRepositorySession([wallet, 1, True, True], [membership])
    repository = WalletRepository(lambda: session)  # type: ignore[arg-type]

    with pytest.raises(AuthFailure) as pending:
        asyncio.run(
            repository.unlink_wallet(
                user_id=uuid.uuid4(),
                address=bytes.fromhex("11" * 20),
                now=now,
                owner_statuses={},
            )
        )
    assert pending.value.code == "SIGNER_ITEMS_PENDING"
    assert wallet.unlinked_at is None
