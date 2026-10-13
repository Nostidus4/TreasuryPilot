from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import cast

from eth_abi import encode
from eth_hash.auto import keccak
from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.access import MemberContext, require_role
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.invoices.anomalies import (
    InvoiceRevisionSignals,
    PaidInvoice,
    evaluate_anomalies,
)
from treasurypilot_api.invoices.fingerprints import (
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
from treasurypilot_api.mandate.models import Payee, Vendor
from treasurypilot_api.treasury.models import Asset, Chain, Treasury, TreasuryWallet
from treasurypilot_core.fingerprint import fingerprint, normalize
from treasurypilot_core.money import BaseUnits

router = APIRouter(prefix="/v1/orgs/{organization_id}/requests", tags=["requests"])
_require_operator = require_role(OrganizationRole.OPERATOR, OrganizationRole.ORG_ADMIN)


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


def _duplicate_fingerprint(existing_request_id: uuid.UUID) -> AuthFailure:
    return AuthFailure(
        status=409,
        code="DUPLICATE_FINGERPRINT",
        title="Duplicate invoice",
        detail="An active request already uses this invoice fingerprint.",
        extensions={"existingRequestId": str(existing_request_id)},
    )


def _serialize(row: PaymentRequest) -> dict[str, object]:
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
                row.terms_hash = (
                    keccak(json.dumps(row.terms, sort_keys=True, separators=(",", ":")).encode())
                    if row.terms is not None
                    else None
                )
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
            assert row.fingerprint is not None
            row.terms_hash = (
                keccak(json.dumps(row.terms, sort_keys=True, separators=(",", ":")).encode())
                if row.terms is not None
                else None
            )
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
