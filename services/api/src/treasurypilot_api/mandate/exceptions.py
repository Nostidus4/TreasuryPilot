"""Owner workflows for one-time mandate exceptions and duplicate overrides."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.events import AuditEvent, log_audit_event
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.invoices.models import (
    TERMINAL_REQUEST_STATUSES,
    ApprovalStatus,
    PaymentApproval,
    PaymentRequest,
    RequestStatus,
)
from treasurypilot_api.mandate.governance import (
    build_allow_duplicate_call,
    build_grant_exception_call,
    build_revoke_exception_call,
)
from treasurypilot_api.mandate.governance_service import GovernanceFailure, GovernanceService
from treasurypilot_api.mandate.models import (
    ExceptionStatus,
    GovernanceTx,
    GovernanceTxPurpose,
    GovernanceTxStatus,
    MandateException,
    MandateVersion,
    MandateVersionStatus,
    Payee,
)
from treasurypilot_api.mandate.payees import effective_payee_status
from treasurypilot_api.treasury.models import Asset, Treasury
from treasurypilot_api.treasury.safe import RpcUnavailable
from treasurypilot_core.domain import ApprovedRequest, PaymentTerms
from treasurypilot_core.engine.payment_terms import request_value
from treasurypilot_core.money import BaseUnits

router = APIRouter(prefix="/v1", tags=["mandate exceptions"])

_OPEN_EXCEPTION_STATUSES = (
    ExceptionStatus.REQUESTED,
    ExceptionStatus.PROPOSED,
    ExceptionStatus.GRANTED,
)


class GrantExceptionRequest(ApiModel):
    expiry_hours: int = Field(default=72, alias="expiryHours", ge=1, le=720)


class RejectExceptionRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value


class AllowDuplicateRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions = getattr(request.app.state, "request_sessions", None)
    if sessions is None:
        raise AuthFailure(
            status=503,
            code="EXCEPTION_UNAVAILABLE",
            title="Exception service unavailable",
            detail="Exception storage is not configured.",
        )
    return cast(async_sessionmaker[AsyncSession], sessions)


def _governance(request: Request) -> GovernanceService:
    service = getattr(request.app.state, "governance_service", None)
    if service is None:
        raise AuthFailure(
            status=503,
            code="GOVERNANCE_UNAVAILABLE",
            title="Governance unavailable",
            detail="Governance storage is not configured.",
        )
    return cast(GovernanceService, service)


def _fail(status: int, code: str, detail: str) -> AuthFailure:
    return AuthFailure(
        status=status,
        code=code,
        title="Exception request rejected",
        detail=detail,
    )


def _governance_failure(exc: GovernanceFailure) -> AuthFailure:
    return _fail(exc.status, exc.code, exc.detail)


def _module_address(treasury: Treasury) -> bytes:
    if treasury.module_address is None or len(treasury.module_address) != 20:
        raise _fail(409, "MODULE_NOT_READY", "Treasury module is not configured.")
    return bytes(treasury.module_address)


def _asset_address(asset: Asset) -> bytes:
    # The module represents its native asset with the zero address.
    return bytes(asset.address) if asset.address is not None else bytes(20)


def _pay_limits(
    config: dict[str, Any], *, asset_id: uuid.UUID, primary_asset_id: uuid.UUID
) -> tuple[int, int]:
    if asset_id != primary_asset_id:
        for policy in config.get("assetPolicies", []):
            if not isinstance(policy, dict) or str(policy.get("assetId")) != str(asset_id):
                continue
            if not policy.get("enabled", False):
                break
            limits = policy.get("limits", {})
            pay = limits.get("PAY", {}) if isinstance(limits, dict) else {}
            if not isinstance(pay, dict):
                return 0, 0
            return int(pay.get("perRequest", 0)), int(pay.get("daily", 0))
        raise _fail(409, "ASSET_NOT_ENABLED", "The request asset is not enabled in the mandate.")

    limits = config.get("limits", {})
    pay = limits.get("PAY", {}) if isinstance(limits, dict) else {}
    if not isinstance(pay, dict):
        return 0, 0
    return int(pay.get("perRequest", 0)), int(pay.get("daily", 0))


_ACTIVE_GOVERNANCE_STATUSES = (
    GovernanceTxStatus.COLLECTING,
    GovernanceTxStatus.READY,
    GovernanceTxStatus.SUBMITTED,
)


async def _grant_tx_pending(session: AsyncSession, row: MandateException) -> bool:
    """A Proposed exception is retryable once its grant tx failed, was replaced or cancelled."""
    status = await session.scalar(
        select(GovernanceTx.status).where(GovernanceTx.id == row.governance_tx_id)
    )
    return status not in {
        GovernanceTxStatus.FAILED,
        GovernanceTxStatus.SUPERSEDED,
        GovernanceTxStatus.CANCELLED,
    }


async def _request_context(
    sessions: async_sessionmaker[AsyncSession],
    *,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
) -> tuple[PaymentRequest, Treasury, Payee, Asset, MandateVersion] | None:
    async with sessions() as session:
        result = await session.execute(
            select(PaymentRequest, Treasury, Payee, Asset)
            .join(Treasury, Treasury.id == PaymentRequest.treasury_id)
            .join(Payee, Payee.id == PaymentRequest.payee_id)
            .join(Asset, Asset.id == PaymentRequest.asset_id)
            .where(
                PaymentRequest.id == request_id,
                PaymentRequest.org_id == organization_id,
                Treasury.org_id == organization_id,
                Payee.org_id == organization_id,
            )
        )
        item = result.one_or_none()
        if item is None:
            return None
        payment, treasury, payee, asset = item
        mandate = await session.scalar(
            select(MandateVersion).where(
                MandateVersion.treasury_id == payment.treasury_id,
                MandateVersion.org_id == organization_id,
                MandateVersion.status == MandateVersionStatus.ACTIVE,
            )
        )
        if mandate is None or mandate.onchain_version is None:
            raise _fail(409, "MANDATE_NOT_ACTIVE", "Treasury has no active on-chain mandate.")
        return payment, treasury, payee, asset, mandate


async def _valid_approvals(
    session: AsyncSession,
    payment: PaymentRequest,
    *,
    now: datetime,
) -> list[PaymentApproval]:
    return list(
        await session.scalars(
            select(PaymentApproval)
            .where(
                PaymentApproval.request_id == payment.id,
                PaymentApproval.revision == payment.current_revision,
                PaymentApproval.status == ApprovalStatus.VALID.value,
                PaymentApproval.expires_at > now,
            )
            .order_by(PaymentApproval.expires_at.desc())
        )
    )


def _approval_expiry(approvals: list[PaymentApproval]) -> datetime | None:
    expiries: list[datetime] = []
    for approval in approvals:
        message = approval.typed_data.get("message")
        if isinstance(message, dict) and message.get("expiry") is not None:
            try:
                expiries.append(datetime.fromtimestamp(int(message["expiry"]), UTC))
            except (TypeError, ValueError, OSError):
                expiries.append(approval.expires_at)
        else:
            expiries.append(approval.expires_at)
    # One current, unexpired approval is sufficient in M1, so bind the exception to the
    # latest still-valid approval rather than shortening it to another signature's expiry.
    return max(expiries) if expiries else None


def _value_if_granted(
    payment: PaymentRequest, payee: Payee, approval: PaymentApproval | None
) -> int | None:
    """Value a payment today using its confirmed terms and signed early-payment option."""
    if payment.amount is None or not isinstance(payment.terms, dict):
        return None
    try:
        terms = PaymentTerms.model_validate(payment.terms)
        now = int(datetime.now(UTC).timestamp())
        raw_message = approval.typed_data.get("message") if approval is not None else None
        message: Mapping[str, Any] = raw_message if isinstance(raw_message, Mapping) else {}
        early_pay_by = int(message.get("earlyPayBy", 0))
        early_amount_value = message.get("earlyAmount")
        early_amount = (
            BaseUnits(int(early_amount_value))
            if early_amount_value is not None
            and int(early_amount_value) > 0
            and now <= early_pay_by
            else None
        )
        request = ApprovedRequest(
            id=str(payment.id),
            paying_wallet="0x" + "00" * 20,
            payee="0x" + bytes(payee.address).hex(),
            amount=BaseUnits(int(payment.amount)),
            approved_seq=0,
            terms=terms,
            early_amount=early_amount,
            early_pay_by=early_pay_by if early_amount is not None else None,
        )
        return int(request_value(request, 0))
    except (TypeError, ValueError, KeyError):
        return None


@router.get("/orgs/{organization_id}/requests/{request_id}/exception")
async def get_exception(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(
            require_role(
                OrganizationRole.OWNER,
                OrganizationRole.OPERATOR,
                OrganizationRole.FINANCE,
            )
        ),
    ],
) -> dict[str, Any]:
    sessions = _sessions(request)
    context = await _request_context(
        sessions, organization_id=member.organization_id, request_id=request_id
    )
    if context is None:
        raise _fail(404, "REQUEST_NOT_FOUND", "Payment request not found.")
    payment, treasury, payee, asset, mandate = context
    if payment.amount is None:
        raise _fail(409, "REQUEST_NOT_READY", "Payment request has no confirmed amount.")
    cap, daily = _pay_limits(mandate.config, asset_id=asset.id, primary_asset_id=treasury.asset_id)
    try:
        daily_used = await _governance(request).read_used_today(
            payment.chain_id, _module_address(treasury), _asset_address(asset)
        )
    except GovernanceFailure as exc:
        raise _governance_failure(exc) from None
    except RpcUnavailable:
        raise _fail(
            503, "RPC_UNAVAILABLE", "Current PAY usage could not be read from chain."
        ) from None

    async with sessions() as session:
        exception = await session.scalar(
            select(MandateException)
            .where(
                MandateException.request_id == payment.id,
                MandateException.treasury_id == payment.treasury_id,
                MandateException.org_id == member.organization_id,
            )
            .order_by(MandateException.created_at.desc())
            .limit(1)
        )
        approvals = await _valid_approvals(session, payment, now=datetime.now(UTC))

    value = _value_if_granted(payment, payee, approvals[0] if approvals else None)
    return {
        "exception": _exception_json(exception) if exception is not None else None,
        "numbers": {
            "amount": str(payment.amount),
            "cap": str(cap),
            "dailyUsed": str(daily_used),
            "dailyRemainingAfter": str(daily - daily_used - int(payment.amount)),
            "valueIfGranted": str(value) if value is not None else None,
        },
        "aiDraft": None,
    }


def _exception_json(row: MandateException) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "requestId": str(row.request_id),
        "mandateVersion": row.mandate_onchain_version,
        "amount": str(row.amount),
        "payee": "0x" + bytes(row.payee).hex(),
        "expiry": row.expiry.isoformat(),
        "status": row.status.value,
        "governanceTxId": str(row.governance_tx_id) if row.governance_tx_id else None,
        "reason": row.reason,
    }


@router.post("/orgs/{organization_id}/requests/{request_id}/exception/grant-tx", status_code=201)
async def grant_exception(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: GrantExceptionRequest,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(OrganizationRole.OWNER, step_up=True)),
    ],
) -> dict[str, Any]:
    sessions = _sessions(request)
    context = await _request_context(
        sessions, organization_id=member.organization_id, request_id=request_id
    )
    if context is None:
        raise _fail(404, "REQUEST_NOT_FOUND", "Payment request not found.")
    payment, treasury, payee, asset, mandate = context
    if (
        payment.status in {status.value for status in TERMINAL_REQUEST_STATUSES}
        or payment.status == RequestStatus.PAID.value
    ):
        raise _fail(
            409, "REQUEST_NOT_ACTIVE", "A terminal or paid request cannot receive an exception."
        )
    if payment.amount is None or payment.onchain_request_id is None:
        raise _fail(409, "REQUEST_NOT_READY", "Payment request has no confirmed on-chain terms.")
    amount = int(payment.amount)
    onchain_request_id = bytes(payment.onchain_request_id)
    if mandate.onchain_version is None:
        raise _fail(409, "MANDATE_NOT_ACTIVE", "Treasury has no active on-chain mandate.")
    cap, daily = _pay_limits(mandate.config, asset_id=asset.id, primary_asset_id=treasury.asset_id)
    if int(payment.amount) <= cap:
        raise _fail(409, "NOT_OVER_CAP", "Request amount does not exceed the per-request cap.")
    if (
        effective_payee_status(payee.status.value, payee.active_from, now=datetime.now(UTC))
        != "Active"
    ):
        raise _fail(
            409, "PAYEE_NOT_ACTIVE", "Only an active payee can receive an exception payment."
        )
    try:
        daily_used = await _governance(request).read_used_today(
            payment.chain_id, _module_address(treasury), _asset_address(asset)
        )
    except GovernanceFailure as exc:
        raise _governance_failure(exc) from None
    except RpcUnavailable:
        raise _fail(
            503, "RPC_UNAVAILABLE", "Current PAY usage could not be read from chain."
        ) from None
    if daily_used + amount > daily:
        raise _fail(
            409,
            "DAILY_LIMIT_WOULD_EXCEED",
            "The full payment would exceed the on-chain daily PAY limit.",
        )

    now = datetime.now(UTC)
    async with sessions() as session:
        approvals = await _valid_approvals(session, payment, now=now)
    approval_expiry = _approval_expiry(approvals)
    if approval_expiry is None:
        raise _fail(409, "APPROVAL_EXPIRED", "A current approval is required for the exception.")
    expiry = min(now + timedelta(hours=payload.expiry_hours), approval_expiry, mandate.expires_at)
    expiry = datetime.fromtimestamp(int(expiry.timestamp()), UTC)
    if expiry <= now:
        raise _fail(409, "APPROVAL_EXPIRED", "The active approval expires before this exception.")
    if amount > (1 << 128) - 1:
        raise _fail(409, "EXCEPTION_AMOUNT_UNSUPPORTED", "Request amount exceeds the module limit.")

    call = build_grant_exception_call(
        _module_address(treasury),
        request_id=onchain_request_id,
        amount=amount,
        payee=bytes(payee.address),
        expiry=int(expiry.timestamp()),
    )
    try:
        async with sessions() as session, session.begin():
            # Serialize grant and reject actions for this request through tx creation.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"mandate-exception:{payment.id}"},
            )
            existing = await session.scalar(
                select(MandateException)
                .where(
                    MandateException.request_id == payment.id,
                    MandateException.treasury_id == payment.treasury_id,
                    MandateException.status.in_(_OPEN_EXCEPTION_STATUSES),
                )
                .with_for_update()
            )
            if (
                existing is not None
                and existing.status != ExceptionStatus.REQUESTED
                and (
                    existing.status != ExceptionStatus.PROPOSED
                    or await _grant_tx_pending(session, existing)
                )
            ):
                raise _fail(
                    409, "EXCEPTION_EXISTS", "This request already has an active exception."
                )
            if existing is None:
                existing = MandateException(
                    id=uuid.uuid4(),
                    org_id=member.organization_id,
                    treasury_id=payment.treasury_id,
                    request_id=payment.id,
                    mandate_onchain_version=mandate.onchain_version,
                    amount=amount,
                    payee=bytes(payee.address),
                    expiry=expiry,
                    status=ExceptionStatus.REQUESTED,
                    created_by=member.user_id,
                    updated_by=member.user_id,
                )
                session.add(existing)
            else:
                existing.mandate_onchain_version = mandate.onchain_version
                existing.amount = amount
                existing.payee = bytes(payee.address)
                existing.expiry = expiry
                existing.version += 1
                existing.updated_by = member.user_id
            await session.flush()
            governance = await _governance(request).create(
                organization_id=member.organization_id,
                treasury_id=payment.treasury_id,
                user_id=member.user_id,
                purpose=GovernanceTxPurpose.EXCEPTION_GRANT,
                calls=[call],
                entity_type="exception",
                entity_id=existing.id,
            )
            governance_tx = governance.get("governanceTx", governance)
            existing.status = ExceptionStatus.PROPOSED
            existing.governance_tx_id = uuid.UUID(str(governance_tx["id"]))
            existing.version += 1
            existing.updated_by = member.user_id
            await log_audit_event(
                session,
                AuditEvent(
                    org_id=member.organization_id,
                    actor_id=member.user_id,
                    action="exception.grant_requested",
                    entity_type="exception",
                    entity_id=existing.id,
                    data={
                        "requestId": str(payment.id),
                        "governanceTxId": str(existing.governance_tx_id),
                        "amount": str(amount),
                        "payee": "0x" + bytes(payee.address).hex(),
                        "mandateVersion": mandate.onchain_version,
                    },
                ),
            )
    except GovernanceFailure as exc:
        raise _governance_failure(exc) from None
    except RpcUnavailable:
        raise _fail(503, "RPC_UNAVAILABLE", "Safe state could not be read from chain.") from None
    return {"governanceTx": governance}


@router.post("/orgs/{organization_id}/requests/{request_id}/exception/reject")
async def reject_exception(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: RejectExceptionRequest,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(OrganizationRole.OWNER)),
    ],
) -> dict[str, Any]:
    context = await _request_context(
        _sessions(request), organization_id=member.organization_id, request_id=request_id
    )
    if context is None:
        raise _fail(404, "REQUEST_NOT_FOUND", "Payment request not found.")
    payment, _treasury, payee, _asset, mandate = context
    if (
        payment.status in {status.value for status in TERMINAL_REQUEST_STATUSES}
        or payment.status == RequestStatus.PAID.value
    ):
        raise _fail(
            409, "REQUEST_NOT_ACTIVE", "A terminal or paid request cannot receive an exception."
        )
    if payment.amount is None or mandate.onchain_version is None:
        raise _fail(409, "REQUEST_NOT_READY", "Payment request has no active mandate terms.")
    sessions = _sessions(request)
    async with sessions() as session, session.begin():
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"mandate-exception:{payment.id}"},
        )
        row = await session.scalar(
            select(MandateException)
            .where(
                MandateException.request_id == payment.id,
                MandateException.treasury_id == payment.treasury_id,
                MandateException.status.in_(_OPEN_EXCEPTION_STATUSES),
            )
            .with_for_update()
        )
        if row is not None and row.status == ExceptionStatus.GRANTED:
            raise _fail(
                409,
                "EXCEPTION_ACTIVE",
                "The exception is already granted on-chain; revoke it instead.",
            )
        if (
            row is not None
            and row.status == ExceptionStatus.PROPOSED
            and await _grant_tx_pending(session, row)
        ):
            raise _fail(
                409,
                "EXCEPTION_TX_PENDING",
                "An exception governance transaction is already pending.",
            )
        if row is None:
            row = MandateException(
                id=uuid.uuid4(),
                org_id=member.organization_id,
                treasury_id=payment.treasury_id,
                request_id=payment.id,
                mandate_onchain_version=mandate.onchain_version,
                amount=int(payment.amount),
                payee=bytes(payee.address),
                expiry=mandate.expires_at,
                status=ExceptionStatus.REJECTED,
                reason=payload.reason.strip(),
                created_by=member.user_id,
                updated_by=member.user_id,
            )
            session.add(row)
        else:
            row.status = ExceptionStatus.REJECTED
            row.reason = payload.reason.strip()
            row.version += 1
            row.updated_by = member.user_id
        await session.flush()
        await log_audit_event(
            session,
            AuditEvent(
                org_id=member.organization_id,
                actor_id=member.user_id,
                action="exception.rejected",
                entity_type="exception",
                entity_id=row.id,
                data={"requestId": str(payment.id), "reason": payload.reason},
            ),
        )
        result = _exception_json(row)
    return {"exception": result}


@router.post("/orgs/{organization_id}/requests/{request_id}/exception/revoke-tx", status_code=201)
async def revoke_exception(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(OrganizationRole.OWNER, step_up=True)),
    ],
) -> dict[str, Any]:
    context = await _request_context(
        _sessions(request), organization_id=member.organization_id, request_id=request_id
    )
    if context is None:
        raise _fail(404, "REQUEST_NOT_FOUND", "Payment request not found.")
    payment, treasury, _payee, _asset, _mandate = context
    if payment.onchain_request_id is None:
        raise _fail(409, "REQUEST_NOT_READY", "Payment request has no on-chain identifier.")
    sessions = _sessions(request)
    try:
        async with sessions() as session, session.begin():
            # Same lock as grant/reject so concurrent revokes cannot create two governance txs.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"mandate-exception:{payment.id}"},
            )
            row = await session.scalar(
                select(MandateException)
                .where(
                    MandateException.request_id == payment.id,
                    MandateException.treasury_id == payment.treasury_id,
                    MandateException.org_id == member.organization_id,
                    MandateException.status == ExceptionStatus.GRANTED,
                    MandateException.expiry > datetime.now(UTC),
                )
                .with_for_update()
            )
            if row is None:
                raise _fail(409, "NOT_GRANTED", "Only a live granted exception can be revoked.")
            if row.governance_tx_id is not None and await session.scalar(
                select(GovernanceTx.id).where(
                    GovernanceTx.id == row.governance_tx_id,
                    GovernanceTx.purpose == GovernanceTxPurpose.EXCEPTION_REVOKE,
                    GovernanceTx.status.in_(_ACTIVE_GOVERNANCE_STATUSES),
                )
            ):
                raise _fail(
                    409,
                    "EXCEPTION_TX_PENDING",
                    "A revoke governance transaction is already pending.",
                )
            call = build_revoke_exception_call(
                _module_address(treasury), request_id=bytes(payment.onchain_request_id)
            )
            governance = await _governance(request).create(
                organization_id=member.organization_id,
                treasury_id=payment.treasury_id,
                user_id=member.user_id,
                purpose=GovernanceTxPurpose.EXCEPTION_REVOKE,
                calls=[call],
                entity_type="exception",
                entity_id=row.id,
            )
            governance_tx = governance.get("governanceTx", governance)
            row.governance_tx_id = uuid.UUID(str(governance_tx["id"]))
            row.version += 1
            row.updated_by = member.user_id
            await log_audit_event(
                session,
                AuditEvent(
                    org_id=member.organization_id,
                    actor_id=member.user_id,
                    action="exception.revoke_requested",
                    entity_type="exception",
                    entity_id=row.id,
                    data={
                        "requestId": str(payment.id),
                        "governanceTxId": str(row.governance_tx_id),
                    },
                ),
            )
    except GovernanceFailure as exc:
        raise _governance_failure(exc) from None
    except RpcUnavailable:
        raise _fail(503, "RPC_UNAVAILABLE", "Safe state could not be read from chain.") from None
    return {"governanceTx": governance}


@router.post("/orgs/{organization_id}/requests/{request_id}/allow-duplicate-tx", status_code=201)
async def allow_duplicate(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: AllowDuplicateRequest,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(OrganizationRole.OWNER, step_up=True)),
    ],
) -> dict[str, Any]:
    sessions = _sessions(request)
    context = await _request_context(
        sessions, organization_id=member.organization_id, request_id=request_id
    )
    if context is None:
        raise _fail(404, "REQUEST_NOT_FOUND", "Payment request not found.")
    payment, treasury, _payee, _asset, _mandate = context
    if (
        payment.status in {status.value for status in TERMINAL_REQUEST_STATUSES}
        or payment.status == RequestStatus.PAID.value
    ):
        raise _fail(
            409, "REQUEST_NOT_ACTIVE", "A terminal or paid request cannot receive an override."
        )
    if payment.fingerprint is None or payment.onchain_request_id is None:
        raise _fail(409, "NOT_DUPLICATE", "The request has no confirmed invoice fingerprint.")
    async with sessions() as session:
        existing = await session.scalar(
            select(PaymentRequest.id).where(
                PaymentRequest.treasury_id == payment.treasury_id,
                PaymentRequest.id != payment.id,
                PaymentRequest.fingerprint == payment.fingerprint,
                PaymentRequest.status.not_in(TERMINAL_REQUEST_STATUSES),
            )
        )
    if existing is None:
        raise _fail(409, "NOT_DUPLICATE", "No matching active request fingerprint was found.")
    try:
        call = build_allow_duplicate_call(
            _module_address(treasury),
            fingerprint=bytes(payment.fingerprint),
            request_id=bytes(payment.onchain_request_id),
        )
        governance = await _governance(request).create(
            organization_id=member.organization_id,
            treasury_id=payment.treasury_id,
            user_id=member.user_id,
            purpose=GovernanceTxPurpose.ALLOW_DUPLICATE,
            calls=[call],
            entity_type="payment_request",
            entity_id=payment.id,
        )
    except GovernanceFailure as exc:
        raise _governance_failure(exc) from None
    except RpcUnavailable:
        raise _fail(503, "RPC_UNAVAILABLE", "Safe state could not be read from chain.") from None
    async with sessions() as session, session.begin():
        await log_audit_event(
            session,
            AuditEvent(
                org_id=member.organization_id,
                actor_id=member.user_id,
                action="request.duplicate_override_requested",
                entity_type="payment_request",
                entity_id=payment.id,
                data={
                    "fingerprint": "0x" + bytes(payment.fingerprint).hex(),
                    "governanceTxId": str(governance.get("governanceTx", governance).get("id")),
                    "reason": payload.reason,
                },
            ),
        )
    return {"governanceTx": governance}
