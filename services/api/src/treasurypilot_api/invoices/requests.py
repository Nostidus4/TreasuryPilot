from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from email import policy
from email.parser import BytesParser
from typing import cast

from eth_abi import encode
from eth_hash.auto import keccak
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import Field, ValidationError, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.models import AuditActorType
from treasurypilot_api.audit.writer import AuditActor, AuditEntity
from treasurypilot_api.audit.writer import write as write_audit
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.invoices.anomalies import (
    InvoiceRevisionSignals,
    PaidInvoice,
    evaluate_anomalies,
)
from treasurypilot_api.invoices.fingerprints import (
    DuplicateFingerprintConflict,
    compute_fingerprint,
    find_active_duplicate,
)
from treasurypilot_api.invoices.models import (
    TERMINAL_REQUEST_STATUSES,
    ApprovalStatus,
    CsvImport,
    PaymentApproval,
    PaymentRequest,
    RequestDocument,
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
from treasurypilot_api.invoices.near_duplicates import find_near_duplicates
from treasurypilot_api.invoices.state_machine import SqlAlchemyPayOperationGuard, TransitionAction
from treasurypilot_api.mandate.models import Payee, PayeeStatus, Vendor
from treasurypilot_api.mandate.vendors import normalize_vendor_ref
from treasurypilot_api.treasury.models import Asset, Chain, Treasury, TreasuryWallet
from treasurypilot_core.domain import PaymentTerms
from treasurypilot_core.engine import InvalidTerms, validate_terms
from treasurypilot_core.fingerprint import normalize
from treasurypilot_core.money import BaseUnits

router = APIRouter(prefix="/v1/orgs/{organization_id}/requests", tags=["requests"])
_require_operator = require_role(OrganizationRole.OPERATOR, OrganizationRole.ORG_ADMIN)

CSV_REQUIRED_COLUMNS = (
    "vendor_ref",
    "payee_address",
    "invoice_no",
    "issue_date",
    "due_date",
    "amount",
)
CSV_OPTIONAL_COLUMNS = ("terms_text", "note", "cost_center")
CSV_MAX_BYTES = 5 * 1024 * 1024
CSV_MAX_ROWS = 1_000
_ADDRESS_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]{40}$")


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

    @model_validator(mode="after")
    def _reject_null_required_fields(self) -> RequestPatch:
        # Only these columns accept NULL; an explicit null elsewhere would 500 downstream.
        nullable = {"paying_wallet_id", "terms", "note", "cost_center"}
        for name in self.model_fields_set - nullable:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


_BOUND_FIELDS = (
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
)
_FINGERPRINT_INDEX = "uq_payment_requests_active_fingerprint"


class ConfirmTermsRequest(ApiModel):
    terms: dict[str, object]


_TERMS_KEYS = {
    "netDueDay": "net_due_day",
    "discountBps": "discount_bps",
    "discountDeadlineDay": "discount_deadline_day",
    "lateFee": "late_fee",
    "priorityNote": "priority_note",
}


def _early_option(terms: PaymentTerms, amount: int) -> tuple[int, int] | None:
    if terms.discount_deadline_day is None:
        return None
    return (
        amount - amount * terms.discount_bps // 10_000,
        terms.discount_deadline_day * 86_400 + 86_399,
    )


def _validated_terms(
    raw: dict[str, object], amount: int
) -> tuple[dict[str, object], bytes, tuple[int, int] | None]:
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
    early = _early_option(terms, amount)
    if early is not None and early[0] <= 0:
        raise _fail(
            422,
            "TERMS_INVALID",
            "Payment terms invalid",
            "A discount must leave a positive early payment amount.",
        )
    return stored, digest, early


def confirmed_payment_terms(row: PaymentRequest) -> PaymentTerms | None:
    """Only confirmed terms may enter scheduler input."""
    if row.terms_confirmed_by is None or row.terms is None:
        return None
    return PaymentTerms.model_validate(row.terms)


class CsvImportCreated(ApiModel):
    row: int
    request_id: uuid.UUID | None
    invoice_number: str
    flags: list[str]


class CsvImportRowError(ApiModel):
    row: int
    field: str
    code: str
    message: str
    value: str


class CsvImportResponse(ApiModel):
    import_id: uuid.UUID | None
    dry_run: bool
    created: list[CsvImportCreated]
    errors: list[CsvImportRowError]
    error_report_url: str | None


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


def _validate_dates(issue_date: date, due_date: date) -> None:
    if due_date < issue_date:
        raise _fail(
            422, "DATE_INVALID", "Dates invalid", "The due date must be on or after the issue date."
        )


def _serialize(row: PaymentRequest) -> dict[str, object]:
    try:
        terms = confirmed_payment_terms(row)
    except ValidationError:  # stored terms no longer match the model; do not break reads
        terms = None
    early = (
        _early_option(terms, int(row.amount))
        if terms is not None and row.amount is not None
        else None
    )
    return {
        "id": str(row.id),
        "orgId": str(row.org_id),
        "treasuryId": str(row.treasury_id),
        "vendorId": str(row.vendor_id) if row.vendor_id else None,
        "payeeId": str(row.payee_id) if row.payee_id else None,
        "invoiceNo": row.invoice_no,
        "issueDate": row.issue_date.isoformat() if row.issue_date else None,
        "dueDate": row.due_at.isoformat() if row.due_at else None,
        "amount": str(row.amount) if row.amount is not None else None,
        "assetId": str(row.asset_id),
        "payingWalletId": str(row.paying_wallet_id) if row.paying_wallet_id else None,
        "terms": row.terms,
        "termsHash": "0x" + row.terms_hash.hex() if row.terms_hash else None,
        "termsConfirmedBy": str(row.terms_confirmed_by) if row.terms_confirmed_by else None,
        "termsConfirmedAt": row.terms_confirmed_at.isoformat() if row.terms_confirmed_at else None,
        "earlyAmount": str(early[0]) if early else None,
        "earlyPayBy": early[1] if early else None,
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
        "vendorId": str(row.vendor_id) if row.vendor_id else None,
        "payeeId": str(row.payee_id) if row.payee_id else None,
        "invoiceNo": row.invoice_no,
        "issueDate": row.issue_date.isoformat() if row.issue_date else None,
        "dueDate": row.due_at.isoformat() if row.due_at else None,
        "amount": str(row.amount) if row.amount is not None else None,
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
    require_active_payee: bool = True,
) -> tuple[Treasury, Vendor, Payee, Asset]:
    treasury = await session.scalar(
        select(Treasury)
        .where(Treasury.id == treasury_id, Treasury.org_id == organization_id)
        .with_for_update()
    )
    if treasury is None:
        raise _fail(
            422,
            "TREASURY_UNKNOWN",
            "Treasury invalid",
            "The treasury does not exist in this organization.",
        )
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
    if require_active_payee and payee.status == PayeeStatus.DEACTIVATED:
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


async def _bound_changed(
    session: AsyncSession, row: PaymentRequest, fields: dict[str, object]
) -> bool:
    """Whether the patch changes a bound field, comparing normalised stored values."""
    values = {key: fields[key] for key in _BOUND_FIELDS if key in fields}
    if "amount" in values:
        asset = await session.get(Asset, values.get("asset_id", row.asset_id))
        if asset is None:
            return True  # _bound_fields reports the invalid asset
        values["amount"] = _amount(str(values["amount"]), asset.decimals)
    current = {key: getattr(row, key) for key in values if key != "due_date"}
    current["due_date"] = row.due_at
    if "amount" in current:
        current["amount"] = None if row.amount is None else int(row.amount)
    return any(current[key] != value for key, value in values.items())


def _is_fingerprint_conflict(error: IntegrityError) -> bool:
    return _FINGERPRINT_INDEX in str(error.orig)


async def _raise_if_fingerprint_race(
    factory: async_sessionmaker[AsyncSession],
    error: IntegrityError,
    scope: tuple[uuid.UUID, bytes] | None,
    exclude_request_id: uuid.UUID | None = None,
) -> None:
    """Turn a lost unique-index race into the 409 that names the winning request."""
    if scope is None or not _is_fingerprint_conflict(error):
        return
    async with factory() as session:
        existing = await find_active_duplicate(
            session,
            treasury_id=scope[0],
            value=scope[1],
            exclude_request_id=exclude_request_id,
        )
    if existing is not None:
        raise DuplicateFingerprintConflict(existing) from error


def _hashes(
    row: PaymentRequest,
    vendor_ref: str,
    asset_address: bytes,
    document_sha256: bytes = bytes(32),
) -> bytes:
    if row.invoice_no is None or row.amount is None or row.issue_date is None or row.due_at is None:
        raise _fail(
            409,
            "EXTRACTION_UNCONFIRMED",
            "Extraction not confirmed",
            "Complete and confirm all invoice fields before hashing a request.",
        )
    value = compute_fingerprint(vendor_ref, row.invoice_no, int(row.amount), asset_address)
    row.fingerprint = value
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
                document_sha256,
            ],
        )
    )
    return value


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
    if row.due_at is None or row.issue_date is None or row.amount is None or row.payee_id is None:
        return []  # unconfirmed upload draft
    # shortcut: updated_at stands in for the paid date (any later write to a Paid row shifts it),
    # and every Paid row in the window is loaded for the median; revisit when paid_at exists.
    history_rows = await session.execute(
        select(
            PaymentRequest.amount, PaymentRequest.updated_at, PaymentRequest.payee_id, Payee.address
        )
        .join(Payee, Payee.id == PaymentRequest.payee_id)
        .where(
            PaymentRequest.vendor_id == row.vendor_id,
            # Amounts are raw base units, so only compare within the same asset (decimals).
            PaymentRequest.asset_id == row.asset_id,
            PaymentRequest.status == RequestStatus.PAID.value,
            PaymentRequest.updated_at
            >= datetime.combine(today - timedelta(days=365), datetime.min.time(), UTC),
        )
        .order_by(PaymentRequest.updated_at.desc())
    )
    history = tuple(
        PaidInvoice(int(amount), updated_at.date(), payee_id, address)
        for amount, updated_at, payee_id, address in history_rows
        if amount is not None and payee_id is not None  # Paid rows always have both
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
    if payee_address is None:
        raise _fail(
            422, "PAYEE_UNKNOWN", "Payee unknown", "The payee is not registered for this vendor."
        )
    if asset_symbol is None or chain_name is None:  # unreachable: FK-enforced
        raise RuntimeError("Request anomaly inputs are incomplete")
    # Only payee id and address are read; the amount and date are placeholders (not windowed).
    previous_paid = (
        PaidInvoice(0, today, previous_paid_row[0], previous_paid_row[1])
        if previous_paid_row is not None and previous_paid_row[0] is not None
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
    flags = [(anomaly.code, anomaly.severity, anomaly.evidence) for anomaly in anomaly_flags]
    for duplicate in await find_near_duplicates(session, row):
        flags.append(
            ("POSSIBLE_DUPLICATE", duplicate.severity, duplicate.evidence(row.invoice_no or ""))
        )
    result: list[dict[str, object]] = []
    for code, raw_severity, evidence in flags:
        severity = RequestFlagSeverity(raw_severity)
        flag = RequestFlag(
            id=uuid7(),
            request_id=row.id,
            revision=row.current_revision,
            code=code,
            severity=severity.value,
            evidence=evidence,
            source=RequestFlagSource.DETERMINISTIC.value,
        )
        session.add(flag)
        result.append(
            {
                "id": str(flag.id),
                "revision": row.current_revision,
                "code": code,
                "severity": severity.value,
                "evidence": evidence,
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


def _parse_csv_upload(content_type: str | None, body: bytes) -> tuple[bytes, uuid.UUID]:
    """Read the small multipart contract without making multipart a runtime parser dependency."""
    if not content_type or not content_type.casefold().startswith("multipart/form-data"):
        raise _fail(415, "CSV_MULTIPART_REQUIRED", "Multipart required", "Upload a multipart form.")
    try:
        message = BytesParser(policy=policy.default).parsebytes(
            b"MIME-Version: 1.0\r\nContent-Type: "
            + content_type.encode("ascii")
            + b"\r\n\r\n"
            + body
        )
    except (UnicodeEncodeError, ValueError):
        raise _fail(
            400, "CSV_MULTIPART_INVALID", "Multipart invalid", "The upload form is malformed."
        ) from None
    if not message.is_multipart():
        raise _fail(
            400, "CSV_MULTIPART_INVALID", "Multipart invalid", "The upload form is malformed."
        )
    file_bytes: bytes | None = None
    treasury_id: uuid.UUID | None = None
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        decoded = part.get_payload(decode=True)
        payload = decoded if isinstance(decoded, bytes) else b""
        if name == "file":
            file_bytes = payload
        elif name == "treasuryId":
            try:
                treasury_id = uuid.UUID(payload.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise _fail(
                    422, "TREASURY_INVALID", "Treasury invalid", "Provide a valid treasuryId."
                ) from None
    if file_bytes is None:
        raise _fail(
            422, "CSV_FILE_REQUIRED", "CSV file required", "Include a file part named file."
        )
    if len(file_bytes) > CSV_MAX_BYTES:
        raise _fail(413, "CSV_TOO_LARGE", "CSV too large", "The CSV file exceeds 5 MiB.")
    if treasury_id is None:
        raise _fail(422, "TREASURY_INVALID", "Treasury invalid", "Provide a valid treasuryId.")
    return file_bytes, treasury_id


def _csv_rows(file_bytes: bytes) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    try:
        source = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _fail(
            422, "CSV_ENCODING", "CSV encoding invalid", "Upload a UTF-8 CSV file."
        ) from None
    try:
        reader = csv.reader(io.StringIO(source, newline=""), strict=True)
        header = next(reader, None)
        optional = header[len(CSV_REQUIRED_COLUMNS) :] if header is not None else []
        if (
            header is None
            or header[: len(CSV_REQUIRED_COLUMNS)] != list(CSV_REQUIRED_COLUMNS)
            or any(name not in CSV_OPTIONAL_COLUMNS for name in optional)
            or optional != [name for name in CSV_OPTIONAL_COLUMNS if name in optional]
            or len(set(header)) != len(header)
        ):
            raise _fail(
                422,
                "CSV_HEADER_INVALID",
                "CSV header invalid",
                "Use the documented CSV template columns in order.",
            )
        rows: list[tuple[int, dict[str, str]]] = []
        while True:
            number = reader.line_num + 1  # physical line where this record starts
            values = next(reader, None)
            if values is None:
                break
            if not values or (len(values) == 1 and not values[0].strip()):
                continue
            if len(rows) >= CSV_MAX_ROWS:
                raise _fail(
                    422,
                    "CSV_ROW_LIMIT",
                    "CSV row limit exceeded",
                    "A CSV file may contain at most 1,000 data rows.",
                )
            parsed = dict(zip(header, values, strict=False))
            if len(values) != len(header):
                parsed["__csv_error__"] = "CSV_COLUMN_COUNT"
            rows.append((number, parsed))
    except csv.Error:
        raise _fail(422, "CSV_INVALID", "CSV invalid", "The CSV syntax is invalid.") from None
    return header, rows


def _csv_error(row: int, field: str, code: str, message: str, value: str = "") -> dict[str, object]:
    return {"row": row, "field": field, "code": code, "message": message, "value": value}


def _error_csv(errors: list[dict[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(("row", "field", "code", "message", "value"))
    for error in errors:
        values = [error.get(key, "") for key in ("row", "field", "code", "message", "value")]
        safe = [
            "'" + str(value) if str(value).startswith(("=", "+", "-", "@", "\t", "\r")) else value
            for value in values
        ]
        writer.writerow(safe)
    return output.getvalue().encode("utf-8")


@router.post(
    "/import-csv",
    responses={413: {"description": "CSV file exceeds the upload limit"}},
    openapi_extra={
        "x-organization-scoped": True,
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file", "treasuryId"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "treasuryId": {"type": "string", "format": "uuid"},
                        },
                    }
                }
            },
        },
    },
)
async def import_requests_csv(
    organization_id: uuid.UUID,
    request: Request,
    dry_run: bool = Query(default=False, alias="dryRun"),
    member: MemberAccess = Depends(_require_operator),  # noqa: B008
) -> CsvImportResponse:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > CSV_MAX_BYTES + 64 * 1024:
            raise _fail(413, "CSV_TOO_LARGE", "CSV too large", "The CSV file exceeds 5 MiB.")
    file_bytes, treasury_id = _parse_csv_upload(request.headers.get("content-type"), bytes(body))
    _header, rows = _csv_rows(file_bytes)
    return CsvImportResponse.model_validate(
        await _import_csv_rows(
            organization_id=member.organization_id,
            treasury_id=treasury_id,
            user_id=member.user_id,
            rows=rows,
            file_sha256=hashlib.sha256(file_bytes).digest(),
            dry_run=dry_run,
            factory=_sessions(request),
        )
    )


@router.get(
    "/import-csv/{import_id}/errors.csv",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}}}},
    openapi_extra={"x-organization-scoped": True},
)
async def download_csv_import_errors(
    organization_id: uuid.UUID,
    import_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_operator),  # noqa: B008
) -> StreamingResponse:
    async with _sessions(request)() as session:
        record = await session.scalar(
            select(CsvImport).where(
                CsvImport.id == import_id,
                CsvImport.org_id == member.organization_id,
            )
        )
    if record is None:
        raise _not_found()
    return StreamingResponse(
        io.BytesIO(_error_csv(record.errors)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="import-{import_id}-errors.csv"'},
    )


def _bulk_flag_codes(
    row: PaymentRequest, *, paid_payees: set[uuid.UUID], paid_by_vendor: dict[uuid.UUID, int]
) -> list[tuple[str, RequestFlagSeverity, dict[str, object]]]:
    flags: list[tuple[str, RequestFlagSeverity, dict[str, object]]] = []
    if row.due_at < datetime.now(UTC).date():
        flags.append(
            ("DUE_DATE_PAST", RequestFlagSeverity.LOW, {"dueDate": row.due_at.isoformat()})
        )
    if row.due_at > row.issue_date + timedelta(days=120):
        flags.append(
            (
                "DUE_DATE_FAR",
                RequestFlagSeverity.LOW,
                {"dueDate": row.due_at.isoformat(), "thresholdDays": 120},
            )
        )
    if row.payee_id not in paid_payees:
        flags.append(
            ("FIRST_PAYMENT_TO_PAYEE", RequestFlagSeverity.LOW, {"payeeId": str(row.payee_id)})
        )
    if paid_by_vendor.get(row.vendor_id, 0) < 5:
        flags.append(("NO_BASELINE", RequestFlagSeverity.LOW, {"minimumHistory": 5}))
    return flags


async def _import_csv_rows(
    *,
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    user_id: uuid.UUID,
    rows: list[tuple[int, dict[str, str]]],
    file_sha256: bytes,
    dry_run: bool,
    factory: async_sessionmaker[AsyncSession],
) -> dict[str, object]:
    errors: list[dict[str, object]] = []
    candidates: list[tuple[int, PaymentRequest, str]] = []
    seen: set[bytes] = set()
    async with factory() as session:
        treasury = await session.scalar(
            select(Treasury).where(Treasury.id == treasury_id, Treasury.org_id == organization_id)
        )
        if treasury is None:
            raise _not_found()
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
        vendors = {
            vendor.normalized_ref: vendor
            for vendor in await session.scalars(
                select(Vendor).where(Vendor.org_id == organization_id)
            )
        }
        payees = list(
            await session.scalars(
                select(Payee).where(
                    Payee.org_id == organization_id, Payee.treasury_id == treasury_id
                )
            )
        )
        payees_by_vendor_address = {
            (payee.vendor_id, payee.address): payee
            for payee in payees
            if payee.status != PayeeStatus.DEACTIVATED
        }
        deactivated_payee_addresses = {
            (payee.vendor_id, payee.address)
            for payee in payees
            if payee.status == PayeeStatus.DEACTIVATED
        }
        for line, cells in rows:
            if cells.get("__csv_error__"):
                errors.append(
                    _csv_error(
                        line,
                        "_row",
                        "CSV_COLUMN_COUNT",
                        "The row has a different number of columns than the header.",
                    )
                )
                continue
            row_errors: list[dict[str, object]] = []
            values = {
                name: cells.get(name, "").strip()
                for name in (*CSV_REQUIRED_COLUMNS, *CSV_OPTIONAL_COLUMNS)
            }
            nul_field = next((name for name, value in values.items() if "\x00" in value), None)
            if nul_field is not None:  # Postgres rejects NUL in text/JSONB; never echo it back
                errors.append(
                    _csv_error(
                        line,
                        nul_field,
                        "CSV_NUL_BYTE",
                        "Cells must not contain NUL characters.",
                    )
                )
                continue
            vendor_ref = normalize_vendor_ref(values["vendor_ref"])
            vendor = vendors.get(vendor_ref)
            if not vendor:
                row_errors.append(
                    _csv_error(
                        line,
                        "vendor_ref",
                        "VENDOR_UNKNOWN",
                        "No vendor matches this reference.",
                        values["vendor_ref"],
                    )
                )
            invoice_no = values["invoice_no"]
            if not invoice_no:
                row_errors.append(
                    _csv_error(
                        line, "invoice_no", "INVOICE_NO_REQUIRED", "Invoice number is required."
                    )
                )
            elif len(invoice_no) > 200:
                row_errors.append(
                    _csv_error(
                        line,
                        "invoice_no",
                        "INVOICE_NO_TOO_LONG",
                        "Invoice number must be at most 200 characters.",
                        invoice_no,
                    )
                )
            if len(values["cost_center"]) > 120:
                row_errors.append(
                    _csv_error(
                        line,
                        "cost_center",
                        "COST_CENTER_TOO_LONG",
                        "Cost center must be at most 120 characters.",
                        values["cost_center"],
                    )
                )
            issue_date: date | None = None
            due_date: date | None = None
            for field in ("issue_date", "due_date"):
                raw = values[field]
                try:
                    parsed_date = date.fromisoformat(raw)
                    if parsed_date.isoformat() != raw:
                        raise ValueError
                    if field == "issue_date":
                        issue_date = parsed_date
                    else:
                        due_date = parsed_date
                except ValueError:
                    row_errors.append(
                        _csv_error(
                            line,
                            field,
                            "DATE_INVALID",
                            "Use an ISO date in YYYY-MM-DD format.",
                            raw,
                        )
                    )
            if issue_date is not None and due_date is not None and due_date < issue_date:
                row_errors.append(
                    _csv_error(
                        line,
                        "due_date",
                        "DATE_INVALID",
                        "Due date must be on or after issue date.",
                        values["due_date"],
                    )
                )
            amount: int | None = None
            try:
                amount = _amount(values["amount"], asset.decimals)
            except AuthFailure as error:
                row_errors.append(
                    _csv_error(line, "amount", error.code, error.detail, values["amount"])
                )
            payee = None
            address_text = values["payee_address"]
            if not _ADDRESS_RE.fullmatch(address_text):
                row_errors.append(
                    _csv_error(
                        line,
                        "payee_address",
                        "PAYEE_ADDRESS_INVALID",
                        "Payee address must be a 20-byte hex address.",
                        address_text,
                    )
                )
            elif vendor is not None:
                address = bytes.fromhex(address_text.removeprefix("0x"))
                key = (vendor.id, address)
                payee = payees_by_vendor_address.get(key)
                if payee is None:
                    if key in deactivated_payee_addresses:
                        row_errors.append(
                            _csv_error(
                                line,
                                "payee_address",
                                "PAYEE_INACTIVE",
                                "A deactivated payee cannot receive a request.",
                                address_text,
                            )
                        )
                    else:
                        row_errors.append(
                            _csv_error(
                                line,
                                "payee_address",
                                "PAYEE_NOT_OF_VENDOR",
                                "Payee address is not registered to this vendor in the treasury.",
                                address_text,
                            )
                        )
            if row_errors:
                errors.extend(row_errors)
                continue
            assert (
                vendor is not None
                and payee is not None
                and issue_date is not None
                and due_date is not None
                and amount is not None
            )
            request_row = PaymentRequest(
                id=uuid7(),
                org_id=organization_id,
                treasury_id=treasury_id,
                chain_id=treasury.chain_id,
                vendor_id=vendor.id,
                payee_id=payee.id,
                invoice_no=invoice_no,
                issue_date=issue_date,
                due_at=due_date,
                amount=amount,
                asset_id=asset.id,
                source=RequestSource.CSV.value,
                status=RequestStatus.DRAFT.value,
                current_revision=1,
                created_by=user_id,
                last_edited_by=user_id,
                terms={"text": values["terms_text"]} if values["terms_text"] else None,
                note=values["note"] or None,
                cost_center=values["cost_center"] or None,
            )
            _hashes(request_row, vendor.normalized_ref, asset.address)
            assert request_row.fingerprint is not None
            if request_row.fingerprint in seen:
                errors.append(
                    _csv_error(
                        line,
                        "invoice_no",
                        "DUPLICATE_FINGERPRINT",
                        "An active request already uses this vendor, invoice number, amount and asset.",
                        invoice_no,
                    )
                )
                seen.add(request_row.fingerprint)
                continue
            seen.add(request_row.fingerprint)
            request_row.onchain_request_id = _request_id(organization_id, request_row.id)
            request_row.terms_hash = (
                keccak(
                    json.dumps(request_row.terms, sort_keys=True, separators=(",", ":")).encode()
                )
                if request_row.terms is not None
                else None
            )
            candidates.append((line, request_row, invoice_no))

        if candidates:
            taken = set(
                await session.scalars(
                    select(PaymentRequest.fingerprint).where(
                        PaymentRequest.treasury_id == treasury_id,
                        PaymentRequest.status.not_in(
                            [status.value for status in TERMINAL_REQUEST_STATUSES]
                        ),
                        PaymentRequest.fingerprint.in_(
                            [row.fingerprint for _, row, _ in candidates]
                        ),
                    )
                )
            )
            for line, row, invoice_no in candidates:
                if row.fingerprint in taken:
                    errors.append(
                        _csv_error(
                            line,
                            "invoice_no",
                            "DUPLICATE_FINGERPRINT",
                            "An active request already uses this vendor, invoice number, amount and asset.",
                            invoice_no,
                        )
                    )
            candidates = [item for item in candidates if item[1].fingerprint not in taken]
        errors.sort(key=lambda error: cast(int, error["row"]))

        paid_payees: set[uuid.UUID] = set()
        paid_by_vendor: dict[uuid.UUID, int] = {}
        if candidates:
            candidate_payee_ids = {row.payee_id for _, row, _ in candidates}
            candidate_vendor_ids = {row.vendor_id for _, row, _ in candidates}
            paid_payees = set(
                await session.scalars(
                    select(PaymentRequest.payee_id).where(
                        PaymentRequest.status == RequestStatus.PAID.value,
                        PaymentRequest.payee_id.in_(candidate_payee_ids),
                    )
                )
            )
            counts = await session.execute(
                select(PaymentRequest.vendor_id, func.count())
                .where(
                    PaymentRequest.status == RequestStatus.PAID.value,
                    PaymentRequest.vendor_id.in_(candidate_vendor_ids),
                )
                .group_by(PaymentRequest.vendor_id)
            )
            paid_by_vendor = {vendor_id: count for vendor_id, count in counts}

        if dry_run:
            return {
                "importId": None,
                "dryRun": True,
                "created": [
                    {
                        "row": line,
                        "requestId": None,
                        "invoiceNumber": invoice_no,
                        "flags": [
                            code
                            for code, _severity, _evidence in _bulk_flag_codes(
                                row,
                                paid_payees=paid_payees,
                                paid_by_vendor=paid_by_vendor,
                            )
                        ],
                    }
                    for line, row, invoice_no in candidates
                ],
                "errors": errors,
                "errorReportUrl": None,
            }

        record = CsvImport(
            id=uuid7(),
            org_id=organization_id,
            treasury_id=treasury_id,
            file_sha256=file_sha256,
            rows_total=len(rows),
            rows_created=0,
            errors=[],
            created_by=user_id,
        )
        session.add(record)
        await session.flush()
        created: list[dict[str, object]] = []
        for line, row, invoice_no in candidates:
            try:
                async with session.begin_nested():
                    session.add(row)
                    await session.flush()
                    session.add(
                        RequestRevision(
                            id=uuid7(),
                            request_id=row.id,
                            revision=1,
                            snapshot=_snapshot(row),
                            edited_by=user_id,
                        )
                    )
                    session.add(
                        RequestStatusEvent(
                            id=uuid7(),
                            request_id=row.id,
                            from_status=None,
                            to_status=RequestStatus.DRAFT.value,
                            actor_type=StatusEventActorType.USER.value,
                            actor_id=user_id,
                            reason=f"CSV import row {line}",
                        )
                    )
                    await session.flush()  # flags FK to the revision row
                    flag_rows = []
                    flag_codes = []
                    for code, severity, evidence in _bulk_flag_codes(
                        row, paid_payees=paid_payees, paid_by_vendor=paid_by_vendor
                    ):
                        flag_codes.append(code)
                        flag_rows.append(
                            RequestFlag(
                                id=uuid7(),
                                request_id=row.id,
                                revision=1,
                                code=code,
                                severity=severity.value,
                                evidence=evidence,
                                source=RequestFlagSource.DETERMINISTIC.value,
                            )
                        )
                    session.add_all(flag_rows)
                    await session.flush()
            except IntegrityError as error:
                if not _is_fingerprint_conflict(error):
                    raise
                errors.append(
                    _csv_error(
                        line,
                        "invoice_no",
                        "DUPLICATE_FINGERPRINT",
                        "An active request already uses this vendor, invoice number, amount and asset.",
                        invoice_no,
                    )
                )
                continue
            created.append(
                {
                    "row": line,
                    "requestId": str(row.id),
                    "invoiceNumber": invoice_no,
                    "flags": flag_codes,
                }
            )
        errors.sort(key=lambda error: cast(int, error["row"]))  # insert-time duplicates arrive late
        record.rows_created = len(created)
        record.errors = errors
        await session.flush()
        import_id = record.id
        await session.commit()
    return {
        "importId": str(import_id),
        "dryRun": False,
        "created": created,
        "errors": errors,
        "errorReportUrl": f"/v1/orgs/{organization_id}/requests/import-csv/{import_id}/errors.csv"
        if errors
        else None,
    }


@router.post("", status_code=201, openapi_extra={"x-organization-scoped": True})
async def create_request(
    organization_id: uuid.UUID,
    payload: RequestCreate,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=255
    ),
    member: MemberAccess = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    if idempotency_key is None:
        raise _fail(
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "Idempotency key required",
            "Provide an Idempotency-Key for this create request.",
        )
    _validate_dates(payload.issue_date, payload.due_date)
    factory = _sessions(request)
    payload_hash = _payload_hash(payload)
    scope: tuple[uuid.UUID, bytes] | None = None
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
                scope = (row.treasury_id, _hashes(row, vendor.normalized_ref, asset.address or b""))
                duplicate = await find_active_duplicate(
                    session, treasury_id=scope[0], value=scope[1]
                )
                if duplicate is not None:
                    raise DuplicateFingerprintConflict(duplicate)
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
        async with factory() as session:
            existing = await session.scalar(
                select(PaymentRequest).where(
                    PaymentRequest.org_id == member.organization_id,
                    PaymentRequest.idempotency_key == idempotency_key,
                )
            )
            if existing is None:
                await _raise_if_fingerprint_race(factory, error, scope)
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
    member: MemberAccess = Depends(_require_operator),  # noqa: B008
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
    factory = _sessions(request)
    scope: tuple[uuid.UUID, bytes] | None = None
    try:
        async with factory() as session, session.begin():
            row = await session.scalar(
                select(PaymentRequest)
                .where(
                    PaymentRequest.id == request_id, PaymentRequest.org_id == member.organization_id
                )
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
            bound_changed = await _bound_changed(session, row, fields)
            for key, value in fields.items():
                if key in {"note", "tags", "cost_center"}:
                    setattr(row, key, value)
            if bound_changed:
                if (  # unconfirmed upload draft
                    row.vendor_id is None
                    or row.payee_id is None
                    or row.invoice_no is None
                    or row.issue_date is None
                    or row.due_at is None
                    or row.amount is None
                ):
                    raise _fail(
                        409,
                        "EXTRACTION_UNCONFIRMED",
                        "Extraction not confirmed",
                        "Use the extraction confirmation endpoint to complete uploaded invoice fields.",
                    )
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
                    require_active_payee=payee_id != row.payee_id,
                )
                new_issue_date = fields.get("issue_date", row.issue_date)
                new_due_date = fields.get("due_date", row.due_at)
                _validate_dates(new_issue_date, new_due_date)
                amount = (
                    _amount(fields["amount"], asset.decimals)
                    if "amount" in fields
                    else int(row.amount)
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
                # Upload drafts must keep committing to the uploaded file in invoice_hash.
                document_sha256 = await session.scalar(
                    select(RequestDocument.sha256).where(RequestDocument.request_id == row.id)
                )
                scope = (
                    row.treasury_id,
                    _hashes(
                        row,
                        vendor.normalized_ref,
                        asset.address or b"",
                        document_sha256 or bytes(32),
                    ),
                )
                row.terms_hash = None
                row.terms_confirmed_by = None
                row.terms_confirmed_at = None
                duplicate = await find_active_duplicate(
                    session, treasury_id=scope[0], value=scope[1], exclude_request_id=row.id
                )
                if duplicate is not None:
                    raise DuplicateFingerprintConflict(duplicate)
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
                    await write_audit(
                        session,
                        org_id=member.organization_id,
                        actor=AuditActor(AuditActorType.USER, member.user_id),
                        action=TransitionAction.EDIT_BOUND_FIELDS.value,
                        entity=AuditEntity("payment_request", row.id),
                        data={"from": previous_status, "to": RequestStatus.DRAFT.value},
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
            # onupdate=func.now() expires updated_at; reload it before the sync serializer reads it.
            await session.refresh(row)
            result = _serialize(row)
            version = row.version
            revision = row.current_revision
    except IntegrityError as error:
        await _raise_if_fingerprint_race(factory, error, scope, request_id)
        raise
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
    if_match: str | None = Header(default=None, alias="If-Match"),
    member: MemberAccess = Depends(_require_operator),  # noqa: B008
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
                409, "NOT_EDITABLE", "Request cannot be edited", "Only a draft can confirm terms."
            )
        if row.amount is None:
            raise _fail(
                409,
                "EXTRACTION_UNCONFIRMED",
                "Extraction not confirmed",
                "Confirm the extracted invoice fields before confirming terms.",
            )
        stored, digest, _ = _validated_terms(payload.terms, int(row.amount))
        # Provisional terms are stored raw; compare in canonical form so an equivalent
        # spelling (camelCase, omitted defaults) does not bump the revision.
        try:
            current = _validated_terms(row.terms, int(row.amount))[0] if row.terms else None
        except AuthFailure:
            current = row.terms
        row.terms = stored
        if current != stored:
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
        if row.terms_confirmed_by is None or current != stored:
            # Re-confirming identical terms keeps the original confirmer.
            row.terms_confirmed_by = member.user_id
            row.terms_confirmed_at = datetime.now(UTC)
        await session.flush()
        await session.refresh(row)
        result = _serialize(row)
        version = row.version
    response.headers["ETag"] = f'"{version}"'
    return {"request": result}
