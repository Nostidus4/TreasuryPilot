from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from siwe import (  # type: ignore[import-untyped]
    InvalidSignature,
    SiweMessage,
    VerificationError,
    generate_nonce,
)
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from web3 import HTTPProvider, Web3

from treasurypilot_api.audit import AuditActor, AuditActorType, AuditEntity, write
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import (
    Membership,
    MembershipStatus,
    OrganizationRole,
    SiweNonce,
    WalletLink,
    uuid7,
)
from treasurypilot_api.treasury.config import PlatformConfiguration, resolve_rpc_url
from treasurypilot_api.treasury.models import TreasuryWallet, WalletRole

SIWE_CHAIN_ID = 11155111
SIWE_NONCE_LIFETIME = timedelta(minutes=10)
SIWE_CLOCK_SKEW = timedelta(minutes=2)
OWNER_CHECK_INTERVAL = timedelta(hours=1)
# After an RPC outage, /me skips the owner refresh for this long instead of making every
# request wait on dead endpoints (per process; the stored status is kept meanwhile).
OWNER_REFRESH_BACKOFF_SECONDS = 60.0
MAX_SIWE_MESSAGE_LENGTH = 4096
MAX_SIWE_SIGNATURE_LENGTH = 4096
# Outstanding (unused, unexpired) challenges per user; more is a nonce flood.
MAX_OPEN_SIWE_NONCES = 5
_SIGNATURE = re.compile(r"^0x(?:[0-9a-fA-F]{2})+$")

logger = logging.getLogger(__name__)

# time.monotonic() before which /me does not retry the owner refresh.
_owner_refresh_blocked_until = 0.0

_SAFE_OWNERS_ABI = [
    {
        "inputs": [],
        "name": "getOwners",
        "outputs": [{"internalType": "address[]", "name": "", "type": "address[]"}],
        "stateMutability": "view",
        "type": "function",
    }
]


@dataclass(frozen=True, slots=True)
class SiweNonceRecord:
    nonce: str
    user_id: uuid.UUID
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class OwnerContext:
    org_id: uuid.UUID
    wallet_addresses: tuple[bytes, ...]
    safe_addresses: tuple[bytes, ...]
    owner_is_onchain: bool
    owner_checked_at: datetime | None


@dataclass(frozen=True, slots=True)
class WalletLinkRecord:
    address: bytes
    is_contract: bool
    linked_at: datetime


class WalletRepository:
    """PostgreSQL persistence for SIWE challenges, wallet links, and owner checks."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create_nonce(
        self, *, nonce: str, user_id: uuid.UUID, created_at: datetime
    ) -> SiweNonceRecord:
        expires_at = created_at + SIWE_NONCE_LIFETIME
        async with self._sessions() as session, session.begin():
            # Serialize per user so concurrent requests cannot all pass the cap check.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"siwe-nonce:{user_id}"},
            )
            # Retention cleanup is centralized in the policy-aware compliance worker,
            # which honors the global legal hold and writes a hash-only receipt. Count
            # only open challenges here so historical rows do not block new requests.
            open_nonces = await session.scalar(
                select(func.count())
                .select_from(SiweNonce)
                .where(
                    SiweNonce.user_id == user_id,
                    SiweNonce.used_at.is_(None),
                    SiweNonce.expires_at >= created_at - SIWE_CLOCK_SKEW,
                )
            )
            if int(open_nonces or 0) >= MAX_OPEN_SIWE_NONCES:
                raise AuthFailure(
                    status=429,
                    code="RATE_LIMITED",
                    title="Too many requests",
                    detail="Too many open wallet challenges. Please wait and try again.",
                )
            session.add(
                SiweNonce(
                    nonce=nonce,
                    user_id=user_id,
                    created_at=created_at,
                    expires_at=expires_at,
                )
            )
        return SiweNonceRecord(nonce, user_id, created_at, expires_at)

    async def get_nonce(self, *, nonce: str, user_id: uuid.UUID) -> SiweNonceRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(SiweNonce).where(SiweNonce.nonce == nonce, SiweNonce.user_id == user_id)
            )
            if row is None or row.used_at is not None:
                return None
            return SiweNonceRecord(row.nonce, row.user_id, row.created_at, row.expires_at)

    async def owner_contexts(self, *, user_id: uuid.UUID) -> tuple[OwnerContext, ...]:
        async with self._sessions() as session:
            memberships = [
                membership
                for membership in await self._active_memberships(session, user_id, lock=False)
                if OrganizationRole.OWNER.value in membership.roles
            ]
            if not memberships:
                return ()
            wallets = (
                await session.scalars(
                    select(WalletLink.address).where(
                        WalletLink.user_id == user_id,
                        WalletLink.unlinked_at.is_(None),
                    )
                )
            ).all()
            safes: dict[uuid.UUID, list[bytes]] = {}
            for org_id, safe_address in await session.execute(
                select(TreasuryWallet.org_id, TreasuryWallet.safe_address).where(
                    TreasuryWallet.org_id.in_([item.org_id for item in memberships]),
                    TreasuryWallet.chain_id == SIWE_CHAIN_ID,
                    TreasuryWallet.role == WalletRole.SOURCE,
                )
            ):
                safes.setdefault(org_id, []).append(safe_address)
            return tuple(
                OwnerContext(
                    org_id=membership.org_id,
                    wallet_addresses=tuple(wallets),
                    safe_addresses=tuple(safes.get(membership.org_id, ())),
                    owner_is_onchain=membership.owner_is_onchain,
                    owner_checked_at=membership.owner_checked_at,
                )
                for membership in memberships
            )

    async def membership_roles(
        self, *, org_id: uuid.UUID, user_id: uuid.UUID
    ) -> frozenset[str] | None:
        async with self._sessions() as session:
            roles = await session.scalar(
                select(Membership.roles).where(
                    Membership.org_id == org_id,
                    Membership.user_id == user_id,
                    Membership.status == MembershipStatus.ACTIVE,
                )
            )
            return frozenset(roles) if roles is not None else None

    async def update_owner_statuses(
        self,
        *,
        user_id: uuid.UUID,
        statuses: Mapping[uuid.UUID, bool],
        checked_at: datetime,
        started_at: datetime,
    ) -> None:
        """Store refreshed statuses unless a link/unlink wrote a newer one meanwhile.

        ``started_at`` is when the slow on-chain read began; a membership already checked
        after that holds fresher data than this result.
        """

        async with self._sessions() as session, session.begin():
            memberships = await self._active_memberships(session, user_id)
            self._apply_owner_statuses(
                memberships, statuses=statuses, checked_at=checked_at, started_at=started_at
            )
            await session.flush()

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
        try:
            async with self._sessions() as session, session.begin():
                challenge = await session.scalar(
                    select(SiweNonce)
                    .where(SiweNonce.nonce == nonce, SiweNonce.user_id == user_id)
                    .with_for_update()
                )
                if (
                    challenge is None
                    or challenge.used_at is not None
                    or now > challenge.expires_at + SIWE_CLOCK_SKEW
                ):
                    raise _failure(
                        400,
                        "SIWE_NONCE_INVALID",
                        "Invalid SIWE nonce",
                        "The SIWE nonce is invalid, expired, or already used.",
                    )

                # Same lock order as unlink (memberships, then wallet rows).
                memberships = await self._active_memberships(session, user_id)
                existing = await session.scalar(
                    select(WalletLink)
                    .where(
                        WalletLink.address == address,
                        WalletLink.unlinked_at.is_(None),
                    )
                    .with_for_update()
                )
                if existing is not None and existing.user_id != user_id:
                    raise _failure(
                        409,
                        "ADDRESS_LINKED_ELSEWHERE",
                        "Wallet already linked",
                        "This address is linked to another user.",
                    )
                if existing is not None:
                    raise _failure(
                        409,
                        "WALLET_ALREADY_LINKED",
                        "Wallet already linked",
                        "This address is already linked to your account.",
                    )

                unlinked = await session.scalar(
                    select(WalletLink)
                    .where(
                        WalletLink.address == address,
                        WalletLink.user_id == user_id,
                        WalletLink.unlinked_at.is_not(None),
                    )
                    .with_for_update()
                )
                if unlinked is None:
                    wallet = WalletLink(
                        id=uuid7(),
                        user_id=user_id,
                        address=address,
                        chain_family="evm",
                        is_contract=is_contract,
                        linked_at=now,
                    )
                    session.add(wallet)
                else:
                    unlinked.unlinked_at = None
                    unlinked.linked_at = now
                    unlinked.is_contract = is_contract
                    wallet = unlinked

                challenge.used_at = now
                await self._write_audit(
                    session,
                    memberships,
                    user_id=user_id,
                    action="wallet.linked",
                    address=address,
                    data={
                        "chain_id": SIWE_CHAIN_ID,
                        "is_contract": is_contract,
                        "signature_sha256": signature_hash,
                    },
                )
                self._apply_owner_statuses(memberships, statuses=owner_statuses, checked_at=now)
                await session.flush()
                return WalletLinkRecord(wallet.address, wallet.is_contract, wallet.linked_at)
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint == "uq_wallet_links_active_address":
                # A concurrent link won; report it from the winning row's point of view.
                async with self._sessions() as session:
                    winner = await session.scalar(
                        select(WalletLink.user_id).where(
                            WalletLink.address == address, WalletLink.unlinked_at.is_(None)
                        )
                    )
                if winner == user_id:
                    raise _failure(
                        409,
                        "WALLET_ALREADY_LINKED",
                        "Wallet already linked",
                        "This address is already linked to your account.",
                    ) from None
                raise _failure(
                    409,
                    "ADDRESS_LINKED_ELSEWHERE",
                    "Wallet already linked",
                    "This address is linked to another user.",
                ) from None
            raise

    async def has_active_wallet(self, *, user_id: uuid.UUID, address: bytes) -> bool:
        async with self._sessions() as session:
            return (
                await session.scalar(
                    select(WalletLink.id).where(
                        WalletLink.user_id == user_id,
                        WalletLink.address == address,
                        WalletLink.unlinked_at.is_(None),
                    )
                )
                is not None
            )

    async def unlink_wallet(
        self,
        *,
        user_id: uuid.UUID,
        address: bytes,
        now: datetime,
        owner_statuses: Mapping[uuid.UUID, bool],
    ) -> None:
        async with self._sessions() as session, session.begin():
            memberships = await self._active_memberships(session, user_id)
            wallet = await session.scalar(
                select(WalletLink)
                .where(
                    WalletLink.user_id == user_id,
                    WalletLink.address == address,
                    WalletLink.unlinked_at.is_(None),
                )
                .with_for_update()
            )
            if wallet is None:
                raise _failure(
                    404,
                    "WALLET_NOT_FOUND",
                    "Wallet not found",
                    "No linked wallet has this address.",
                )
            wallet.unlinked_at = now
            await self._write_audit(
                session,
                memberships,
                user_id=user_id,
                action="wallet.unlinked",
                address=address,
                data={"chain_id": SIWE_CHAIN_ID},
            )
            self._apply_owner_statuses(memberships, statuses=owner_statuses, checked_at=now)
            await session.flush()

    @staticmethod
    async def _active_memberships(
        session: AsyncSession, user_id: uuid.UUID, *, lock: bool = True
    ) -> Sequence[Membership]:
        query = (
            select(Membership)
            .where(Membership.user_id == user_id, Membership.status == MembershipStatus.ACTIVE)
            .order_by(Membership.org_id)
        )
        if lock:
            query = query.with_for_update()
        return (await session.scalars(query)).all()

    @staticmethod
    async def _write_audit(
        session: AsyncSession,
        memberships: Sequence[Membership],
        *,
        user_id: uuid.UUID,
        action: str,
        address: bytes,
        data: dict[str, object],
    ) -> None:
        for membership in memberships:
            await write(
                session,
                org_id=membership.org_id,
                actor=AuditActor(AuditActorType.USER, user_id),
                action=action,
                entity=AuditEntity("wallet", "0x" + address.hex()),
                data=data,
            )

    @staticmethod
    def _apply_owner_statuses(
        memberships: Sequence[Membership],
        *,
        statuses: Mapping[uuid.UUID, bool],
        checked_at: datetime,
        started_at: datetime | None = None,
    ) -> None:
        for membership in memberships:
            if OrganizationRole.OWNER.value not in membership.roles:
                # A flag left over from a removed Owner role must not survive a re-grant.
                membership.owner_is_onchain = False
            elif membership.org_id in statuses:
                if (
                    started_at is not None
                    and membership.owner_checked_at is not None
                    and membership.owner_checked_at > started_at
                ):
                    continue
                membership.owner_is_onchain = statuses[membership.org_id]
                membership.owner_checked_at = checked_at


class WalletLinkService:
    """SIWE verification, ERC-1271 checks, and hourly Safe-owner freshness."""

    def __init__(
        self,
        repository: WalletRepository,
        *,
        allowed_origins: Sequence[str],
        platform_configuration: PlatformConfiguration | None,
    ) -> None:
        self._repository = repository
        self._allowed_origins = tuple(
            normalized
            for origin in allowed_origins
            if (normalized := _normalized_origin(origin)) is not None
        )
        self._platform_configuration = platform_configuration

    def origin_details(self, origin: str | None) -> tuple[str, str]:
        if origin is None:
            if len(self._allowed_origins) != 1:
                raise _failure(
                    400,
                    "SIWE_ORIGIN_INVALID",
                    "Invalid wallet origin",
                    "A configured application origin is required.",
                )
            origin = self._allowed_origins[0]
        normalized = _normalized_origin(origin)
        if normalized is None or normalized not in self._allowed_origins:
            raise _failure(
                403,
                "SIWE_ORIGIN_INVALID",
                "Invalid wallet origin",
                "The request origin is not an allowed application origin.",
            )
        parsed = urlsplit(normalized)
        return parsed.scheme, parsed.netloc

    async def issue_nonce(self, *, user_id: uuid.UUID, origin: str | None) -> SiweNonceRecord:
        self.origin_details(origin)
        now = datetime.now(UTC)
        return await self._repository.create_nonce(
            nonce=generate_nonce(), user_id=user_id, created_at=now
        )

    async def link_wallet(
        self,
        *,
        user_id: uuid.UUID,
        origin: str | None,
        message_text: str,
        signature: str,
    ) -> WalletLinkRecord:
        if (
            len(message_text) > MAX_SIWE_MESSAGE_LENGTH
            or len(signature) > MAX_SIWE_SIGNATURE_LENGTH
            # siwe lets a malformed hex signature escape as ValueError from its ERC-1271
            # path, which would look like an RPC failure (503) instead of a bad signature.
            or not _SIGNATURE.fullmatch(signature)
        ):
            raise _invalid_siwe()
        scheme, domain = self.origin_details(origin)
        try:
            message = SiweMessage.from_message(message=message_text)
        except Exception:
            raise _invalid_siwe() from None

        if (
            message.domain.casefold() != domain.casefold()
            or (message.scheme or "https").casefold() != scheme.casefold()
            or message.chain_id != SIWE_CHAIN_ID
            or message.statement != "Link this wallet to TreasuryPilot"
            or not _same_origin(message.uri, scheme, domain)
        ):
            raise _invalid_siwe()
        challenge = await self._repository.get_nonce(nonce=message.nonce, user_id=user_id)
        now = datetime.now(UTC)
        if challenge is None or now > challenge.expires_at + SIWE_CLOCK_SKEW:
            raise _invalid_siwe()

        issued_at = message.issued_at._datetime
        if (
            issued_at.tzinfo is None
            or issued_at.utcoffset() is None
            or issued_at < challenge.created_at - SIWE_CLOCK_SKEW
            or issued_at > now + SIWE_CLOCK_SKEW
        ):
            raise _invalid_siwe()
        if message.expiration_time is None:
            raise _invalid_siwe()
        expires_at = message.expiration_time._datetime
        if (
            expires_at.tzinfo is None
            or expires_at.utcoffset() is None
            or expires_at <= now - SIWE_CLOCK_SKEW
            or expires_at > challenge.expires_at + SIWE_CLOCK_SKEW
            or expires_at <= issued_at
        ):
            raise _invalid_siwe()
        not_before = message.not_before._datetime if message.not_before is not None else None
        if not_before is not None and (
            not_before.tzinfo is None
            or not_before.utcoffset() is None
            or not_before > now + SIWE_CLOCK_SKEW
        ):
            raise _invalid_siwe()

        verification_time = _verification_time(now, not_before, expires_at)
        is_contract = await self._verify_signature(
            message=message,
            signature=signature,
            domain=domain,
            nonce=challenge.nonce,
            timestamp=verification_time,
        )
        address = bytes.fromhex(message.address.removeprefix("0x"))
        contexts = await self._repository.owner_contexts(user_id=user_id)
        # Linking can only add ownership, so an RPC outage must not block it: orgs left
        # out here keep their stored status and are rechecked by the next /me.
        owner_statuses = await self._owner_statuses(
            contexts, added_address=address, tolerate_unavailable=True
        )
        return await self._repository.link_wallet(
            nonce=challenge.nonce,
            user_id=user_id,
            address=address,
            is_contract=is_contract,
            signature_hash=hashlib.sha256(signature.encode("utf-8")).hexdigest(),
            now=now,
            owner_statuses=owner_statuses,
        )

    async def unlink_wallet(self, *, user_id: uuid.UUID, address: str) -> None:
        try:
            checksum_address = Web3.to_checksum_address(address)
        except ValueError:
            raise _failure(
                422, "ADDRESS_INVALID", "Invalid wallet address", "The address is invalid."
            ) from None
        address_bytes = bytes.fromhex(checksum_address.removeprefix("0x"))
        # Unknown wallets are a 404 even when the RPC is down.
        if not await self._repository.has_active_wallet(user_id=user_id, address=address_bytes):
            raise _failure(
                404, "WALLET_NOT_FOUND", "Wallet not found", "No linked wallet has this address."
            )
        contexts = await self._repository.owner_contexts(user_id=user_id)
        # Unlinking must work during an RPC outage (e.g. a compromised wallet): an org whose
        # status cannot be recomputed fails closed to "not an on-chain owner".
        owner_statuses = await self._owner_statuses(
            contexts, removed_address=address_bytes, tolerate_unavailable=True
        )
        for context in contexts:
            owner_statuses.setdefault(context.org_id, False)
        await self._repository.unlink_wallet(
            user_id=user_id,
            address=address_bytes,
            now=datetime.now(UTC),
            owner_statuses=owner_statuses,
        )

    async def refresh_owner_statuses(self, *, user_id: uuid.UUID) -> None:
        """Best-effort hourly refresh for display (``/me``); never fails the caller."""

        global _owner_refresh_blocked_until
        if time.monotonic() < _owner_refresh_blocked_until:
            return
        try:
            await self._refresh_owner_statuses(user_id=user_id)
        except AuthFailure as failure:
            if failure.status != 503:
                raise
            _owner_refresh_blocked_until = time.monotonic() + OWNER_REFRESH_BACKOFF_SECONDS
            logger.warning("owner_status_refresh_unavailable")

    async def _refresh_owner_statuses(self, *, user_id: uuid.UUID) -> None:
        started_at = datetime.now(UTC)
        contexts = await self._repository.owner_contexts(user_id=user_id)
        stale = tuple(
            context
            for context in contexts
            if context.owner_checked_at is None
            or started_at - context.owner_checked_at >= OWNER_CHECK_INTERVAL
        )
        if not stale:
            return
        statuses = await self._owner_statuses(stale)
        await self._repository.update_owner_statuses(
            user_id=user_id,
            statuses=statuses,
            checked_at=datetime.now(UTC),
            started_at=started_at,
        )

    async def refresh_org_owner_status(
        self, *, org_id: uuid.UUID, user_id: uuid.UUID, fresh: bool = False
    ) -> bool | None:
        """Return the Owner's on-chain status; ``fresh`` skips the hourly cache."""

        started_at = datetime.now(UTC)
        contexts = await self._repository.owner_contexts(user_id=user_id)
        context = next((item for item in contexts if item.org_id == org_id), None)
        if context is None:
            return None
        if (
            fresh
            or context.owner_checked_at is None
            or started_at - context.owner_checked_at >= OWNER_CHECK_INTERVAL
        ):
            statuses = await self._owner_statuses((context,))
            await self._repository.update_owner_statuses(
                user_id=user_id,
                statuses=statuses,
                checked_at=datetime.now(UTC),
                started_at=started_at,
            )
            return statuses[org_id]
        return context.owner_is_onchain

    async def require_onchain_owner(self, *, org_id: uuid.UUID, user_id: uuid.UUID) -> bool | None:
        """Check on-chain now, before an Owner-only write (no hourly cache, M01-D5)."""

        status = await self.refresh_org_owner_status(org_id=org_id, user_id=user_id, fresh=True)
        if status is False:
            raise owner_not_onchain()
        return status

    async def membership_roles(
        self, *, org_id: uuid.UUID, user_id: uuid.UUID
    ) -> frozenset[str] | None:
        return await self._repository.membership_roles(org_id=org_id, user_id=user_id)

    def _rpc_urls(self) -> tuple[str, ...]:
        config = self._platform_configuration
        if config is None:
            raise _wallet_unavailable()
        chain = next(
            (item for item in config.chains if item.chain_id == SIWE_CHAIN_ID and item.enabled),
            None,
        )
        if chain is None:
            raise _wallet_unavailable()
        try:
            urls = tuple(resolve_rpc_url(url, os.environ) for url in chain.rpc_urls)
        except Exception:
            raise _wallet_unavailable() from None
        if not urls:
            # An enabled chain without endpoints is a configuration gap, not a bad request.
            raise _wallet_unavailable()
        return urls

    async def _verify_signature(
        self,
        *,
        message: SiweMessage,
        signature: str,
        domain: str,
        nonce: str,
        timestamp: datetime,
    ) -> bool:
        # An EOA signature is recovered offline, so normal wallets link during an RPC outage.
        try:
            await asyncio.to_thread(_verify_eoa_sync, message, signature, domain, nonce, timestamp)
            return False
        except InvalidSignature:
            pass  # possibly a contract wallet: ERC-1271 needs the RPC
        except VerificationError:
            raise _invalid_siwe() from None
        last_error: Exception | None = None
        for rpc_url in self._rpc_urls():
            try:
                return await asyncio.to_thread(
                    _verify_siwe_sync,
                    rpc_url,
                    message,
                    signature,
                    domain,
                    nonce,
                    timestamp,
                )
            except VerificationError:
                raise _invalid_siwe() from None
            except Exception as exc:
                last_error = exc
        assert last_error is not None  # _rpc_urls() never returns an empty tuple
        raise _wallet_unavailable() from None

    async def _owner_statuses(
        self,
        contexts: Sequence[OwnerContext],
        *,
        added_address: bytes | None = None,
        removed_address: bytes | None = None,
        tolerate_unavailable: bool = False,
    ) -> dict[uuid.UUID, bool]:
        """Recompute Safe-owner status; with ``tolerate_unavailable`` omit unreadable orgs."""

        statuses: dict[uuid.UUID, bool] = {}
        for context in contexts:
            addresses = set(context.wallet_addresses)
            if added_address is not None:
                addresses.add(added_address)
            if removed_address is not None:
                addresses.discard(removed_address)
            if not context.safe_addresses or not addresses:
                statuses[context.org_id] = False
                continue
            owners: set[str] = set()
            try:
                for safe_address in context.safe_addresses:
                    owners.update(await self._safe_owners(safe_address))
            except AuthFailure as failure:
                if not tolerate_unavailable or failure.status != 503:
                    raise
                continue
            statuses[context.org_id] = bool(
                addresses.intersection(bytes.fromhex(owner.removeprefix("0x")) for owner in owners)
            )
        return statuses

    async def _safe_owners(self, address: bytes) -> set[str]:
        for rpc_url in self._rpc_urls():
            try:
                return await asyncio.to_thread(_safe_owners_sync, rpc_url, address)
            except Exception:
                continue
        raise _wallet_unavailable()


def _verify_eoa_sync(
    message: SiweMessage, signature: str, domain: str, nonce: str, timestamp: datetime
) -> None:
    """Verify an EOA signature by local recovery; raises ``InvalidSignature`` otherwise."""

    message.verify(signature, domain=domain, nonce=nonce, timestamp=timestamp)


def _verify_siwe_sync(
    rpc_url: str,
    message: SiweMessage,
    signature: str,
    domain: str,
    nonce: str,
    timestamp: datetime,
) -> bool:
    provider = HTTPProvider(rpc_url, request_kwargs={"timeout": 5})
    web3 = Web3(provider)
    if web3.eth.chain_id != SIWE_CHAIN_ID:
        raise RuntimeError("configured RPC is on the wrong chain")
    is_contract = bool(web3.eth.get_code(Web3.to_checksum_address(message.address)))
    message.verify(
        signature=signature,
        domain=domain,
        nonce=nonce,
        timestamp=timestamp,
        provider=provider,
    )
    return is_contract


def _safe_owners_sync(rpc_url: str, address: bytes) -> set[str]:
    provider = HTTPProvider(rpc_url, request_kwargs={"timeout": 5})
    web3 = Web3(provider)
    if web3.eth.chain_id != SIWE_CHAIN_ID:
        raise RuntimeError("configured RPC is on the wrong chain")
    safe = web3.eth.contract(
        address=Web3.to_checksum_address("0x" + address.hex()), abi=_SAFE_OWNERS_ABI
    )
    owners = safe.functions.getOwners().call()
    return {Web3.to_checksum_address(owner).lower() for owner in owners}


def _normalized_origin(value: str) -> str | None:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    return f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}"


def _same_origin(uri: str, scheme: str, domain: str) -> bool:
    parsed = urlsplit(uri)
    return (
        parsed.scheme.casefold() == scheme.casefold()
        and parsed.netloc.casefold() == domain.casefold()
        and parsed.username is None
        and parsed.password is None
    )


def _verification_time(
    now: datetime, not_before: datetime | None, expires_at: datetime
) -> datetime:
    lower_bound = not_before + timedelta(microseconds=1) if not_before is not None else None
    upper_bound = expires_at - timedelta(microseconds=1)
    if lower_bound is not None and lower_bound >= upper_bound:
        raise _invalid_siwe()
    timestamp = max(now, lower_bound) if lower_bound is not None else now
    return min(timestamp, upper_bound)


def owner_not_onchain() -> AuthFailure:
    return AuthFailure(
        status=403,
        code="OWNER_NOT_ONCHAIN",
        title="On-chain owner required",
        detail="Your linked wallet is not an on-chain owner of Safe T.",
    )


def _invalid_siwe() -> AuthFailure:
    return _failure(
        400,
        "SIWE_INVALID",
        "Invalid wallet signature",
        "The SIWE message, nonce, or signature is invalid.",
    )


def _wallet_unavailable() -> AuthFailure:
    return _failure(
        503,
        "WALLET_VERIFICATION_UNAVAILABLE",
        "Wallet verification unavailable",
        "Wallet verification is temporarily unavailable. Please retry.",
    )


def _failure(status: int, code: str, title: str, detail: str) -> AuthFailure:
    return AuthFailure(status=status, code=code, title=title, detail=detail)
