from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import cast

from eth_abi import encode
from eth_hash.auto import keccak
from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.access import MemberContext, require_role
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import Organization, OrganizationRole, WalletLink, uuid7
from treasurypilot_api.invoices.anomalies import (
    InvoiceRevisionSignals,
    PaidInvoice,
    evaluate_anomalies,
)
from treasurypilot_api.invoices.approval import (
    ApprovalChainReader,
    ApprovalExpiryError,
    build_approval_typed_data,
)
from treasurypilot_api.invoices.fingerprints import (
    DuplicateFingerprintConflict,
    assert_no_active_duplicate,
    find_active_duplicate,
)
from treasurypilot_api.invoices.models import (
    ApprovalStatus,
    PaymentApproval,
    PaymentRequest,
    RequestFlag,
    RequestFlagSeverity,
    RequestFlagSource,
    RequestFlagStatus,
    RequestRevision,
    RequestSource,
    RequestStatus,
    RequestStatusEvent,
    StatusEventActorType,
)
from treasurypilot_api.invoices.state_machine import SqlAlchemyPayOperationGuard
from treasurypilot_api.mandate.models import MandateVersion, MandateVersionStatus, Payee, Vendor
from treasurypilot_api.treasury.models import Asset, Chain, Treasury, TreasuryWallet
from treasurypilot_core.domain import PaymentTerms
from treasurypilot_core.eip712 import digest as eip712_digest
from treasurypilot_core.eip712 import verify_signature
from treasurypilot_core.engine import InvalidTerms, validate_terms
from treasurypilot_core.fingerprint import fingerprint, normalize
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy.context import RequestView

_APPROVAL_MAX_AGE_RANGE = (86_400, 60 * 86_400)  # mandate bounds: 1-60 days
router = APIRouter(prefix="/v1/orgs/{organization_id}/requests", tags=["requests"])
_require_operator = require_role(OrganizationRole.OPERATOR, OrganizationRole.ORG_ADMIN)
_require_approver = require_role(OrganizationRole.APPROVER)


class RequestCreate(ApiModel):
    treasury_id: uuid.UUID
    vendor_id: uuid.UUID
    payee_id: uuid.UUID
    invoice_no: str = Field(min_length=1, max_length=200)
    issue_date: date
    due_date: date
    amount: str = Field(min_length=1, max_length=80)
    asset_id: uuid.UUID
    paying_wallet_id: uuid.UUID | None = None
    terms: dict[str, object] | None = None
    note: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    cost_center: str | None = Field(default=None, max_length=120)


class RequestPatch(ApiModel):
    treasury_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    payee_id: uuid.UUID | None = None
    invoice_no: str | None = Field(default=None, min_length=1, max_length=200)
    issue_date: date | None = None
    due_date: date | None = None
    amount: str | None = Field(default=None, min_length=1, max_length=80)
    asset_id: uuid.UUID | None = None
    paying_wallet_id: uuid.UUID | None = None
    terms: dict[str, object] | None = None
    note: str | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    cost_center: str | None = Field(default=None, max_length=120)


class ConfirmTermsRequest(ApiModel):
    terms: dict[str, object]


class RequestReason(ApiModel):
    reason: str = Field(min_length=1, max_length=2000)


class FlagAcknowledgment(ApiModel):
    note: str = Field(min_length=10, max_length=2000)


class ApproveRequest(ApiModel):
    signature: str = Field(min_length=2, max_length=8192)
    revision: int = Field(gt=0)
    # The expiry from the typed data the approver signed; the server cannot re-derive it.
    expiry: int = Field(gt=0)


_TERMS_KEYS = {
    "netDueDay": "net_due_day",
    "discountBps": "discount_bps",
    "discountDeadlineDay": "discount_deadline_day",
    "lateFee": "late_fee",
    "priorityNote": "priority_note",
}


def _validated_terms(
    raw: dict[str, object], amount: int
) -> tuple[dict[str, object], bytes, int, int]:
    normalized = {_TERMS_KEYS.get(key, key): value for key, value in raw.items()}
    if isinstance(normalized.get("late_fee"), dict):
        late_fee = cast(dict[str, object], normalized["late_fee"])
        normalized["late_fee"] = {
            {"rateBps": "rate_bps", "periodDays": "period_days"}.get(key, key): value
            for key, value in late_fee.items()
        }
    try:
        terms = PaymentTerms.model_validate(normalized)
        validate_terms(terms)
    except (ValidationError, InvalidTerms) as error:
        raise _fail(422, "TERMS_INVALID", "Payment terms invalid", str(error)) from None
    stored = terms.model_dump(mode="json", exclude_none=True)
    digest = keccak(json.dumps(stored, sort_keys=True, separators=(",", ":")).encode())
    early_amount = 0
    early_pay_by = 0
    if terms.discount_deadline_day is not None:
        early_amount = amount - amount * terms.discount_bps // 10_000
        if early_amount <= 0:
            raise _fail(
                422,
                "TERMS_INVALID",
                "Payment terms invalid",
                "A discount must leave a positive early payment amount.",
            )
        early_pay_by = terms.discount_deadline_day * 86_400 + 86_399
    return stored, digest, early_amount, early_pay_by


def confirmed_payment_terms(row: PaymentRequest) -> PaymentTerms | None:
    """Only confirmed terms may enter scheduler input."""
    if row.terms_confirmed_by is None or row.terms is None:
        return None
    return PaymentTerms.model_validate(row.terms)


def _fail(status: int, code: str, title: str, detail: str) -> AuthFailure:
    return AuthFailure(status=status, code=code, title=title, detail=detail)


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    factory = getattr(request.app.state, "request_sessions", None)
    if factory is None:
        raise _fail(
            503,
            "REQUESTS_UNAVAILABLE",
            "Requests unavailable",
            "Request storage is not configured.",
        )
    return cast(async_sessionmaker[AsyncSession], factory)


def _amount(value: str, decimals: int) -> int:
    try:
        parsed = BaseUnits.parse(value, decimals)
    except ValueError as error:
        if "decimal places" in str(error):
            raise _fail(
                422,
                "AMOUNT_PRECISION",
                "Amount precision invalid",
                "The amount has more decimal places than the payment asset supports.",
            ) from None
        raise _fail(
            422,
            "AMOUNT_NOT_POSITIVE",
            "Amount invalid",
            "The amount must be a positive decimal value.",
        ) from None
    if parsed <= 0:
        raise _fail(
            422, "AMOUNT_NOT_POSITIVE", "Amount invalid", "The amount must be greater than zero."
        )
    if parsed >= 1 << 256:
        raise _fail(
            422,
            "AMOUNT_TOO_LARGE",
            "Amount invalid",
            "The amount exceeds the maximum supported payment value.",
        )
    return int(parsed)


def _not_found() -> AuthFailure:
    return _fail(
        404, "REQUEST_NOT_FOUND", "Request not found", "The request is not available to this user."
    )


def _expected_version(if_match: str | None) -> int:
    try:
        version = int(if_match.strip().removeprefix("W/").strip('"')) if if_match else None
    except ValueError:
        version = None
    if version is None:
        raise _fail(
            412,
            "PRECONDITION_FAILED",
            "Request changed",
            "Provide the current request version in If-Match.",
        )
    return version


async def assert_high_flags_acknowledged(session: AsyncSession, row: PaymentRequest) -> None:
    """Reject approval signing while a HIGH flag on this revision remains open."""
    unacknowledged = await session.scalar(
        select(RequestFlag.id)
        .where(
            RequestFlag.request_id == row.id,
            RequestFlag.revision == row.current_revision,
            RequestFlag.severity == RequestFlagSeverity.HIGH.value,
            RequestFlag.status == RequestFlagStatus.OPEN.value,
        )
        .limit(1)
    )
    if unacknowledged is not None:
        raise _fail(
            409,
            "HIGH_FLAGS_UNACKED",
            "High risk flags need acknowledgment",
            "An approver must acknowledge every open HIGH flag on the current revision.",
        )


def _duplicate_fingerprint(existing_request_id: uuid.UUID) -> AuthFailure:
    return AuthFailure(
        status=409,
        code="DUPLICATE_FINGERPRINT",
        title="Duplicate invoice",
        detail="An active request already uses this invoice fingerprint.",
        extensions={"existingRequestId": str(existing_request_id)},
    )


def _serialize(row: PaymentRequest) -> dict[str, object]:
    early_amount = 0
    early_pay_by = 0
    if confirmed_payment_terms(row) is not None:
        _, _, early_amount, early_pay_by = _validated_terms(row.terms or {}, int(row.amount))
    return {
        "id": str(row.id),
        "orgId": str(row.org_id),
        "treasuryId": str(row.treasury_id),
        "vendorId": str(row.vendor_id),
        "payeeId": str(row.payee_id),
        "invoiceNo": row.invoice_no,
        "issueDate": row.issue_date.isoformat(),
        "dueDate": row.due_at.isoformat(),
        "amount": str(row.amount),
        "assetId": str(row.asset_id),
        "payingWalletId": str(row.paying_wallet_id) if row.paying_wallet_id else None,
        "terms": row.terms,
        "termsHash": "0x" + row.terms_hash.hex() if row.terms_hash else None,
        "termsConfirmedBy": str(row.terms_confirmed_by) if row.terms_confirmed_by else None,
        "termsConfirmedAt": row.terms_confirmed_at.isoformat() if row.terms_confirmed_at else None,
        "earlyAmount": str(early_amount),
        "earlyPayBy": early_pay_by,
        "fingerprint": "0x" + row.fingerprint.hex() if row.fingerprint else None,
        "invoiceHash": "0x" + row.invoice_hash.hex() if row.invoice_hash else None,
        "onchainRequestId": "0x" + row.onchain_request_id.hex() if row.onchain_request_id else None,
        "source": row.source,
        "status": row.status,
        "currentRevision": row.current_revision,
        "createdBy": str(row.created_by) if row.created_by else None,
        "lastEditedBy": str(row.last_edited_by) if row.last_edited_by else None,
        "note": row.note,
        "tags": list(row.tags or []),
        "costCenter": row.cost_center,
        "version": row.version,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def _snapshot(row: PaymentRequest) -> dict[str, object]:
    return {
        "treasuryId": str(row.treasury_id),
        "vendorId": str(row.vendor_id),
        "payeeId": str(row.payee_id),
        "invoiceNo": row.invoice_no,
        "issueDate": row.issue_date.isoformat(),
        "dueDate": row.due_at.isoformat(),
        "amount": str(row.amount),
        "assetId": str(row.asset_id),
        "payingWalletId": str(row.paying_wallet_id) if row.paying_wallet_id else None,
        "terms": row.terms,
    }


async def _bound_fields(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    vendor_id: uuid.UUID,
    payee_id: uuid.UUID,
    asset_id: uuid.UUID,
    paying_wallet_id: uuid.UUID | None,
) -> tuple[Treasury, Vendor, Payee, Asset]:
    treasury = await session.scalar(
        select(Treasury)
        .where(Treasury.id == treasury_id, Treasury.org_id == organization_id)
        .with_for_update()
    )
    if treasury is None:
        raise _not_found()
    if treasury.asset_id != asset_id:
        raise _fail(
            422,
            "ASSET_NOT_PAYMENT_STABLECOIN",
            "Payment asset invalid",
            "Requests must use the treasury payment stablecoin.",
        )
    asset = await session.scalar(
        select(Asset).where(Asset.id == treasury.asset_id, Asset.chain_id == treasury.chain_id)
    )
    if asset is None or asset.address is None:
        raise _fail(
            422,
            "ASSET_NOT_PAYMENT_STABLECOIN",
            "Payment asset invalid",
            "The treasury payment asset must be an ERC-20 stablecoin.",
        )
    vendor = await session.scalar(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.org_id == organization_id)
    )
    if vendor is None:
        raise _fail(
            422,
            "VENDOR_UNKNOWN",
            "Vendor invalid",
            "The vendor does not exist in this organization.",
        )
    payee = await session.scalar(
        select(Payee).where(
            Payee.id == payee_id,
            Payee.treasury_id == treasury_id,
            Payee.vendor_id == vendor_id,
            Payee.org_id == organization_id,
        )
    )
    if payee is None:
        mismatched = await session.scalar(
            select(Payee.id).where(
                Payee.id == payee_id,
                Payee.treasury_id == treasury_id,
                Payee.org_id == organization_id,
            )
        )
        if mismatched is not None:
            raise _fail(
                422,
                "PAYEE_NOT_OF_VENDOR",
                "Payee does not belong to vendor",
                "Select a payee registered to the selected vendor.",
            )
        raise _fail(
            422, "PAYEE_UNKNOWN", "Payee invalid", "The payee does not exist in this treasury."
        )
    if payee.status == "Deactivated":
        raise _fail(
            422,
            "PAYEE_UNKNOWN",
            "Payee inactive",
            "A deactivated payee cannot receive a payment request.",
        )
    if paying_wallet_id is not None:
        wallet = await session.scalar(
            select(TreasuryWallet.id).where(
                TreasuryWallet.id == paying_wallet_id,
                TreasuryWallet.treasury_id == treasury_id,
                TreasuryWallet.org_id == organization_id,
            )
        )
        if wallet is None:
            raise _fail(
                422,
                "PAYING_WALLET_UNKNOWN",
                "Paying wallet invalid",
                "The paying wallet does not belong to this treasury.",
            )
    return treasury, vendor, payee, asset


def _hashes(row: PaymentRequest, vendor_ref: str, asset_address: bytes) -> None:
    row.fingerprint = fingerprint(
        vendor_ref, row.invoice_no, BaseUnits(int(row.amount)), "0x" + asset_address.hex()
    )
    row.invoice_hash = keccak(
        encode(
            ["string", "string", "uint256", "address", "string", "string", "bytes32"],
            [
                normalize(vendor_ref),
                normalize(row.invoice_no),
                int(row.amount),
                asset_address,
                row.issue_date.isoformat(),
                row.due_at.isoformat(),
                bytes(32),
            ],
        )
    )


def _request_id(org_id: uuid.UUID, request_id: uuid.UUID) -> bytes:
    return keccak(
        encode(["string", "bytes16", "bytes16"], ["TP_REQ_V1", org_id.bytes, request_id.bytes])
    )


def _payload_hash(payload: RequestCreate) -> bytes:
    return hashlib.sha256(
        json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).digest()


async def _recompute_flags(session: AsyncSession, row: PaymentRequest) -> list[dict[str, object]]:
    today = datetime.now(UTC).date()
    history_rows = await session.execute(
        select(
            PaymentRequest.amount, PaymentRequest.updated_at, PaymentRequest.payee_id, Payee.address
        )
        .join(Payee, Payee.id == PaymentRequest.payee_id)
        .where(
            PaymentRequest.vendor_id == row.vendor_id,
            PaymentRequest.status == RequestStatus.PAID.value,
            PaymentRequest.updated_at
            >= datetime.combine(today - timedelta(days=365), datetime.min.time(), UTC),
        )
        .order_by(PaymentRequest.updated_at.desc())
    )
    history = tuple(
        PaidInvoice(int(amount), updated_at.date(), payee_id, address)
        for amount, updated_at, payee_id, address in history_rows
    )
    previous_paid_row = (
        await session.execute(
            select(PaymentRequest.payee_id, Payee.address)
            .join(Payee, Payee.id == PaymentRequest.payee_id)
            .where(
                PaymentRequest.vendor_id == row.vendor_id,
                PaymentRequest.status == RequestStatus.PAID.value,
            )
            .order_by(PaymentRequest.updated_at.desc())
            .limit(1)
        )
    ).first()
    prior_paid_to_payee = (
        await session.scalar(
            select(PaymentRequest.id)
            .where(
                PaymentRequest.payee_id == row.payee_id,
                PaymentRequest.status == RequestStatus.PAID.value,
            )
            .limit(1)
        )
        is not None
    )
    payee_address = await session.scalar(
        select(Payee.address).where(Payee.id == row.payee_id, Payee.vendor_id == row.vendor_id)
    )
    asset_symbol = await session.scalar(select(Asset.symbol).where(Asset.id == row.asset_id))
    chain_name = await session.scalar(select(Chain.name).where(Chain.chain_id == row.chain_id))
    registered_addresses = tuple(
        await session.scalars(select(Payee.address).where(Payee.vendor_id == row.vendor_id))
    )
    if payee_address is None or asset_symbol is None or chain_name is None:
        raise RuntimeError("Request anomaly inputs are incomplete")
    previous_paid = (
        PaidInvoice(0, today, previous_paid_row[0], previous_paid_row[1])
        if previous_paid_row is not None
        else None
    )
    anomaly_flags = evaluate_anomalies(
        InvoiceRevisionSignals(
            issue_date=row.issue_date,
            due_date=row.due_at,
            amount=int(row.amount),
            payee_id=row.payee_id,
            payee_address=payee_address,
            asset_symbol=asset_symbol,
            chain_name=chain_name,
        ),
        history,
        registered_addresses=registered_addresses,
        prior_paid_to_payee=prior_paid_to_payee,
        previous_paid=previous_paid,
        today=today,
    )
    result: list[dict[str, object]] = []
    for anomaly in anomaly_flags:
        severity = RequestFlagSeverity(anomaly.severity)
        flag = RequestFlag(
            id=uuid7(),
            request_id=row.id,
            revision=row.current_revision,
            code=anomaly.code,
            severity=severity.value,
            evidence=anomaly.evidence,
            source=RequestFlagSource.DETERMINISTIC.value,
        )
        session.add(flag)
        result.append(
            {
                "id": str(flag.id),
                "revision": row.current_revision,
                "code": anomaly.code,
                "severity": severity.value,
                "evidence": anomaly.evidence,
                "status": "Open",
            }
        )
    return result


async def _flag_views(session: AsyncSession, row: PaymentRequest) -> list[dict[str, object]]:
    flags = await session.scalars(
        select(RequestFlag).where(
            RequestFlag.request_id == row.id,
            RequestFlag.revision == row.current_revision,
            RequestFlag.status != RequestFlagStatus.SUPERSEDED.value,
        )
    )
    return [
        {
            "id": str(flag.id),
            "revision": flag.revision,
            "code": flag.code,
            "severity": flag.severity,
            "evidence": flag.evidence,
            "status": flag.status,
        }
        for flag in flags
    ]


@router.post("", status_code=201, openapi_extra={"x-organization-scoped": True})
async def create_request(
    organization_id: uuid.UUID,
    payload: RequestCreate,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=255
    ),
    member: MemberContext = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    if idempotency_key is None:
        raise _fail(
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "Idempotency key required",
            "Provide an Idempotency-Key for this create request.",
        )
    factory = _sessions(request)
    payload_hash = _payload_hash(payload)
    try:
        async with factory() as session, session.begin():
            previous = await session.scalar(
                select(PaymentRequest)
                .where(
                    PaymentRequest.org_id == member.organization_id,
                    PaymentRequest.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if previous is not None:
                if previous.idempotency_payload_hash != payload_hash:
                    raise _fail(
                        409,
                        "IDEMPOTENCY_KEY_REUSED",
                        "Idempotency key reused",
                        "Use a new key when the create request changes.",
                    )
                row = previous
                flags = await _flag_views(session, row)
            else:
                treasury, vendor, _payee, asset = await _bound_fields(
                    session,
                    organization_id=member.organization_id,
                    treasury_id=payload.treasury_id,
                    vendor_id=payload.vendor_id,
                    payee_id=payload.payee_id,
                    asset_id=payload.asset_id,
                    paying_wallet_id=payload.paying_wallet_id,
                )
                amount = _amount(payload.amount, asset.decimals)
                row = PaymentRequest(
                    id=uuid7(),
                    org_id=member.organization_id,
                    treasury_id=treasury.id,
                    chain_id=treasury.chain_id,
                    vendor_id=vendor.id,
                    payee_id=payload.payee_id,
                    invoice_no=payload.invoice_no,
                    issue_date=payload.issue_date,
                    due_at=payload.due_date,
                    amount=amount,
                    asset_id=asset.id,
                    paying_wallet_id=payload.paying_wallet_id,
                    terms=payload.terms,
                    source=RequestSource.MANUAL.value,
                    status=RequestStatus.DRAFT.value,
                    current_revision=1,
                    created_by=member.user_id,
                    last_edited_by=member.user_id,
                    note=payload.note,
                    tags=payload.tags,
                    cost_center=payload.cost_center,
                    idempotency_key=idempotency_key,
                    idempotency_payload_hash=payload_hash,
                )
                _hashes(row, vendor.normalized_ref, asset.address or b"")
                assert row.fingerprint is not None
                duplicate = await find_active_duplicate(
                    session,
                    treasury_id=row.treasury_id,
                    value=row.fingerprint,
                )
                if duplicate is not None:
                    raise _duplicate_fingerprint(duplicate)
                row.onchain_request_id = _request_id(member.organization_id, row.id)
                row.terms_hash = None
                session.add(row)
                await session.flush()
                session.add(
                    RequestRevision(
                        id=uuid7(),
                        request_id=row.id,
                        revision=1,
                        snapshot=_snapshot(row),
                        edited_by=member.user_id,
                    )
                )
                session.add(
                    RequestStatusEvent(
                        id=uuid7(),
                        request_id=row.id,
                        from_status=None,
                        to_status=RequestStatus.DRAFT.value,
                        actor_type=StatusEventActorType.USER.value,
                        actor_id=member.user_id,
                        reason="manual request created",
                    )
                )
                flags = await _recompute_flags(session, row)
                await session.flush()
    except IntegrityError as error:
        constraint_name = getattr(
            getattr(error.orig, "diag", None),
            "constraint_name",
            getattr(error.orig, "constraint_name", None),
        )
        if constraint_name == "uq_payment_requests_active_fingerprint":
            fingerprint_value = row.fingerprint
            if fingerprint_value is None:
                raise error
            async with factory() as session:
                duplicate = await find_active_duplicate(
                    session,
                    treasury_id=row.treasury_id,
                    value=fingerprint_value,
                )
            if duplicate is not None:
                raise _duplicate_fingerprint(duplicate) from error
            raise
        if constraint_name != "uq_payment_requests_idempotency_key":
            raise
        async with factory() as session:
            existing = await session.scalar(
                select(PaymentRequest).where(
                    PaymentRequest.org_id == member.organization_id,
                    PaymentRequest.idempotency_key == idempotency_key,
                )
            )
            if existing is None:
                raise
            if existing.idempotency_payload_hash != payload_hash:
                raise _fail(
                    409,
                    "IDEMPOTENCY_KEY_REUSED",
                    "Idempotency key reused",
                    "Use a new key when the create request changes.",
                ) from error
            row = existing
            flags = await _flag_views(session, row)
    response.headers["ETag"] = f'"{row.version}"'
    return {"request": _serialize(row), "flags": flags}


@router.patch("/{request_id}", openapi_extra={"x-organization-scoped": True})
async def edit_request(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: RequestPatch,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    member: MemberContext = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    try:
        expected_version = int(if_match.strip().removeprefix("W/").strip('"')) if if_match else None
    except ValueError:
        expected_version = None
    if expected_version is None:
        raise _fail(
            412,
            "PRECONDITION_FAILED",
            "Request changed",
            "Provide the current request version in If-Match.",
        )
    fields = payload.model_dump(exclude_unset=True)
    async with _sessions(request)() as session, session.begin():
        row = await session.scalar(
            select(PaymentRequest)
            .where(PaymentRequest.id == request_id, PaymentRequest.org_id == member.organization_id)
            .with_for_update()
        )
        if row is None:
            raise _not_found()
        if row.version != expected_version:
            raise _fail(
                412,
                "PRECONDITION_FAILED",
                "Request changed",
                "The request changed since it was read; reload and try again.",
            )
        if row.status not in {RequestStatus.DRAFT.value, RequestStatus.APPROVED.value}:
            raise _fail(
                409,
                "NOT_EDITABLE",
                "Request cannot be edited",
                "Withdraw a request awaiting approval before editing it.",
            )
        bound_names = {
            "treasury_id",
            "vendor_id",
            "payee_id",
            "invoice_no",
            "issue_date",
            "due_date",
            "amount",
            "asset_id",
            "paying_wallet_id",
            "terms",
        }
        bound_changed = any(
            getattr(row, key_map) != value
            for key, value in fields.items()
            if (key_map := {"due_date": "due_at"}.get(key, key)) in bound_names
        )
        for key, value in fields.items():
            if key in {"note", "tags", "cost_center"}:
                setattr(row, key, value)
        if bound_changed:
            if await SqlAlchemyPayOperationGuard().has_in_flight_pay(
                session=session, request_id=row.id
            ):
                raise _fail(
                    409,
                    "PAYMENT_IN_FLIGHT",
                    "Payment in progress",
                    "Bound fields cannot change while a PAY operation is in flight.",
                )
            treasury_id = fields.get("treasury_id", row.treasury_id)
            vendor_id = fields.get("vendor_id", row.vendor_id)
            payee_id = fields.get("payee_id", row.payee_id)
            asset_id = fields.get("asset_id", row.asset_id)
            wallet_id = fields.get("paying_wallet_id", row.paying_wallet_id)
            treasury, vendor, _payee, asset = await _bound_fields(
                session,
                organization_id=member.organization_id,
                treasury_id=treasury_id,
                vendor_id=vendor_id,
                payee_id=payee_id,
                asset_id=asset_id,
                paying_wallet_id=wallet_id,
            )
            new_issue_date = fields.get("issue_date", row.issue_date)
            new_due_date = fields.get("due_date", row.due_at)
            amount = (
                _amount(fields["amount"], asset.decimals) if "amount" in fields else int(row.amount)
            )
            row.treasury_id, row.chain_id, row.vendor_id, row.payee_id = (
                treasury.id,
                treasury.chain_id,
                vendor.id,
                payee_id,
            )
            row.invoice_no, row.issue_date, row.due_at = (
                fields.get("invoice_no", row.invoice_no),
                new_issue_date,
                new_due_date,
            )
            row.amount, row.asset_id, row.paying_wallet_id = amount, asset.id, wallet_id
            if "terms" in fields:
                row.terms = fields["terms"]
            row.current_revision += 1
            row.last_edited_by = member.user_id
            _hashes(row, vendor.normalized_ref, asset.address or b"")
            row.terms_hash = None
            row.terms_confirmed_by = None
            row.terms_confirmed_at = None
            assert row.fingerprint is not None
            duplicate = await find_active_duplicate(
                session,
                treasury_id=row.treasury_id,
                value=row.fingerprint,
                exclude_request_id=row.id,
            )
            if duplicate is not None:
                raise _duplicate_fingerprint(duplicate)
            previous_status = row.status
            approval_invalidated = previous_status == RequestStatus.APPROVED.value
            await session.execute(
                update(PaymentApproval)
                .where(
                    PaymentApproval.request_id == row.id,
                    PaymentApproval.status == ApprovalStatus.VALID.value,
                )
                .values(status=ApprovalStatus.INVALIDATED.value)
            )
            await session.execute(
                update(RequestFlag)
                .where(
                    RequestFlag.request_id == row.id,
                    RequestFlag.status.in_(
                        [RequestFlagStatus.OPEN.value, RequestFlagStatus.ACKNOWLEDGED.value]
                    ),
                )
                .values(status=RequestFlagStatus.SUPERSEDED.value)
            )
            row.status = RequestStatus.DRAFT.value
            if previous_status == RequestStatus.APPROVED.value:
                session.add(
                    RequestStatusEvent(
                        id=uuid7(),
                        request_id=row.id,
                        from_status=previous_status,
                        to_status=RequestStatus.DRAFT.value,
                        actor_type=StatusEventActorType.USER.value,
                        actor_id=member.user_id,
                        reason="bound fields edited; approvals invalidated",
                    )
                )
            session.add(
                RequestRevision(
                    id=uuid7(),
                    request_id=row.id,
                    revision=row.current_revision,
                    snapshot=_snapshot(row),
                    edited_by=member.user_id,
                    reason="bound fields edited",
                )
            )
            flags = await _recompute_flags(session, row)
        elif fields:
            row.last_edited_by = member.user_id
            flags = []
            approval_invalidated = False
        else:
            flags = []
            approval_invalidated = False
        await session.flush()
        result = _serialize(row)
        version = row.version
        revision = row.current_revision
    response.headers["ETag"] = f'"{version}"'
    return {
        "request": result,
        "revision": revision,
        "approvalInvalidated": approval_invalidated,
        "flags": flags,
    }


@router.post("/{request_id}/terms/confirm", openapi_extra={"x-organization-scoped": True})
async def confirm_request_terms(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: ConfirmTermsRequest,
    request: Request,
    response: Response,
    member: MemberContext = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    async with _sessions(request)() as session, session.begin():
        row = await session.scalar(
            select(PaymentRequest)
            .where(PaymentRequest.id == request_id, PaymentRequest.org_id == member.organization_id)
            .with_for_update()
        )
        if row is None:
            raise _not_found()
        if row.status != RequestStatus.DRAFT.value:
            raise _fail(
                409, "NOT_EDITABLE", "Request cannot be edited", "Only a draft can confirm terms."
            )
        stored, digest, _, _ = _validated_terms(payload.terms, int(row.amount))
        if row.terms != stored:
            await session.execute(
                update(RequestFlag)
                .where(
                    RequestFlag.request_id == row.id,
                    RequestFlag.status.in_(
                        [RequestFlagStatus.OPEN.value, RequestFlagStatus.ACKNOWLEDGED.value]
                    ),
                )
                .values(status=RequestFlagStatus.SUPERSEDED.value)
            )
            row.terms = stored
            row.current_revision += 1
            row.last_edited_by = member.user_id
            session.add(
                RequestRevision(
                    id=uuid7(),
                    request_id=row.id,
                    revision=row.current_revision,
                    snapshot=_snapshot(row),
                    edited_by=member.user_id,
                    reason="payment terms confirmed",
                )
            )
            await _recompute_flags(session, row)
        row.terms_hash = digest
        row.terms_confirmed_by = member.user_id
        row.terms_confirmed_at = datetime.now(UTC)
        await session.flush()
        await session.refresh(row)
        result = _serialize(row)
        version = row.version
    response.headers["ETag"] = f'"{version}"'
    return {"request": result}


@router.post("/{request_id}/submit", openapi_extra={"x-organization-scoped": True})
async def submit_request(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    member: MemberContext = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    expected_version = _expected_version(if_match)
    async with _sessions(request)() as session, session.begin():
        row = await session.scalar(
            select(PaymentRequest)
            .where(PaymentRequest.id == request_id, PaymentRequest.org_id == member.organization_id)
            .with_for_update()
        )
        if row is None:
            raise _not_found()
        if row.version != expected_version:
            raise _fail(
                412,
                "PRECONDITION_FAILED",
                "Request changed",
                "The request changed since it was read; reload and try again.",
            )
        if row.status != RequestStatus.DRAFT.value:
            raise _fail(
                409, "NOT_EDITABLE", "Request cannot be submitted", "Only a draft can be submitted."
            )
        if row.terms is not None and row.terms_confirmed_by is None:
            raise _fail(
                409,
                "TERMS_UNCONFIRMED",
                "Payment terms need confirmation",
                "Confirm the extracted payment terms before submitting this request.",
            )
        if row.source == RequestSource.UPLOAD.value and row.extraction_confirmed_by is None:
            raise _fail(
                409,
                "EXTRACTION_UNCONFIRMED",
                "Extracted fields need confirmation",
                "Confirm the extracted invoice fields before submitting this request.",
            )
        if (
            row.treasury_id is None
            or row.vendor_id is None
            or row.payee_id is None
            or row.asset_id is None
            or row.invoice_no is None
            or row.issue_date is None
            or row.due_at is None
            or row.amount is None
        ):
            code = (
                "EXTRACTION_UNCONFIRMED"
                if row.source == RequestSource.UPLOAD.value
                else "REQUEST_FIELDS_INCOMPLETE"
            )
            raise _fail(
                409,
                code,
                "Request fields are incomplete",
                "Complete and confirm all required invoice fields before submitting this request.",
            )
        await _bound_fields(
            session,
            organization_id=member.organization_id,
            treasury_id=row.treasury_id,
            vendor_id=row.vendor_id,
            payee_id=row.payee_id,
            asset_id=row.asset_id,
            paying_wallet_id=row.paying_wallet_id,
        )
        try:
            await assert_no_active_duplicate(session, row)
        except DuplicateFingerprintConflict as error:
            raise _duplicate_fingerprint(error.existing_request_id) from error
        previous_status = row.status
        row.status = RequestStatus.AWAITING_APPROVAL.value
        session.add(
            RequestStatusEvent(
                id=uuid7(),
                request_id=row.id,
                from_status=previous_status,
                to_status=row.status,
                actor_type=StatusEventActorType.USER.value,
                actor_id=member.user_id,
                reason="request submitted for approval",
            )
        )
        await session.flush()
        await session.refresh(row)
        result, version = _serialize(row), row.version
    response.headers["ETag"] = f'"{version}"'
    return {"request": result}


@router.post("/{request_id}/withdraw", openapi_extra={"x-organization-scoped": True})
async def withdraw_request(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    member: MemberContext = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    return await _return_request_to_draft(
        organization_id=organization_id,
        request_id=request_id,
        request=request,
        response=response,
        expected_version=_expected_version(if_match),
        actor=member,
        reason="request withdrawn by operator",
        require_checker=False,
    )


@router.post("/{request_id}/request-changes", openapi_extra={"x-organization-scoped": True})
async def request_changes(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: RequestReason,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    member: MemberContext = Depends(_require_approver),  # noqa: B008
) -> dict[str, object]:
    return await _return_request_to_draft(
        organization_id=organization_id,
        request_id=request_id,
        request=request,
        response=response,
        expected_version=_expected_version(if_match),
        actor=member,
        reason=payload.reason,
        require_checker=True,
    )


async def _return_request_to_draft(
    *,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    request: Request,
    response: Response,
    expected_version: int,
    actor: MemberContext,
    reason: str,
    require_checker: bool,
) -> dict[str, object]:
    async with _sessions(request)() as session, session.begin():
        row = await session.scalar(
            select(PaymentRequest)
            .where(PaymentRequest.id == request_id, PaymentRequest.org_id == organization_id)
            .with_for_update()
        )
        if row is None:
            raise _not_found()
        if row.version != expected_version:
            raise _fail(
                412,
                "PRECONDITION_FAILED",
                "Request changed",
                "The request changed since it was read; reload and try again.",
            )
        if row.status != RequestStatus.AWAITING_APPROVAL.value:
            raise _fail(
                409,
                "NOT_EDITABLE",
                "Request cannot return to draft",
                "Only a request awaiting approval can return to draft.",
            )
        if require_checker:
            solo_mode = bool(
                await session.scalar(
                    select(Organization.solo_mode).where(Organization.id == organization_id)
                )
            )
            if not solo_mode and actor.user_id in {row.created_by, row.last_edited_by}:
                raise _fail(
                    409,
                    "MAKER_CHECKER",
                    "Maker cannot request changes",
                    "The creator or last editor cannot review this request.",
                )
        previous_status = row.status
        row.status = RequestStatus.DRAFT.value
        session.add(
            RequestStatusEvent(
                id=uuid7(),
                request_id=row.id,
                from_status=previous_status,
                to_status=row.status,
                actor_type=StatusEventActorType.USER.value,
                actor_id=actor.user_id,
                reason=reason,
            )
        )
        await session.flush()
        await session.refresh(row)
        result, version = _serialize(row), row.version
    response.headers["ETag"] = f'"{version}"'
    return {"request": result}


@router.post("/{request_id}/flags/{flag_id}/ack", openapi_extra={"x-organization-scoped": True})
async def acknowledge_flag(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    flag_id: uuid.UUID,
    payload: FlagAcknowledgment,
    request: Request,
    member: MemberContext = Depends(_require_approver),  # noqa: B008
) -> dict[str, object]:
    note = payload.note.strip()
    if len(note) < 10:
        raise _fail(422, "ACK_NOTE_TOO_SHORT", "Note too short", "Provide at least 10 characters.")
    async with _sessions(request)() as session, session.begin():
        row = await session.scalar(
            select(PaymentRequest)
            .where(PaymentRequest.id == request_id, PaymentRequest.org_id == organization_id)
            .with_for_update()
        )
        if row is None:
            raise _not_found()
        flag = await session.scalar(
            select(RequestFlag)
            .where(RequestFlag.id == flag_id, RequestFlag.request_id == row.id)
            .with_for_update()
        )
        if flag is None:
            raise _fail(404, "FLAG_NOT_FOUND", "Flag not found", "The flag is not available.")
        if (
            flag.status == RequestFlagStatus.SUPERSEDED.value
            or flag.revision != row.current_revision
        ):
            raise _fail(
                409,
                "FLAG_SUPERSEDED",
                "Flag superseded",
                "Only flags on the current request revision can be acknowledged.",
            )
        if flag.status != RequestFlagStatus.OPEN.value:
            raise _fail(
                409, "FLAG_NOT_OPEN", "Flag is not open", "Only open flags can be acknowledged."
            )
        if member.user_id == row.created_by:
            raise _fail(
                409,
                "MAKER_CHECKER",
                "Creator cannot acknowledge flags",
                "The creator cannot acknowledge this flag.",
            )
        solo_mode = bool(
            await session.scalar(
                select(Organization.solo_mode).where(Organization.id == organization_id)
            )
        )
        if not solo_mode and member.user_id == row.last_edited_by:
            raise _fail(
                409,
                "MAKER_CHECKER",
                "Maker cannot acknowledge flags",
                "The last editor cannot acknowledge this flag.",
            )
        flag.status = RequestFlagStatus.ACKNOWLEDGED.value
        flag.acknowledged_by = member.user_id
        flag.acknowledged_at = datetime.now(UTC)
        flag.ack_note = note
        await session.flush()
        result = {
            "id": str(flag.id),
            "revision": flag.revision,
            "code": flag.code,
            "severity": flag.severity,
            "evidence": flag.evidence,
            "status": flag.status,
            "acknowledgedBy": str(flag.acknowledged_by),
            "acknowledgedAt": flag.acknowledged_at.isoformat(),
            "ackNote": flag.ack_note,
        }
    return {"flag": result}


def _approval_chain(request: Request) -> ApprovalChainReader:
    chain = getattr(request.app.state, "approval_chain_reader", None)
    if chain is None:
        raise _fail(
            503,
            "RPC_UNAVAILABLE",
            "Approval chain reader unavailable",
            "On-chain approver verification is not configured.",
        )
    return cast(ApprovalChainReader, chain)


def _approval_signature(raw: str) -> bytes:
    try:
        signature = bytes.fromhex(raw.removeprefix("0x"))
    except ValueError:
        signature = b""
    if not signature:
        raise _fail(400, "SIGNATURE_INVALID", "Signature invalid", "Provide a hex signature.")
    return signature


async def _approval_typed_data(
    session: AsyncSession, row: PaymentRequest, expiry: int | None = None
) -> tuple[dict[str, object], int, int]:
    treasury = await session.scalar(select(Treasury).where(Treasury.id == row.treasury_id))
    asset = await session.scalar(select(Asset).where(Asset.id == row.asset_id))
    payee = await session.scalar(select(Payee).where(Payee.id == row.payee_id))
    if treasury is None or asset is None or payee is None:
        raise _fail(
            409,
            "APPROVAL_UNAVAILABLE",
            "Approval unavailable",
            "Bound request records are missing.",
        )
    if treasury.module_address is None or asset.address is None:
        raise _fail(
            503,
            "APPROVAL_UNAVAILABLE",
            "Approval unavailable",
            "The treasury module is not configured.",
        )
    if (
        row.onchain_request_id is None
        or row.invoice_hash is None
        or row.fingerprint is None
        or payee.address is None
    ):
        raise _fail(
            409,
            "APPROVAL_UNAVAILABLE",
            "Approval unavailable",
            "The request is missing signed fields.",
        )

    # The signed payingWallet must be the requester's explicit choice, never a server default.
    wallet = (
        await session.scalar(
            select(TreasuryWallet).where(
                TreasuryWallet.treasury_id == row.treasury_id,
                TreasuryWallet.id == row.paying_wallet_id,
            )
        )
        if row.paying_wallet_id is not None
        else None
    )
    if wallet is None:
        raise _fail(
            409,
            "PAYING_WALLET_UNKNOWN",
            "Paying wallet invalid",
            "Select an operational paying wallet on the request.",
        )

    mandate = await session.scalar(
        select(MandateVersion)
        .where(
            MandateVersion.treasury_id == row.treasury_id,
            MandateVersion.status == MandateVersionStatus.ACTIVE.value,
        )
        .order_by(MandateVersion.version.desc())
        .limit(1)
    )
    if mandate is None:
        raise _fail(
            409,
            "MANDATE_NOT_ACTIVE",
            "Mandate unavailable",
            "An active mandate is required to approve payments.",
        )
    approval_max_age_value = mandate.config.get(
        "approvalMaxAge", mandate.config.get("approval_max_age", 14 * 86_400)
    )
    if (
        isinstance(approval_max_age_value, bool)
        or not isinstance(approval_max_age_value, int)
        or not _APPROVAL_MAX_AGE_RANGE[0] <= approval_max_age_value <= _APPROVAL_MAX_AGE_RANGE[1]
    ):
        raise _fail(
            409,
            "APPROVAL_UNAVAILABLE",
            "Approval unavailable",
            "The active mandate has an invalid approvalMaxAge setting.",
        )
    approval_max_age = approval_max_age_value
    early_amount, early_pay_by = 0, 0
    if confirmed_payment_terms(row) is not None:
        _, _, early_amount, early_pay_by = _validated_terms(row.terms or {}, int(row.amount))
    # End of the due day UTC, matching the 23:59:59 UTC earlyPayBy convention (invoices README).
    deadline = int(datetime.combine(row.due_at, datetime.max.time(), tzinfo=UTC).timestamp())
    view = RequestView.model_validate(
        {
            "request_id": row.onchain_request_id,
            "status": row.status,
            "invoice_hash": row.invoice_hash,
            "fingerprint": row.fingerprint,
            "terms_hash": row.terms_hash or bytes(32),
            "paying_wallet": "0x" + wallet.safe_address.hex(),
            "payee": "0x" + payee.address.hex(),
            "amount": int(row.amount),
            "early_amount": early_amount,
            "early_pay_by": early_pay_by,
            "deadline": deadline,
        }
    )
    now = int(datetime.now(UTC).timestamp())
    try:
        typed = build_approval_typed_data(
            view,
            chain_id=row.chain_id,
            module_address="0x" + treasury.module_address.hex(),
            now=now,
            approval_max_age=approval_max_age,
            asset="0x" + asset.address.hex(),
            expiry=expiry,
        )
    except ApprovalExpiryError as error:
        raise _fail(
            400,
            "APPROVAL_EXPIRY_INVALID",
            "Approval expiry invalid",
            "Request fresh typed data and sign it before it expires.",
        ) from error
    except ValueError as error:
        raise _fail(
            409,
            "APPROVAL_UNAVAILABLE",
            "Approval unavailable",
            "The request cannot be approved in its current state.",
        ) from error
    signed_expiry = cast(int, cast(dict[str, object], typed["message"])["expiry"])
    return typed, signed_expiry, row.chain_id


async def _enforce_maker_checker(
    session: AsyncSession, organization_id: uuid.UUID, member: MemberContext, row: PaymentRequest
) -> bool:
    """Reject makers unless the org is in solo mode; return the org's solo-mode flag."""
    organization = await session.scalar(
        select(Organization).where(Organization.id == organization_id)
    )
    solo_mode = bool(organization and organization.solo_mode)
    if not solo_mode and member.user_id in {row.created_by, row.last_edited_by}:
        raise _fail(
            409,
            "MAKER_CHECKER",
            "Maker cannot approve request",
            "The creator or last editor cannot approve this request.",
        )
    return solo_mode


def _approval_view(row: PaymentApproval) -> dict[str, object]:
    return {
        "id": str(row.id),
        "requestId": str(row.request_id),
        "revision": row.revision,
        "approverAddress": "0x" + row.approver_address.hex(),
        "typedData": row.typed_data,
        "acknowledgedFlagIds": [str(item) for item in row.acknowledged_flag_ids],
        "soloMode": row.solo_mode,
        "expiresAt": row.expires_at.isoformat(),
        "status": row.status,
    }


@router.get("/{request_id}/approval-typed-data", openapi_extra={"x-organization-scoped": True})
async def get_approval_typed_data(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    request: Request,
    response: Response,
    member: MemberContext = Depends(_require_approver),  # noqa: B008
) -> dict[str, object]:
    async with _sessions(request)() as session:
        row = await session.scalar(
            select(PaymentRequest).where(
                PaymentRequest.id == request_id, PaymentRequest.org_id == organization_id
            )
        )
        if row is None:
            raise _not_found()
        if row.status != RequestStatus.AWAITING_APPROVAL.value:
            raise _fail(
                409,
                "NOT_AWAITING_APPROVAL",
                "Request is not awaiting approval",
                "Typed approval data is available only for requests awaiting approval.",
            )
        linked_wallet = await session.scalar(
            select(WalletLink.id)
            .where(WalletLink.user_id == member.user_id, WalletLink.unlinked_at.is_(None))
            .limit(1)
        )
        if linked_wallet is None:
            raise _fail(
                403,
                "WALLET_NOT_LINKED",
                "Wallet not linked",
                "Link an EVM wallet before approving a payment request.",
            )
        await _enforce_maker_checker(session, organization_id, member, row)
        await assert_high_flags_acknowledged(session, row)
        typed, _expiry, _chain_id = await _approval_typed_data(session, row)
        # The POST must echo this revision and the signed message.expiry.
        response.headers["X-Request-Revision"] = str(row.current_revision)
        return typed


@router.post("/{request_id}/approve", openapi_extra={"x-organization-scoped": True})
async def approve_request(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: ApproveRequest,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=255
    ),
    member: MemberContext = Depends(_require_approver),  # noqa: B008
) -> dict[str, object]:
    if idempotency_key is None:
        raise _fail(
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "Idempotency key required",
            "Provide an Idempotency-Key.",
        )
    signature = _approval_signature(payload.signature)
    chain_reader = _approval_chain(request)
    key_hash = keccak(idempotency_key.encode("utf-8"))
    factory = _sessions(request)
    result: dict[str, object]
    try:
        async with factory() as session, session.begin():
            row = await session.scalar(
                select(PaymentRequest)
                .where(PaymentRequest.id == request_id, PaymentRequest.org_id == organization_id)
                .with_for_update()
            )
            if row is None:
                raise _not_found()
            prior = await session.scalar(
                select(PaymentApproval)
                .where(
                    PaymentApproval.request_id == row.id,
                    PaymentApproval.idempotency_key_hash == key_hash,
                )
                .with_for_update()
            )
            if prior is not None:
                if (
                    prior.approver_user_id != member.user_id
                    or prior.revision != payload.revision
                    or prior.signature != signature
                ):
                    raise _fail(
                        409,
                        "IDEMPOTENCY_KEY_REUSED",
                        "Idempotency key reused",
                        "Use a new key when the approval request changes.",
                    )
                result = {
                    "request": _serialize(row),
                    "approval": _approval_view(prior),
                }
                response.headers["ETag"] = f'"{row.version}"'
                return result
            if payload.revision != row.current_revision:
                raise _fail(
                    409,
                    "REVISION_CHANGED",
                    "Request revision changed",
                    "Reload the request and sign the current revision.",
                )
            if row.status != RequestStatus.AWAITING_APPROVAL.value:
                raise _fail(
                    409,
                    "NOT_AWAITING_APPROVAL",
                    "Request is not awaiting approval",
                    "Only requests awaiting approval can be approved.",
                )
            linked_wallets = list(
                (
                    await session.scalars(
                        select(WalletLink)
                        .where(
                            WalletLink.user_id == member.user_id,
                            WalletLink.unlinked_at.is_(None),
                        )
                        .order_by(WalletLink.linked_at, WalletLink.id)
                    )
                ).all()
            )
            if not linked_wallets:
                raise _fail(
                    403,
                    "WALLET_NOT_LINKED",
                    "Wallet not linked",
                    "Link an EVM wallet before approving a payment request.",
                )
            solo_mode = await _enforce_maker_checker(session, organization_id, member, row)
            await assert_high_flags_acknowledged(session, row)
            typed, expiry, chain_id = await _approval_typed_data(session, row, payload.expiry)
            module_address = cast(
                str, cast(dict[str, object], typed["domain"])["verifyingContract"]
            )
            signer_address: str | None = None
            signer_wallet: WalletLink | None = None
            approval_digest = eip712_digest(typed)
            # EOA wallets first: they need no RPC, so a failing ERC-1271 call cannot mask them.
            for wallet in sorted(linked_wallets, key=lambda item: item.is_contract):
                address = "0x" + wallet.address.hex()
                if wallet.is_contract:
                    try:
                        valid = await chain_reader.is_valid_erc1271_signature(
                            chain_id=chain_id,
                            wallet=address,
                            digest=approval_digest,
                            signature=signature,
                        )
                    except Exception as error:
                        raise _fail(
                            503,
                            "RPC_UNAVAILABLE",
                            "Approval verification unavailable",
                            "Could not verify the linked contract wallet signature.",
                        ) from error
                else:
                    valid = verify_signature(typed, address, signature)
                if valid:
                    signer_address, signer_wallet = address, wallet
                    break
            if signer_address is None or signer_wallet is None:
                raise _fail(
                    400,
                    "SIGNATURE_INVALID",
                    "Signature invalid",
                    "The signature does not match an active wallet linked to this approver.",
                )
            try:
                onchain_approver = await chain_reader.is_approver(
                    chain_id=chain_id, module=module_address, signer=signer_address
                )
            except Exception as error:
                raise _fail(
                    503,
                    "RPC_UNAVAILABLE",
                    "Approver verification unavailable",
                    "Could not read the current on-chain approver set.",
                ) from error
            if not onchain_approver:
                raise _fail(
                    403,
                    "NOT_IN_APPROVER_SET",
                    "Signer is not an approver",
                    "The linked wallet is not in the treasury module's current approver set.",
                )
            acknowledged_flag_ids = list(
                (
                    await session.scalars(
                        select(RequestFlag.id).where(
                            RequestFlag.request_id == row.id,
                            RequestFlag.revision == row.current_revision,
                            RequestFlag.status == RequestFlagStatus.ACKNOWLEDGED.value,
                        )
                    )
                ).all()
            )
            approval = PaymentApproval(
                id=uuid7(),
                request_id=row.id,
                revision=row.current_revision,
                approver_user_id=member.user_id,
                approver_address=signer_wallet.address,
                idempotency_key_hash=key_hash,
                typed_data=typed,
                signature=signature,
                acknowledged_flag_ids=acknowledged_flag_ids,
                solo_mode=solo_mode and member.user_id in {row.created_by, row.last_edited_by},
                expires_at=datetime.fromtimestamp(expiry, UTC),
                status=ApprovalStatus.VALID.value,
            )
            session.add(approval)
            previous_status = row.status
            row.status = RequestStatus.APPROVED.value
            session.add(
                RequestStatusEvent(
                    id=uuid7(),
                    request_id=row.id,
                    from_status=previous_status,
                    to_status=row.status,
                    actor_type=StatusEventActorType.USER.value,
                    actor_id=member.user_id,
                    reason="request approved with verified EIP-712 signature",
                )
            )
            await session.flush()
            await session.refresh(row)
            await session.refresh(approval)
            result = {
                "request": _serialize(row),
                "approval": _approval_view(approval),
            }
            version = row.version
    except IntegrityError as error:
        constraint_name = getattr(
            getattr(error.orig, "diag", None),
            "constraint_name",
            getattr(error.orig, "constraint_name", None),
        )
        if constraint_name not in {
            "uq_approvals_request_revision_address",
            "uq_approvals_request_idempotency_key",
        }:
            raise
        raise _fail(
            409,
            "APPROVAL_EXISTS",
            "Request already approved",
            "A valid approval already exists for this request revision.",
        ) from error
    response.headers["ETag"] = f'"{version}"'
    return result
