"""Treasury creation and lookup (FR-101..103, M02-D2, M02-D6)."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

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
    SafeConfigSnapshot,
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
    coverage_acknowledged: bool = False
    coverage_acknowledged_at: datetime | None = None
    coverage_acknowledged_by: uuid.UUID | None = None
    coverage_ack_reason: str | None = None
    coverage_details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TreasurySummaryRecord:
    id: uuid.UUID
    chain_id: int
    asset_id: uuid.UUID
    status: TreasuryStatus
    coverage: Coverage
    created_at: datetime


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
        coverage_acknowledged=treasury.coverage_ack_by is not None,
        coverage_acknowledged_at=treasury.coverage_ack_at,
        coverage_acknowledged_by=treasury.coverage_ack_by,
        coverage_ack_reason=treasury.coverage_ack_reason,
        coverage_details=tuple(treasury.coverage_details or ()),
    )


def _default_label(role: WalletRole, index: int) -> str:
    prefix = "T" if role == WalletRole.SOURCE else "O"
    return "T" if role == WalletRole.SOURCE and index == 1 else f"{prefix}{index}"


class TreasuryService:
    SNAPSHOT_MAX_AGE = timedelta(minutes=12)

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
            latest = await _latest_snapshots(session, organization_id, wallets)
        record = _record(treasury, wallets)
        # Fail closed on read: a stopped worker must not leave a stored COMPLETE usable forever.
        if record.coverage != Coverage.UNKNOWN and (
            not wallets
            or any(
                wallet.id not in latest
                or datetime.now(UTC) - latest[wallet.id].observed_at > self.SNAPSHOT_MAX_AGE
                for wallet in wallets
            )
        ):
            return replace(
                record,
                coverage=Coverage.UNKNOWN,
                coverage_acknowledged=False,
                coverage_details=("Coverage is UNKNOWN: no recent Safe configuration snapshot.",),
            )
        return record

    async def list_for_org(
        self, *, organization_id: uuid.UUID
    ) -> tuple[TreasurySummaryRecord, ...]:
        """List this organization's treasuries without combining their balances or counters."""

        async with self._sessions() as session:
            rows = await session.scalars(
                _TreasuryRepository(session, organization_id)
                .select()
                .order_by(Treasury.created_at, Treasury.id)
            )
            return tuple(
                TreasurySummaryRecord(
                    id=row.id,
                    chain_id=row.chain_id,
                    asset_id=row.asset_id,
                    status=row.status,
                    coverage=row.coverage,
                    created_at=row.created_at,
                )
                for row in rows
            )

    async def refresh_coverage(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> TreasuryRecord:
        """Recompute coverage from recent block-pinned Safe snapshots; missing data fails closed."""

        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            treasury = await _locked_treasury(session, organization_id, treasury_id)
            if treasury is None:
                raise TreasuryNotFound
            wallets = list(
                await session.scalars(
                    _WalletRepository(session, organization_id)
                    .select()
                    .where(TreasuryWallet.treasury_id == treasury_id)
                )
            )
            module_implementation = _deployment_address(
                self._configuration, treasury.chain_id, "TREASURY_MODULE_IMPLEMENTATION"
            )
            fallback_handler = _deployment_address(
                self._configuration, treasury.chain_id, "SAFE_FALLBACK_HANDLER"
            )
            latest = await _latest_snapshots(session, organization_id, wallets)

            coverage, details = evaluate_coverage(
                wallets,
                latest,
                now=now,
                module_address=treasury.module_address,
                module_implementation=module_implementation,
                fallback_handler=fallback_handler,
                max_snapshot_age=self.SNAPSHOT_MAX_AGE,
            )
            # An acknowledgment covers exactly the deviations the Owner reviewed.
            if coverage != Coverage.PARTIAL or list(details) != list(treasury.coverage_details):
                treasury.coverage_ack_by = None
                treasury.coverage_ack_at = None
                treasury.coverage_ack_reason = None
            treasury.coverage = coverage
            treasury.coverage_details = list(details)
            await session.flush()
            record = _record(treasury, wallets)
            return replace(record, coverage_details=tuple(details))

    async def acknowledge_coverage(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: str,
    ) -> TreasuryRecord:
        clean_reason = reason.strip()
        if not clean_reason:
            raise TreasuryRequestError(
                "INVALID_REASON", "Provide a reason for accepting partial coverage."
            )
        async with self._sessions() as session, session.begin():
            treasury = await _locked_treasury(session, organization_id, treasury_id)
            if treasury is None:
                raise TreasuryNotFound
            if treasury.coverage == Coverage.COMPLETE:
                raise TreasuryRequestError(
                    "COVERAGE_COMPLETE", "Complete coverage does not need acknowledgment."
                )
            if treasury.coverage == Coverage.UNKNOWN:
                raise TreasuryRequestError(
                    "COVERAGE_UNKNOWN",
                    "Coverage must be refreshed successfully before acknowledgment.",
                )
            treasury.coverage_ack_by = user_id
            treasury.coverage_ack_at = datetime.now(UTC)
            treasury.coverage_ack_reason = clean_reason
            await session.flush()
            await write_audit(
                session,
                org_id=organization_id,
                actor=AuditActor(AuditActorType.USER, user_id),
                action="treasury.coverage.acknowledged",
                entity=AuditEntity("treasury", treasury.id),
                data={"coverage": treasury.coverage.value, "reason": clean_reason},
            )
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


async def _locked_treasury(
    session: AsyncSession, organization_id: uuid.UUID, treasury_id: uuid.UUID
) -> Treasury | None:
    """Row-lock the treasury so API writes serialize with the worker's coverage UPDATE."""

    row: Treasury | None = await session.scalar(
        _TreasuryRepository(session, organization_id)
        .select()
        .where(Treasury.id == treasury_id)
        .with_for_update()
    )
    return row


async def _latest_snapshots(
    session: AsyncSession, organization_id: uuid.UUID, wallets: Sequence[TreasuryWallet]
) -> dict[uuid.UUID, SafeConfigSnapshot]:
    snapshots = await session.scalars(
        select(SafeConfigSnapshot)
        .where(
            SafeConfigSnapshot.org_id == organization_id,
            SafeConfigSnapshot.wallet_id.in_([wallet.id for wallet in wallets]),
        )
        .order_by(SafeConfigSnapshot.block_number.desc(), SafeConfigSnapshot.observed_at.desc())
    )
    latest: dict[uuid.UUID, SafeConfigSnapshot] = {}
    for snapshot in snapshots:
        latest.setdefault(snapshot.wallet_id, snapshot)
    return latest


def _deployment_address(
    configuration: PlatformConfiguration, chain_id: int, name: str
) -> bytes | None:
    for manifest in configuration.manifests:
        if manifest.chain_id != chain_id:
            continue
        deployment = next((item for item in manifest.deployments if item.name == name), None)
        if deployment is not None:
            return bytes(deployment.address_bytes)
    return None


def evaluate_coverage(
    wallets: Sequence[TreasuryWallet],
    snapshots: Mapping[uuid.UUID, SafeConfigSnapshot],
    *,
    now: datetime,
    module_address: bytes | None,
    module_implementation: bytes | None,
    fallback_handler: bytes | None,
    max_snapshot_age: timedelta = timedelta(minutes=12),
) -> tuple[Coverage, tuple[str, ...]]:
    """Apply the deterministic coverage policy to one latest snapshot per registered Safe."""

    details: list[str] = []
    all_complete = module_address is not None
    any_unknown = not wallets or module_address is None
    if module_address is None:
        details.append("Coverage is UNKNOWN: the treasury module is not deployed yet.")
    if not wallets:
        details.append("Coverage is UNKNOWN: the treasury has no registered Safes.")
    if module_implementation is None or fallback_handler is None:
        any_unknown = True
        missing = (
            "TREASURY_MODULE_IMPLEMENTATION"
            if module_implementation is None
            else "SAFE_FALLBACK_HANDLER"
        )
        details.append(f"Coverage is UNKNOWN: {missing} is not configured for this chain.")
    for wallet in wallets:
        snapshot = snapshots.get(wallet.id)
        if snapshot is None or now - snapshot.observed_at > max_snapshot_age:
            any_unknown = True
            all_complete = False
            details.append(f"{wallet.label}: no recent Safe configuration snapshot.")
            continue
        module_key = "0x" + module_address.hex() if module_address else ""
        clone_target = snapshot.module_implementations.get(module_key)
        if module_address is None or snapshot.modules != [module_address]:
            all_complete = False
            details.append(f"{wallet.label}: enabled modules do not equal the treasury module.")
        elif (
            module_implementation is not None and clone_target != "0x" + module_implementation.hex()
        ):
            all_complete = False
            details.append(
                f"{wallet.label}: treasury module is not an EIP-1167 clone of the configured implementation."
            )
        if snapshot.guard is not None:
            all_complete = False
            details.append(f"{wallet.label}: an unexpected guard is enabled.")
        if fallback_handler is not None and snapshot.fallback_handler != fallback_handler:
            all_complete = False
            details.append(
                f"{wallet.label}: fallback handler is not the configured canonical handler."
            )

    if any_unknown:
        return Coverage.UNKNOWN, tuple(details)
    if all_complete:
        details.append("All registered Safes match the configured TreasuryPilot module policy.")
        return Coverage.COMPLETE, tuple(details)
    if not details:
        details.append("Safe configuration does not satisfy the coverage policy.")
    return Coverage.PARTIAL, tuple(details)


def coverage_allows_execution(coverage: Coverage, acknowledged: bool) -> bool:
    """Execution is allowed only for complete coverage or Owner-acknowledged partial coverage."""

    return coverage == Coverage.COMPLETE or (coverage == Coverage.PARTIAL and acknowledged)
