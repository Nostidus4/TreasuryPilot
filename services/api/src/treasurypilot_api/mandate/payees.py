from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.events import AuditEvent, AuditWriter, log_audit_event
from treasurypilot_api.compliance.screening import (
    ScreeningRecord,
    ScreeningService,
    normalize_address,
)
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.identity.rbac import MemberAccess, require_member, require_role
from treasurypilot_api.mandate.governance import (
    GovernanceCall,
    build_add_payee_call,
    build_deactivate_payee_call,
)
from treasurypilot_api.mandate.governance_service import GovernanceFailure, GovernanceService
from treasurypilot_api.mandate.models import (
    GovernanceTxPurpose,
    OobMethod,
    Payee,
    PayeeStatus,
    Screening,
    ScreeningResult,
    Vendor,
)
from treasurypilot_api.treasury.models import Treasury, TreasuryWallet
from treasurypilot_api.treasury.safe import RpcUnavailable


class PayeeExists(Exception):
    """The address is already a live payee of the treasury."""


class NotAwaitingOwner(Exception):
    """The payee is not in the AwaitingOwner state."""


class OobAlreadyVerified(Exception):
    """Out-of-band verification is evidence and is recorded once."""


@dataclass(frozen=True, slots=True)
class ScreeningSummary:
    result: ScreeningResult
    source_ref: str | None
    provider: str
    checked_at: datetime
    ttl_until: datetime | None


@dataclass(frozen=True, slots=True)
class PayeeRecord:
    id: uuid.UUID
    treasury_id: uuid.UUID
    vendor_id: uuid.UUID
    label: str
    address: bytes
    status: str
    oob_method: str | None
    oob_note: str | None
    oob_verified_by: uuid.UUID | None
    oob_verified_at: datetime | None
    registration_tx_id: uuid.UUID | None
    active_from: datetime | None
    proposed_by: uuid.UUID | None
    created_at: datetime
    screening: ScreeningSummary | None = None


@dataclass(frozen=True, slots=True)
class PayeeContext:
    chain_id: int
    wallet_addresses: frozenset[bytes]
    module_address: bytes | None = None


class PayeeRepository(Protocol):
    async def get_context(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> PayeeContext | None: ...

    async def vendor_exists(self, *, organization_id: uuid.UUID, vendor_id: uuid.UUID) -> bool: ...

    async def propose(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        vendor_id: uuid.UUID,
        user_id: uuid.UUID,
        label: str,
        address: bytes,
    ) -> PayeeRecord:
        """Create the payee in ``Screening``; raise ``PayeeExists`` for a live duplicate."""
        ...

    async def finish_screening(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        payee_id: uuid.UUID,
        user_id: uuid.UUID,
        result: ScreeningResult,
        provider: str,
    ) -> PayeeRecord | None:
        """CLEAR moves a Screening payee to AwaitingOwner; HIT or ERROR to ScreeningFailed."""
        ...

    async def list_payees(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> tuple[PayeeRecord, ...] | None: ...

    async def get_payee(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID, payee_id: uuid.UUID
    ) -> PayeeRecord | None: ...

    async def register_with_tx(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        payee_id: uuid.UUID,
        create_tx: Callable[[], Awaitable[tuple[uuid.UUID, dict[str, object]]]],
    ) -> dict[str, object] | None: ...

    async def record_deactivation_requested(
        self,
        *,
        organization_id: uuid.UUID,
        payee_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: str,
        governance_tx_id: object,
    ) -> None: ...

    async def verify_oob(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        payee_id: uuid.UUID,
        user_id: uuid.UUID,
        method: OobMethod,
        note: str,
        at: datetime,
    ) -> PayeeRecord | None:
        """Raise ``NotAwaitingOwner`` or ``OobAlreadyVerified`` instead of overwriting."""
        ...


def _screening_summary(row: Screening | None) -> ScreeningSummary | None:
    if row is None:
        return None
    return ScreeningSummary(
        result=ScreeningResult(row.result),
        source_ref=row.source_ref,
        provider=row.provider,
        checked_at=row.checked_at,
        ttl_until=row.ttl_until,
    )


def _payee_record(row: Payee, screening: Screening | None = None) -> PayeeRecord:
    status = effective_payee_status(row.status.value, row.active_from, now=datetime.now(UTC))
    return PayeeRecord(
        id=row.id,
        treasury_id=row.treasury_id,
        vendor_id=row.vendor_id,
        label=row.label,
        address=row.address,
        status=status,
        oob_method=row.oob_method.value if row.oob_method else None,
        oob_note=row.oob_note,
        oob_verified_by=row.oob_verified_by,
        oob_verified_at=row.oob_verified_at,
        registration_tx_id=row.registration_tx_id,
        active_from=row.active_from,
        proposed_by=row.created_by,
        created_at=row.created_at,
        screening=_screening_summary(screening),
    )


def effective_payee_status(status: str, active_from: datetime | None, *, now: datetime) -> str:
    """Project the time-derived Cooling → Active transition without another chain event."""
    if status == PayeeStatus.COOLING.value and active_from is not None and active_from <= now:
        return PayeeStatus.ACTIVE.value
    return status


async def _latest_screening(session: AsyncSession, payee_id: uuid.UUID) -> Screening | None:
    return await session.scalar(
        select(Screening)
        .where(Screening.payee_id == payee_id)
        .order_by(Screening.checked_at.desc(), Screening.id.desc())
        .limit(1)
    )


class SqlAlchemyPayeeRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        audit_writer: AuditWriter = log_audit_event,
    ) -> None:
        self._sessions = sessions
        self._audit = audit_writer

    async def get_context(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> PayeeContext | None:
        async with self._sessions() as session:
            treasury = await session.execute(
                select(Treasury.chain_id, Treasury.module_address).where(
                    Treasury.id == treasury_id, Treasury.org_id == organization_id
                )
            )
            row = treasury.one_or_none()
            if row is None:
                return None
            wallets = await session.scalars(
                select(TreasuryWallet.safe_address).where(
                    TreasuryWallet.treasury_id == treasury_id,
                    TreasuryWallet.org_id == organization_id,
                )
            )
            return PayeeContext(
                chain_id=row.chain_id,
                wallet_addresses=frozenset(wallets),
                module_address=bytes(row.module_address)
                if row.module_address is not None
                else None,
            )

    async def vendor_exists(self, *, organization_id: uuid.UUID, vendor_id: uuid.UUID) -> bool:
        async with self._sessions() as session:
            found = await session.scalar(
                select(Vendor.id).where(Vendor.id == vendor_id, Vendor.org_id == organization_id)
            )
            return found is not None

    async def propose(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        vendor_id: uuid.UUID,
        user_id: uuid.UUID,
        label: str,
        address: bytes,
    ) -> PayeeRecord:
        try:
            async with self._sessions() as session, session.begin():
                live = await session.scalar(
                    select(Payee.id).where(
                        Payee.treasury_id == treasury_id,
                        Payee.address == address,
                        Payee.status.not_in(
                            (PayeeStatus.DEACTIVATED, PayeeStatus.SCREENING_FAILED)
                        ),
                    )
                )
                if live is not None:
                    raise PayeeExists
                row = Payee(
                    id=uuid7(),
                    treasury_id=treasury_id,
                    org_id=organization_id,
                    vendor_id=vendor_id,
                    label=label,
                    address=address,
                    status=PayeeStatus.SCREENING,
                    created_by=user_id,
                )
                session.add(row)
                await session.flush()
                await self._audit(
                    session,
                    AuditEvent(
                        org_id=organization_id,
                        actor_id=user_id,
                        action="payee.proposed",
                        entity_type="payee",
                        entity_id=row.id,
                        data={
                            "treasuryId": treasury_id,
                            "vendorId": vendor_id,
                            "address": address,
                        },
                    ),
                )
                return _payee_record(row)
        except IntegrityError as error:
            # Lost a race against the partial unique(treasury_id, address) index.
            raise PayeeExists from error

    async def finish_screening(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        payee_id: uuid.UUID,
        user_id: uuid.UUID,
        result: ScreeningResult,
        provider: str,
    ) -> PayeeRecord | None:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(Payee)
                .where(
                    Payee.id == payee_id,
                    Payee.treasury_id == treasury_id,
                    Payee.org_id == organization_id,
                )
                .with_for_update()
            )
            if row is None:
                return None
            if row.status == PayeeStatus.SCREENING:
                clear = result == ScreeningResult.CLEAR
                row.status = PayeeStatus.AWAITING_OWNER if clear else PayeeStatus.SCREENING_FAILED
                await session.flush()
                await self._audit(
                    session,
                    AuditEvent(
                        org_id=organization_id,
                        actor_id=user_id,
                        action="payee.screening_clear" if clear else "payee.screening_failed",
                        entity_type="payee",
                        entity_id=row.id,
                        data={"result": result, "provider": provider},
                    ),
                )
            return _payee_record(row, await _latest_screening(session, row.id))

    async def list_payees(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> tuple[PayeeRecord, ...] | None:
        async with self._sessions() as session:
            visible = await session.scalar(
                select(Treasury.id).where(
                    Treasury.id == treasury_id, Treasury.org_id == organization_id
                )
            )
            if visible is None:
                return None
            rows = await session.scalars(
                select(Payee).where(Payee.treasury_id == treasury_id).order_by(Payee.created_at)
            )
            return tuple(
                [_payee_record(row, await _latest_screening(session, row.id)) for row in rows]
            )

    async def get_payee(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID, payee_id: uuid.UUID
    ) -> PayeeRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(Payee).where(
                    Payee.id == payee_id,
                    Payee.treasury_id == treasury_id,
                    Payee.org_id == organization_id,
                )
            )
            if row is None:
                return None
            return _payee_record(row, await _latest_screening(session, row.id))

    async def register_with_tx(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        payee_id: uuid.UUID,
        create_tx: Callable[[], Awaitable[tuple[uuid.UUID, dict[str, object]]]],
    ) -> dict[str, object] | None:
        """Create the registration tx and link it while holding the payee row lock."""
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(Payee)
                .where(
                    Payee.id == payee_id,
                    Payee.treasury_id == treasury_id,
                    Payee.org_id == organization_id,
                )
                .with_for_update()
            )
            if (
                row is None
                or row.status != PayeeStatus.AWAITING_OWNER
                or row.registration_tx_id is not None
            ):
                return None
            tx_id, governance_tx = await create_tx()
            row.registration_tx_id = tx_id
            await session.flush()
            return governance_tx

    async def record_deactivation_requested(
        self,
        *,
        organization_id: uuid.UUID,
        payee_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: str,
        governance_tx_id: object,
    ) -> None:
        async with self._sessions() as session, session.begin():
            await self._audit(
                session,
                AuditEvent(
                    org_id=organization_id,
                    actor_id=user_id,
                    action="payee.deactivation_requested",
                    entity_type="payee",
                    entity_id=payee_id,
                    data={"reason": reason, "governanceTxId": str(governance_tx_id)},
                ),
            )

    async def verify_oob(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        payee_id: uuid.UUID,
        user_id: uuid.UUID,
        method: OobMethod,
        note: str,
        at: datetime,
    ) -> PayeeRecord | None:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(Payee)
                .where(
                    Payee.id == payee_id,
                    Payee.treasury_id == treasury_id,
                    Payee.org_id == organization_id,
                )
                .with_for_update()
            )
            if row is None:
                return None
            if row.status != PayeeStatus.AWAITING_OWNER:
                raise NotAwaitingOwner
            if row.oob_verified_at is not None:
                raise OobAlreadyVerified
            row.oob_verified_by = user_id
            row.oob_verified_at = at
            row.oob_method = method
            row.oob_note = note
            await session.flush()
            await self._audit(
                session,
                AuditEvent(
                    org_id=organization_id,
                    actor_id=user_id,
                    action="payee.oob_verified",
                    entity_type="payee",
                    entity_id=row.id,
                    data={"method": method, "note": note},
                ),
            )
            return _payee_record(row, await _latest_screening(session, row.id))


# ---------------------------------------------------------------- API models


class PayeeCreate(ApiModel):
    vendor_id: uuid.UUID
    label: str = Field(min_length=1, max_length=120)
    address: str = Field(max_length=100)

    @field_validator("label")
    @classmethod
    def label_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class OobVerification(ApiModel):
    method: OobMethod
    note: str = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def note_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class DeactivationRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class ReplacePayeeAddressRequest(DeactivationRequest):
    address: str


class ScreeningView(ApiModel):
    result: ScreeningResult
    source_ref: str | None
    provider: str
    checked_at: datetime
    ttl_until: datetime | None


class PayeeView(ApiModel):
    id: uuid.UUID
    treasury_id: uuid.UUID
    vendor_id: uuid.UUID
    label: str
    address: str
    status: PayeeStatus
    oob_method: str | None
    oob_note: str | None
    oob_verified_by: uuid.UUID | None
    oob_verified_at: datetime | None
    registration_tx_id: uuid.UUID | None
    active_from: datetime | None
    created_at: datetime
    screening: ScreeningView | None

    @classmethod
    def from_record(cls, row: PayeeRecord) -> PayeeView:
        screening = row.screening
        return cls(
            id=row.id,
            treasury_id=row.treasury_id,
            vendor_id=row.vendor_id,
            label=row.label,
            address=f"0x{row.address.hex()}",
            status=PayeeStatus(row.status),
            oob_method=row.oob_method,
            oob_note=row.oob_note,
            oob_verified_by=row.oob_verified_by,
            oob_verified_at=row.oob_verified_at,
            registration_tx_id=row.registration_tx_id,
            active_from=row.active_from,
            created_at=row.created_at,
            screening=ScreeningView(
                result=screening.result,
                source_ref=screening.source_ref,
                provider=screening.provider,
                checked_at=screening.checked_at,
                ttl_until=screening.ttl_until,
            )
            if screening is not None
            else None,
        )


class PayeeResponse(ApiModel):
    payee: PayeeView


class PayeeListResponse(ApiModel):
    items: list[PayeeView]


class PayeeTxResponse(ApiModel):
    governance_tx: dict[str, object]


class ReplacePayeeAddressResponse(ApiModel):
    payee: PayeeView
    deactivation_governance_tx: dict[str, object]


# ---------------------------------------------------------------- helpers


def _repository(request: Request) -> PayeeRepository:
    repository = getattr(request.app.state, "payee_repository", None)
    if repository is None:
        raise AuthFailure(
            status=503,
            code="PAYEE_UNAVAILABLE",
            title="Payee service unavailable",
            detail="Payee storage is not configured.",
        )
    return cast(PayeeRepository, repository)


def _screening(request: Request) -> ScreeningService:
    service = getattr(request.app.state, "screening_service", None)
    if service is None:
        # Fail closed (BR-085): without screening nothing can be proposed.
        raise AuthFailure(
            status=503,
            code="SCREENING_UNAVAILABLE",
            title="Screening unavailable",
            detail="Payees cannot be proposed because screening is not configured.",
        )
    return cast(ScreeningService, service)


def _not_found() -> AuthFailure:
    return AuthFailure(
        status=404,
        code="PAYEE_NOT_FOUND",
        title="Payee not found",
        detail="The treasury or payee is not available to this user.",
    )


def check_registration_gates(payee: PayeeRecord, *, now: datetime) -> AuthFailure | None:
    """Return the refusal for building a registration transaction, or ``None`` if allowed.

    These are deterministic backend rules (BR-013, BR-085); no model is involved.
    """

    screening = payee.screening
    if payee.status != PayeeStatus.AWAITING_OWNER or (
        screening is None or screening.result != ScreeningResult.CLEAR
    ):
        return AuthFailure(
            status=409,
            code="SCREENING_NOT_CLEAR",
            title="Screening is not clear",
            detail="Only a payee that passed screening and awaits the Owner can be registered.",
        )
    if screening.ttl_until is None or now >= screening.ttl_until:
        return AuthFailure(
            status=409,
            code="SCREENING_EXPIRED",
            title="Screening expired",
            detail="The screening result is stale; the payee must be screened again.",
        )
    if payee.oob_verified_at is None or payee.oob_verified_by is None:
        return AuthFailure(
            status=409,
            code="OOB_NOT_VERIFIED",
            title="Out-of-band verification missing",
            detail="Record the out-of-band verification before registering this payee.",
        )
    return None


def _governance_service(request: Request) -> GovernanceService:
    service = getattr(request.app.state, "governance_service", None)
    if service is None:
        raise AuthFailure(
            status=503,
            code="GOVERNANCE_UNAVAILABLE",
            title="Governance unavailable",
            detail="Governance transaction storage or chain verification is not configured.",
        )
    return cast(GovernanceService, service)


async def _build_payee_governance_tx(
    request: Request,
    *,
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    user_id: uuid.UUID,
    purpose: GovernanceTxPurpose,
    call: GovernanceCall,
    payee_id: uuid.UUID,
) -> dict[str, object]:
    try:
        return await _governance_service(request).create(
            organization_id=organization_id,
            treasury_id=treasury_id,
            user_id=user_id,
            purpose=purpose,
            calls=[call],
            entity_type="payee",
            entity_id=payee_id,
        )
    except GovernanceFailure as exc:
        raise AuthFailure(
            status=exc.status,
            code=exc.code,
            title="Governance transaction rejected",
            detail=exc.detail,
        ) from None
    except RpcUnavailable:
        raise AuthFailure(
            status=503,
            code="RPC_UNAVAILABLE",
            title="Chain RPC unavailable",
            detail="Safe state could not be read because no RPC provider answered.",
            retry_after=5,
        ) from None


router = APIRouter(
    prefix="/v1/orgs/{organization_id}/treasuries/{treasury_id}/payees", tags=["payees"]
)
_require_proposer = require_role(
    OrganizationRole.OPERATOR, OrganizationRole.ORG_ADMIN, OrganizationRole.OWNER
)
_require_owner = require_role(OrganizationRole.OWNER)


@router.get("", response_model=PayeeListResponse, openapi_extra={"x-organization-scoped": True})
async def list_payees(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> PayeeListResponse:
    rows = await _repository(request).list_payees(
        organization_id=member.organization_id, treasury_id=treasury_id
    )
    if rows is None:
        raise _not_found()
    return PayeeListResponse(items=[PayeeView.from_record(row) for row in rows])


@router.get(
    "/{payee_id}", response_model=PayeeResponse, openapi_extra={"x-organization-scoped": True}
)
async def get_payee(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payee_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> PayeeResponse:
    row = await _repository(request).get_payee(
        organization_id=member.organization_id, treasury_id=treasury_id, payee_id=payee_id
    )
    if row is None:
        raise _not_found()
    return PayeeResponse(payee=PayeeView.from_record(row))


@router.post(
    "",
    status_code=201,
    response_model=PayeeResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def propose_payee(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payload: PayeeCreate,
    request: Request,
    response: Response,
    member: MemberAccess = Depends(_require_proposer),  # noqa: B008
) -> PayeeResponse:
    repository = _repository(request)
    screening_service = _screening(request)
    context = await repository.get_context(
        organization_id=member.organization_id, treasury_id=treasury_id
    )
    if context is None:
        raise _not_found()
    try:
        address = normalize_address(payload.address)
    except ValueError:
        raise AuthFailure(
            status=422,
            code="ADDRESS_INVALID",
            title="Address invalid",
            detail="The payee address is not a valid EVM address.",
        ) from None
    if address in context.wallet_addresses:
        raise AuthFailure(
            status=422,
            code="ADDRESS_IS_TREASURY_WALLET",
            title="Address is a treasury wallet",
            detail="A treasury's own wallet cannot be registered as a payee.",
        )
    if not await repository.vendor_exists(
        organization_id=member.organization_id, vendor_id=payload.vendor_id
    ):
        raise AuthFailure(
            status=404,
            code="VENDOR_NOT_FOUND",
            title="Vendor not found",
            detail="The vendor does not exist in this organization.",
        )
    try:
        payee = await repository.propose(
            organization_id=member.organization_id,
            treasury_id=treasury_id,
            vendor_id=payload.vendor_id,
            user_id=member.user_id,
            label=payload.label,
            address=address,
        )
    except PayeeExists:
        raise AuthFailure(
            status=409,
            code="PAYEE_EXISTS",
            title="Payee already exists",
            detail="This address is already a payee of the treasury.",
        ) from None

    # The check ends in CLEAR, HIT or ERROR (provider failure, fail closed); never an exception.
    record: ScreeningRecord = await screening_service.screen(
        organization_id=member.organization_id,
        address=address,
        chain_id=context.chain_id,
        payee_id=payee.id,
    )
    updated = await repository.finish_screening(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
        payee_id=payee.id,
        user_id=member.user_id,
        result=record.result,
        provider=record.provider,
    )
    if updated is None:
        raise _not_found()
    if record.result == ScreeningResult.HIT:
        raise AuthFailure(
            status=422,
            code="SCREENING_HIT",
            title="Screening hit",
            detail="The address matched a sanctions screening list and is blocked.",
            extensions={"payeeId": str(payee.id), "status": updated.status},
        )
    if record.result != ScreeningResult.CLEAR:
        # ERROR: the provider is unavailable, so the payee stays ScreeningFailed (fail closed).
        raise AuthFailure(
            status=503,
            code="DATA_MISSING",
            title="Screening could not complete",
            detail="The screening provider did not answer; the payee is blocked (fail closed).",
            extensions={"payeeId": str(payee.id), "status": updated.status},
        )
    response.headers["Location"] = (
        f"/v1/orgs/{organization_id}/treasuries/{treasury_id}/payees/{payee.id}"
    )
    return PayeeResponse(payee=PayeeView.from_record(updated))


@router.post(
    "/{payee_id}/verify-oob",
    response_model=PayeeResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def verify_oob(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payee_id: uuid.UUID,
    payload: OobVerification,
    request: Request,
    member: MemberAccess = Depends(_require_owner),  # noqa: B008
) -> PayeeResponse:
    try:
        row = await _repository(request).verify_oob(
            organization_id=member.organization_id,
            treasury_id=treasury_id,
            payee_id=payee_id,
            user_id=member.user_id,
            method=payload.method,
            note=payload.note,
            at=datetime.now(UTC),
        )
    except NotAwaitingOwner:
        raise AuthFailure(
            status=409,
            code="NOT_AWAITING_OWNER",
            title="Payee is not awaiting the Owner",
            detail="Out-of-band verification can be recorded only for a screened payee.",
        ) from None
    except OobAlreadyVerified:
        raise AuthFailure(
            status=409,
            code="OOB_ALREADY_VERIFIED",
            title="Already verified",
            detail="Out-of-band verification was already recorded for this payee.",
        ) from None
    if row is None:
        raise _not_found()
    return PayeeResponse(payee=PayeeView.from_record(row))


@router.post(
    "/{payee_id}/registration-tx",
    status_code=201,
    response_model=PayeeTxResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def build_registration_tx(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payee_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_owner),  # noqa: B008
) -> dict[str, object]:
    row = await _repository(request).get_payee(
        organization_id=member.organization_id, treasury_id=treasury_id, payee_id=payee_id
    )
    if row is None:
        raise _not_found()
    refusal = check_registration_gates(row, now=datetime.now(UTC))
    if refusal is not None:
        raise refusal
    if row.registration_tx_id is not None:
        raise AuthFailure(
            status=409,
            code="REGISTRATION_TX_EXISTS",
            title="Registration already proposed",
            detail="This payee already has a registration transaction in progress.",
        )
    context = await _repository(request).get_context(
        organization_id=member.organization_id, treasury_id=treasury_id
    )
    if context is None:
        raise _not_found()
    if context.module_address is None:
        raise AuthFailure(
            status=409,
            code="MODULE_NOT_READY",
            title="Treasury module unavailable",
            detail="Deploy and activate the treasury module before registering payees.",
        )
    try:
        call = build_add_payee_call(context.module_address, payee=row.address)
    except ValueError:
        raise AuthFailure(
            status=409,
            code="MODULE_NOT_READY",
            title="Treasury module unavailable",
            detail="The treasury module address is invalid.",
        ) from None

    async def create_tx() -> tuple[uuid.UUID, dict[str, object]]:
        created = await _build_payee_governance_tx(
            request,
            organization_id=member.organization_id,
            treasury_id=treasury_id,
            user_id=member.user_id,
            purpose=GovernanceTxPurpose.PAYEE_ADD,
            call=call,
            payee_id=payee_id,
        )
        try:
            return uuid.UUID(str(created.get("id"))), created
        except ValueError:
            raise AuthFailure(
                status=503,
                code="GOVERNANCE_UNAVAILABLE",
                title="Governance unavailable",
                detail="The governance service returned an invalid transaction identifier.",
            ) from None

    governance_tx = await _repository(request).register_with_tx(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
        payee_id=payee_id,
        create_tx=create_tx,
    )
    if governance_tx is None:
        raise AuthFailure(
            status=409,
            code="PAYEE_CHANGED",
            title="Payee registration changed",
            detail="The payee is no longer awaiting registration; reload its current state.",
        )
    return {"governanceTx": governance_tx}


@router.post(
    "/{payee_id}/deactivation-tx",
    status_code=201,
    response_model=PayeeTxResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def build_deactivation_tx(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payee_id: uuid.UUID,
    payload: DeactivationRequest,
    request: Request,
    member: MemberAccess = Depends(_require_owner),  # noqa: B008
) -> dict[str, object]:
    row = await _repository(request).get_payee(
        organization_id=member.organization_id, treasury_id=treasury_id, payee_id=payee_id
    )
    if row is None:
        raise _not_found()
    if row.status not in (PayeeStatus.COOLING.value, PayeeStatus.ACTIVE.value):
        raise AuthFailure(
            status=409,
            code="PAYEE_NOT_REGISTERED",
            title="Payee is not registered",
            detail="Only a registered payee can be deactivated on-chain.",
        )
    context = await _repository(request).get_context(
        organization_id=member.organization_id, treasury_id=treasury_id
    )
    if context is None:
        raise _not_found()
    if context.module_address is None:
        raise AuthFailure(
            status=409,
            code="MODULE_NOT_READY",
            title="Treasury module unavailable",
            detail="Deploy and activate the treasury module before deactivating payees.",
        )
    try:
        call = build_deactivate_payee_call(context.module_address, payee=row.address)
    except ValueError:
        raise AuthFailure(
            status=409,
            code="MODULE_NOT_READY",
            title="Treasury module unavailable",
            detail="The treasury module address is invalid.",
        ) from None
    governance_tx = await _build_payee_governance_tx(
        request,
        organization_id=member.organization_id,
        treasury_id=treasury_id,
        user_id=member.user_id,
        purpose=GovernanceTxPurpose.PAYEE_DEACTIVATE,
        call=call,
        payee_id=payee_id,
    )
    await _repository(request).record_deactivation_requested(
        organization_id=member.organization_id,
        payee_id=payee_id,
        user_id=member.user_id,
        reason=payload.reason,
        governance_tx_id=governance_tx.get("id"),
    )
    return {"governanceTx": governance_tx}


@router.post(
    "/{payee_id}/replace-address",
    status_code=201,
    response_model=ReplacePayeeAddressResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def replace_payee_address(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payee_id: uuid.UUID,
    payload: ReplacePayeeAddressRequest,
    request: Request,
    member: MemberAccess = Depends(_require_owner),  # noqa: B008
) -> dict[str, object]:
    repository = _repository(request)
    old = await repository.get_payee(
        organization_id=member.organization_id, treasury_id=treasury_id, payee_id=payee_id
    )
    if old is None:
        raise _not_found()
    if old.status not in (PayeeStatus.COOLING.value, PayeeStatus.ACTIVE.value):
        raise AuthFailure(
            status=409,
            code="PAYEE_NOT_REGISTERED",
            title="Payee is not registered",
            detail="Only a registered payee address can be replaced.",
        )
    try:
        address = normalize_address(payload.address)
    except ValueError:
        raise AuthFailure(
            status=422,
            code="ADDRESS_INVALID",
            title="Address invalid",
            detail="The replacement must be a valid EVM address.",
        ) from None
    if address == old.address:
        raise AuthFailure(
            status=409,
            code="ADDRESS_UNCHANGED",
            title="Address unchanged",
            detail="Choose a different address to restart the payee cooling period.",
        )
    context = await repository.get_context(
        organization_id=member.organization_id, treasury_id=treasury_id
    )
    if context is None:
        raise _not_found()
    if address in context.wallet_addresses:
        raise AuthFailure(
            status=422,
            code="ADDRESS_IS_TREASURY_WALLET",
            title="Address invalid",
            detail="A treasury wallet cannot be registered as a payee.",
        )
    # Fail before proposing so a rejected replacement leaves no stray payee row.
    if context.module_address is None:
        raise AuthFailure(
            status=409,
            code="MODULE_NOT_READY",
            title="Treasury module unavailable",
            detail="Deploy and activate the treasury module before replacing payees.",
        )
    try:
        call = build_deactivate_payee_call(context.module_address, payee=old.address)
    except ValueError:
        raise AuthFailure(
            status=409,
            code="MODULE_NOT_READY",
            title="Treasury module unavailable",
            detail="The treasury module address is invalid.",
        ) from None
    try:
        new_payee = await repository.propose(
            organization_id=member.organization_id,
            treasury_id=treasury_id,
            vendor_id=old.vendor_id,
            user_id=member.user_id,
            label=old.label,
            address=address,
        )
    except PayeeExists:
        raise AuthFailure(
            status=409,
            code="PAYEE_EXISTS",
            title="Payee already exists",
            detail="The replacement address is already registered or under review.",
        ) from None

    record = await _screening(request).screen(
        organization_id=member.organization_id,
        address=address,
        chain_id=context.chain_id,
        payee_id=new_payee.id,
    )
    screened = await repository.finish_screening(
        organization_id=member.organization_id,
        treasury_id=treasury_id,
        payee_id=new_payee.id,
        user_id=member.user_id,
        result=record.result,
        provider=record.provider,
    )
    if screened is None:
        raise _not_found()
    if record.result == ScreeningResult.HIT:
        raise AuthFailure(
            status=422,
            code="SCREENING_HIT",
            title="Screening hit",
            detail="The replacement address matched a sanctions screening list.",
            extensions={"payeeId": str(new_payee.id), "status": screened.status},
        )
    if record.result != ScreeningResult.CLEAR:
        raise AuthFailure(
            status=503,
            code="DATA_MISSING",
            title="Screening could not complete",
            detail="The replacement address is blocked until screening succeeds.",
            extensions={"payeeId": str(new_payee.id), "status": screened.status},
        )
    deactivation_tx = await _build_payee_governance_tx(
        request,
        organization_id=member.organization_id,
        treasury_id=treasury_id,
        user_id=member.user_id,
        purpose=GovernanceTxPurpose.PAYEE_DEACTIVATE,
        call=call,
        payee_id=payee_id,
    )
    await repository.record_deactivation_requested(
        organization_id=member.organization_id,
        payee_id=payee_id,
        user_id=member.user_id,
        reason=payload.reason,
        governance_tx_id=deactivation_tx.get("id"),
    )
    return {
        "payee": PayeeView.from_record(screened),
        "deactivationGovernanceTx": deactivation_tx,
    }
