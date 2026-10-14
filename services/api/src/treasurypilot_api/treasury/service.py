"""Treasury creation and lookup (FR-101..103, M02-D2, M02-D6)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from eth_utils import to_checksum_address
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.models import AuditActorType
from treasurypilot_api.audit.writer import AuditActor, AuditEntity
from treasurypilot_api.audit.writer import write as write_audit
from treasurypilot_api.common.repository import OrgScopedRepository
from treasurypilot_api.treasury.config import PlatformConfiguration
from treasurypilot_api.treasury.models import (
    Coverage,
    Treasury,
    TreasuryStatus,
    TreasuryWallet,
    WalletRole,
)
from treasurypilot_api.treasury.safe import SafeInfo, SafeVerificationError, SafeVerifier
from treasurypilot_api.treasury.sync import asset_id as configured_asset_id

MAX_OPERATIONAL_WALLETS = 2
OWNER_SETS_DIFFER = "OWNER_SETS_DIFFER"


class TreasuryRequestError(Exception):
    """A treasury request that fails validation; ``code`` is the API error code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


class TreasuryNotFound(Exception):
    """The treasury does not exist in this organization."""


@dataclass(frozen=True, slots=True)
class WalletInput:
    role: WalletRole
    safe_address: str  # 0x + 40 hex, any case
    label: str | None = None


@dataclass(frozen=True, slots=True)
class WalletRecord:
    id: uuid.UUID
    role: WalletRole
    label: str
    safe_address: str  # EIP-55
    owners: tuple[str, ...]
    threshold: int


@dataclass(frozen=True, slots=True)
class TreasuryWarning:
    code: str
    message: str
    wallets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TreasuryRecord:
    id: uuid.UUID
    org_id: uuid.UUID
    chain_id: int
    asset_id: uuid.UUID
    status: TreasuryStatus
    coverage: Coverage
    module_address: str | None
    created_at: datetime
    wallets: tuple[WalletRecord, ...]
    warnings: tuple[TreasuryWarning, ...]


class _TreasuryRepository(OrgScopedRepository[Treasury]):
    model = Treasury


class _WalletRepository(OrgScopedRepository[TreasuryWallet]):
    model = TreasuryWallet


def _checksum(raw: bytes) -> str:
    return str(to_checksum_address("0x" + raw.hex()))


def owner_set_warnings(wallets: Sequence[WalletRecord]) -> tuple[TreasuryWarning, ...]:
    """Differing owner sets or thresholds across T/O1/O2 warn but never block (M02-D6)."""

    if len(wallets) < 2:
        return ()
    reference = wallets[0]
    reference_key = ({o.lower() for o in reference.owners}, reference.threshold)
    differing = tuple(
        wallet.label
        for wallet in wallets[1:]
        if ({o.lower() for o in wallet.owners}, wallet.threshold) != reference_key
    )
    if not differing:
        return ()
    return (
        TreasuryWarning(
            code=OWNER_SETS_DIFFER,
            message=(
                "Owner sets or thresholds differ between the Safes; the module is enabled "
                "on each Safe by its own owners, so expect separate signing sessions."
            ),
            wallets=(reference.label, *differing),
        ),
    )


def _record(treasury: Treasury, wallets: Sequence[TreasuryWallet]) -> TreasuryRecord:
    ordered = sorted(wallets, key=lambda w: (w.role != WalletRole.SOURCE, w.label))
    records = tuple(
        WalletRecord(
            id=wallet.id,
            role=wallet.role,
            label=wallet.label,
            safe_address=_checksum(wallet.safe_address),
            owners=tuple(wallet.owners),
            threshold=wallet.threshold,
        )
        for wallet in ordered
    )
    return TreasuryRecord(
        id=treasury.id,
        org_id=treasury.org_id,
        chain_id=treasury.chain_id,
        asset_id=treasury.asset_id,
        status=treasury.status,
        coverage=treasury.coverage,
        module_address=(
            _checksum(treasury.module_address) if treasury.module_address is not None else None
        ),
        created_at=treasury.created_at,
        wallets=records,
        warnings=owner_set_warnings(records),
    )


def _default_label(role: WalletRole, index: int) -> str:
    prefix = "T" if role == WalletRole.SOURCE else "O"
    return "T" if role == WalletRole.SOURCE and index == 1 else f"{prefix}{index}"


class TreasuryService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        verifier: SafeVerifier,
        configuration: PlatformConfiguration,
    ) -> None:
        self._sessions = sessions
        self._verifier = verifier
        self._configuration = configuration

    def _validate(
        self, chain_id: int, asset: uuid.UUID, wallets: Sequence[WalletInput]
    ) -> list[tuple[WalletInput, str, str]]:
        chain = next(
            (c for c in self._configuration.chains if c.chain_id == chain_id and c.enabled), None
        )
        if chain is None:
            raise TreasuryRequestError("WRONG_CHAIN", f"Chain {chain_id} is not supported.")
        if not any(configured_asset_id(chain_id, a.address) == asset for a in chain.assets):
            raise TreasuryRequestError(
                "UNSUPPORTED_ASSET", "The asset is not registered on this chain."
            )
        sources = [w for w in wallets if w.role == WalletRole.SOURCE]
        operational = [w for w in wallets if w.role == WalletRole.OPERATIONAL]
        if len(sources) != 1 or not 1 <= len(operational) <= MAX_OPERATIONAL_WALLETS:
            raise TreasuryRequestError(
                "INVALID_WALLET_SET",
                "A treasury needs exactly one SOURCE Safe and one or two OPERATIONAL Safes.",
            )
        normalized: list[tuple[WalletInput, str, str]] = []
        seen: set[str] = set()
        labels: set[str] = set()
        counters = {WalletRole.SOURCE: 0, WalletRole.OPERATIONAL: 0}
        explicit = {(w.label or "").strip().casefold() for w in wallets} - {""}
        for wallet in [*sources, *operational]:
            address = "0x" + wallet.safe_address.removeprefix("0x").lower()
            if address in seen:
                raise TreasuryRequestError(
                    "DUPLICATE_WALLET", f"{wallet.safe_address} is listed more than once."
                )
            seen.add(address)
            counters[wallet.role] += 1
            label = (wallet.label or "").strip()
            index = counters[wallet.role]
            while not label:
                # A generated default must not collide with a label the user supplied.
                candidate = _default_label(wallet.role, index)
                if candidate.casefold() in explicit or candidate.casefold() in labels:
                    index += 1
                else:
                    label = candidate
            if label.casefold() in labels:
                raise TreasuryRequestError("INVALID_WALLET_SET", f"Label {label!r} is repeated.")
            labels.add(label.casefold())
            normalized.append((wallet, address, label))
        return normalized

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        chain_id: int,
        asset: uuid.UUID,
        wallets: Sequence[WalletInput],
    ) -> TreasuryRecord:
        normalized = self._validate(chain_id, asset, wallets)
        addresses = [address for _, address, _ in normalized]
        await self._reject_registered(chain_id, addresses)
        try:
            verified: list[SafeInfo] = await self._verifier.verify(chain_id, addresses)
        except SafeVerificationError as exc:
            raise TreasuryRequestError(exc.code, exc.detail) from None

        treasury = Treasury(
            id=uuid.uuid4(),
            org_id=organization_id,
            chain_id=chain_id,
            asset_id=asset,
            status=TreasuryStatus.DRAFT,
            coverage=Coverage.UNKNOWN,
            created_by=user_id,
            updated_by=user_id,
        )
        rows = [
            TreasuryWallet(
                id=uuid.uuid4(),
                org_id=organization_id,
                treasury_id=treasury.id,
                chain_id=chain_id,
                role=wallet.role,
                label=label,
                safe_address=bytes.fromhex(address[2:]),
                owners=list(info.owners),
                threshold=info.threshold,
                created_by=user_id,
                updated_by=user_id,
            )
            for (wallet, address, label), info in zip(normalized, verified, strict=True)
        ]
        try:
            async with self._sessions() as session, session.begin():
                _TreasuryRepository(session, organization_id).add(treasury)
                await session.flush()
                for row in rows:
                    _WalletRepository(session, organization_id).add(row)
                await session.flush()
                record = _record(treasury, rows)
                await write_audit(
                    session,
                    org_id=organization_id,
                    actor=AuditActor(AuditActorType.USER, user_id),
                    action="treasury.created",
                    entity=AuditEntity("treasury", treasury.id),
                    data={
                        "chainId": chain_id,
                        "assetId": str(asset),
                        "status": treasury.status.value,
                        "wallets": [
                            {
                                "role": row.role.value,
                                "label": row.label,
                                "safeAddress": info.address,
                                "safeVersion": info.version,
                                "masterCopy": info.master_copy,
                                "threshold": info.threshold,
                                "ownerCount": len(info.owners),
                                "verifiedAtBlock": info.block_number,
                            }
                            for row, info in zip(rows, verified, strict=True)
                        ],
                        "warnings": [warning.code for warning in record.warnings],
                    },
                )
        except IntegrityError as exc:
            # A concurrent request registered the same Safe between the check and the insert.
            if "uq_treasury_wallets_chain_address" in str(exc.orig):
                raise TreasuryRequestError(
                    "DUPLICATE_WALLET", "A Safe is already registered to a treasury."
                ) from None
            raise
        return record

    async def get(self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID) -> TreasuryRecord:
        async with self._sessions() as session:
            treasury = await _TreasuryRepository(session, organization_id).get(treasury_id)
            if treasury is None:
                raise TreasuryNotFound
            wallets = list(
                await session.scalars(
                    _WalletRepository(session, organization_id)
                    .select()
                    .where(TreasuryWallet.treasury_id == treasury_id)
                )
            )
        return _record(treasury, wallets)

    async def _reject_registered(self, chain_id: int, addresses: Sequence[str]) -> None:
        # A Safe belongs to exactly one treasury across all tenants (unique chain+address),
        # so this check is intentionally not org-scoped; it reveals only that it is taken.
        async with self._sessions() as session:
            taken = await session.scalar(
                select(TreasuryWallet.id)
                .where(
                    TreasuryWallet.chain_id == chain_id,
                    TreasuryWallet.safe_address.in_([bytes.fromhex(a[2:]) for a in addresses]),
                )
                .limit(1)
            )
        if taken is not None:
            raise TreasuryRequestError(
                "DUPLICATE_WALLET", "A Safe is already registered to a treasury."
            )
