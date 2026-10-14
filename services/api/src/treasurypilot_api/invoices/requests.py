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
from treasurypilot_api.identity.models import Organization, OrganizationRole, WalletLink, uuid7
from treasurypilot_api.identity.rbac import MemberAccess, maker_checker_conflict, require_role
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
    compute_fingerprint,
    find_active_duplicate,
)
from treasurypilot_api.invoices.fx import (
    FxProviderUnavailable,
    asset_key,
    capture_reference_quote,
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
from treasurypilot_api.invoices.state_machine import (
    AuditEntry,
    RequestStateMachine,
    RequestTransitionError,
    SqlAlchemyPayOperationGuard,
    TransitionAction,
    TransitionActor,
    validate_transition,
)
from treasurypilot_api.mandate.models import (
    MandateVersion,
    MandateVersionStatus,
    Payee,
    PayeeStatus,
    Vendor,
)
from treasurypilot_api.mandate.vendors import normalize_vendor_ref
from treasurypilot_api.treasury.models import Asset, Chain, Treasury, TreasuryWallet
from treasurypilot_core.domain import FxPolicy, PaymentTerms
from treasurypilot_core.eip712 import digest as eip712_digest
from treasurypilot_core.eip712 import verify_signature
from treasurypilot_core.engine import FiatPaymentBlocked, InvalidTerms, validate_terms
from treasurypilot_core.fingerprint import normalize
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy.context import RequestView

router = APIRouter(prefix="/v1/orgs/{organization_id}/requests", tags=["requests"])
_require_operator = require_role(OrganizationRole.OPERATOR, OrganizationRole.ORG_ADMIN)
_require_approver = require_role(OrganizationRole.APPROVER)
_require_canceller = require_role(
    OrganizationRole.OPERATOR, OrganizationRole.ORG_ADMIN, OrganizationRole.OWNER
)
_require_renewer = require_role(OrganizationRole.OPERATOR)
_require_cancel_tx_actor = require_role(OrganizationRole.APPROVER, OrganizationRole.OWNER)

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
    fiat_amount_minor_units: str | None = Field(
        default=None, min_length=1, max_length=78, pattern=r"^[1-9][0-9]*$"
    )
    fiat_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    paying_wallet_id: uuid.UUID | None = None
    terms: dict[str, object] | None = None
    note: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    cost_center: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _validate_fiat_pair(self) -> RequestCreate:
        if (self.fiat_amount_minor_units is None) != (self.fiat_currency is None):
            raise ValueError("fiat_amount_minor_units and fiat_currency must be supplied together")
        return self


class RequestPatch(ApiModel):
    treasury_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    payee_id: uuid.UUID | None = None
    invoice_no: str | None = Field(default=None, min_length=1, max_length=200)
    issue_date: date | None = None
    due_date: date | None = None
    amount: str | None = Field(default=None, min_length=1, max_length=80)
    asset_id: uuid.UUID | None = None
    fiat_amount_minor_units: str | None = Field(
        default=None, min_length=1, max_length=78, pattern=r"^[1-9][0-9]*$"
    )
    fiat_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    paying_wallet_id: uuid.UUID | None = None
    terms: dict[str, object] | None = None
    note: str | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    cost_center: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _reject_null_required_fields(self) -> RequestPatch:
        # Only these columns accept NULL; an explicit null elsewhere would 500 downstream.
        nullable = {
            "paying_wallet_id",
            "terms",
            "note",
            "cost_center",
            "fiat_amount_minor_units",
            "fiat_currency",
        }
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
    "fiat_amount_minor_units",
    "fiat_currency",
    "paying_wallet_id",
    "terms",
)
_FINGERPRINT_INDEX = "uq_payment_requests_active_fingerprint"


class ConfirmTermsRequest(ApiModel):
    terms: dict[str, object]


class RequestReason(ApiModel):
    reason: str = Field(min_length=1, max_length=2000)


class RenewRequest(ApiModel):
    due_date: date | None = None


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


def _fiat_amount(value: str | None) -> int | None:
    if value is None:
        return None
    # Pydantic already enforces canonical digits at the HTTP boundary; keep this
    # check for internal callers and before converting untrusted input to int.
    if not value.isascii() or not value.isdigit() or value.startswith("0"):
        raise _fail(
            422, "FIAT_AMOUNT_INVALID", "Fiat amount invalid", "Use positive integer minor units."
        )
    parsed = int(value)
    if not 0 < parsed < 1 << 256:
        raise _fail(
            422, "FIAT_AMOUNT_INVALID", "Fiat amount invalid", "Use positive integer minor units."
        )
    return parsed


def _fiat_pair(currency: str | None, fiat_amount_minor_units: int | None) -> None:
    if (currency is None) != (fiat_amount_minor_units is None):
        raise _fail(
            422,
            "FIAT_FIELDS_REQUIRED",
            "Fiat fields incomplete",
            "Provide both fiatAmountMinorUnits and fiatCurrency, or clear both.",
        )


def _edit_fiat_fields(
    row: PaymentRequest, fields: dict[str, object]
) -> tuple[int | None, str | None]:
    """Fiat amount/currency after applying a patch (amount already parsed to int)."""
    amount = (
        cast(int | None, fields["fiat_amount_minor_units"])
        if "fiat_amount_minor_units" in fields
        else None
        if row.fiat_amount_minor_units is None
        else int(row.fiat_amount_minor_units)
    )
    currency = cast(str | None, fields.get("fiat_currency", row.fiat_currency))
    _fiat_pair(currency, amount)
    return amount, currency


def _fiat_recapture_needed(
    row: PaymentRequest,
    fields: dict[str, object],
    fiat_amount_minor_units: int | None,
    currency: str | None,
    asset: Asset,
) -> bool:
    """A fresh FX quote is only warranted when what the quote prices has changed."""
    current_fiat = None if row.fiat_amount_minor_units is None else int(row.fiat_amount_minor_units)
    return (
        (fiat_amount_minor_units, currency, asset.id)
        != (current_fiat, row.fiat_currency, row.asset_id)
        or row.fx_reference_quote is None
        or ("amount" in fields and _amount(str(fields["amount"]), asset.decimals) != row.amount)
    )


async def _capture_fiat_reference(
    request: Request,
    *,
    currency: str | None,
    fiat_amount_minor_units: int | None,
    max_stablecoin_amount: int,
    asset: Asset | None,
) -> tuple[dict[str, object] | None, int | None]:
    if currency is None or fiat_amount_minor_units is None:
        _fiat_pair(currency, fiat_amount_minor_units)  # raises when only one is set
        return None, None
    if asset is None or asset.address is None or len(asset.address) != 20:
        raise _fail(
            422,
            "ASSET_NOT_PAYMENT_STABLECOIN",
            "Payment asset invalid",
            "The treasury payment asset must be an ERC-20 stablecoin.",
        )
    state = request.app.state
    provider = getattr(state, "fx_quote_provider", None)
    policy = getattr(state, "fx_policy", None)
    tolerance_bps = getattr(state, "fx_tolerance_bps", None)
    if (
        provider is None
        or not isinstance(policy, FxPolicy)
        or type(tolerance_bps) is not int
        or not 0 <= tolerance_bps <= 10_000
    ):
        raise _fail(
            503,
            "FX_UNAVAILABLE",
            "FX quotes unavailable",
            "A configured FX quote source and policy are required for fiat requests.",
        )
    try:
        quote = await capture_reference_quote(
            provider,
            fiat_currency=currency,
            fiat_amount_minor_units=fiat_amount_minor_units,
            stablecoin_asset=asset_key(asset.address),
            max_stablecoin_amount=max_stablecoin_amount,
            tolerance_bps=tolerance_bps,
            policy=policy,
            now_timestamp=int(datetime.now(UTC).timestamp()),
        )
    except FxProviderUnavailable:
        raise _fail(
            503,
            "FX_UNAVAILABLE",
            "FX quotes unavailable",
            "The configured FX quote source is temporarily unavailable.",
        ) from None
    except FiatPaymentBlocked as error:
        code = "FX_MAX_EXCEEDED" if error.reason == "APPROVED_MAX_EXCEEDED" else "FX_QUOTE_INVALID"
        raise _fail(422, code, "Fiat quote invalid", error.reason) from None
    return quote.model_dump(mode="json"), tolerance_bps


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
        # For fiat requests amount/maxStablecoinAmount is the cap signed by approvers.
        "maxStablecoinAmount": str(row.amount) if row.amount is not None else None,
        "assetId": str(row.asset_id),
        "fiatAmountMinorUnits": (
            str(row.fiat_amount_minor_units) if row.fiat_amount_minor_units is not None else None
        ),
        "fiatCurrency": row.fiat_currency,
        "fxReferenceQuote": row.fx_reference_quote,
        "fxToleranceBps": row.fx_tolerance_bps,
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
        "maxStablecoinAmount": str(row.amount) if row.amount is not None else None,
        "assetId": str(row.asset_id),
        "fiatAmountMinorUnits": (
            str(row.fiat_amount_minor_units) if row.fiat_amount_minor_units is not None else None
        ),
        "fiatCurrency": row.fiat_currency,
        "fxReferenceQuote": row.fx_reference_quote,
        "fxToleranceBps": row.fx_tolerance_bps,
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
    if "fiat_amount_minor_units" in current and current["fiat_amount_minor_units"] is not None:
        current["fiat_amount_minor_units"] = int(current["fiat_amount_minor_units"])
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
    types = ["string", "string", "uint256", "address", "string", "string"]
    values: list[object] = [
        normalize(vendor_ref),
        normalize(row.invoice_no),
        int(row.amount),
        asset_address,
        row.issue_date.isoformat(),
        row.due_at.isoformat(),
    ]
    if row.fiat_currency is not None:
        # Fiat fields are appended only for fiat requests so hashes (and signed approvals) of
        # existing non-fiat requests keep their original 7-field encoding.
        types += ["string", "string", "uint256", "string"]
        values += [
            str(row.fiat_amount_minor_units),
            row.fiat_currency,
            int(row.fx_tolerance_bps or 0),
            json.dumps(row.fx_reference_quote, sort_keys=True, separators=(",", ":")),
        ]
    row.invoice_hash = keccak(encode([*types, "bytes32"], [*values, document_sha256]))
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
    if row.due_at is None or row.issue_date is None or row.vendor_id is None:
        return flags  # CSV rows always carry these; only upload drafts lack them
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
            paid_by_vendor = {
                vendor_id: count for vendor_id, count in counts if vendor_id is not None
            }

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
    # Quote before the transaction so the external call never holds DB locks. Replays of an
    # existing key skip it: they return the stored request, whatever the market does now.
    fx: tuple[dict[str, object] | None, int | None] = (None, None)
    fiat_amount_minor_units = _fiat_amount(payload.fiat_amount_minor_units)
    if payload.fiat_currency is not None:
        async with factory() as session:
            replayed = await session.scalar(
                select(PaymentRequest.id).where(
                    PaymentRequest.org_id == member.organization_id,
                    PaymentRequest.idempotency_key == idempotency_key,
                )
            )
            asset = await session.get(Asset, payload.asset_id)
        if replayed is None:
            fx = await _capture_fiat_reference(
                request,
                currency=payload.fiat_currency,
                fiat_amount_minor_units=fiat_amount_minor_units,
                max_stablecoin_amount=_amount(payload.amount, asset.decimals) if asset else 0,
                asset=asset,
            )
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
                fx_reference_quote, fx_tolerance_bps = fx
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
                    fiat_amount_minor_units=fiat_amount_minor_units,
                    fiat_currency=payload.fiat_currency,
                    fx_reference_quote=fx_reference_quote,
                    fx_tolerance_bps=fx_tolerance_bps,
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
    expected_version = _expected_version(if_match)
    fields = payload.model_dump(exclude_unset=True)
    if "fiat_amount_minor_units" in fields:
        fields["fiat_amount_minor_units"] = _fiat_amount(fields["fiat_amount_minor_units"])
    factory = _sessions(request)
    scope: tuple[uuid.UUID, bytes] | None = None
    # Quote before taking the row lock so the external call never holds DB locks. The version
    # check under the lock guarantees this unlocked read is still the row being edited.
    fx: tuple[dict[str, object] | None, int | None] | None = None
    async with factory() as session:
        current = await session.scalar(
            select(PaymentRequest).where(
                PaymentRequest.id == request_id, PaymentRequest.org_id == member.organization_id
            )
        )
        asset = (
            await session.get(Asset, fields.get("asset_id", current.asset_id)) if current else None
        )
    if (
        current is not None
        and asset is not None
        and current.amount is not None
        and current.version == expected_version
        and current.status in {RequestStatus.DRAFT.value, RequestStatus.APPROVED.value}
    ):
        fiat_amount, fiat_currency = _edit_fiat_fields(current, fields)
        if fiat_amount is not None and _fiat_recapture_needed(
            current, fields, fiat_amount, fiat_currency, asset
        ):
            fx = await _capture_fiat_reference(
                request,
                currency=fiat_currency,
                fiat_amount_minor_units=fiat_amount,
                max_stablecoin_amount=(
                    _amount(str(fields["amount"]), asset.decimals)
                    if "amount" in fields
                    else int(current.amount)
                ),
                asset=asset,
            )
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
            fiat_amount_minor_units, fiat_currency = _edit_fiat_fields(row, fields)
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
                if fiat_amount_minor_units is None:
                    fx_reference_quote, fx_tolerance_bps = None, None
                elif not _fiat_recapture_needed(
                    row, fields, fiat_amount_minor_units, fiat_currency, asset
                ):
                    fx_reference_quote, fx_tolerance_bps = (
                        row.fx_reference_quote,
                        row.fx_tolerance_bps,
                    )
                else:
                    # Fallback if the unlocked prefetch was skipped or priced something else.
                    fx_reference_quote, fx_tolerance_bps = fx or await _capture_fiat_reference(
                        request,
                        currency=fiat_currency,
                        fiat_amount_minor_units=fiat_amount_minor_units,
                        max_stablecoin_amount=amount,
                        asset=asset,
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
                row.fiat_amount_minor_units = fiat_amount_minor_units
                row.fiat_currency = fiat_currency
                row.fx_reference_quote = fx_reference_quote
                row.fx_tolerance_bps = fx_tolerance_bps
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


class _AuditAppender:
    async def append(self, *, session: AsyncSession, entry: AuditEntry) -> None:
        await write_audit(
            session,
            org_id=entry.organization_id,
            actor=AuditActor(AuditActorType(entry.actor_type.value), entry.actor_id),
            action=entry.action,
            entity=AuditEntity(entry.entity_type, entry.entity_id),
            data=entry.data,
        )


async def _transition(
    request: Request,
    response: Response,
    *,
    member: MemberAccess,
    request_id: uuid.UUID,
    action: TransitionAction,
    target: RequestStatus,
    expected_version: int,
    reason: str,
) -> dict[str, object]:
    """Run a user transition through the state machine and return the refreshed request."""
    factory = _sessions(request)
    machine = RequestStateMachine(
        factory, audit=_AuditAppender(), pay_operation_guard=SqlAlchemyPayOperationGuard()
    )
    actor = TransitionActor(
        StatusEventActorType.USER,
        action,
        member.user_id,
        frozenset(OrganizationRole(role) for role in member.roles),
    )
    try:
        await machine.transition(
            organization_id=member.organization_id,
            request_id=request_id,
            target=target,
            actor=actor,
            expected_version=expected_version,
            reason=reason,
        )
    except RequestTransitionError as error:
        raise _fail(
            error.status_code, error.code, "Request transition rejected", error.detail
        ) from None
    async with factory() as session:
        row = await session.scalar(select(PaymentRequest).where(PaymentRequest.id == request_id))
        assert row is not None
        result, version = _serialize(row), row.version
    response.headers["ETag"] = f'"{version}"'
    return {"request": result}


@router.post("/{request_id}/submit", openapi_extra={"x-organization-scoped": True})
async def submit_request(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    member: MemberAccess = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    expected_version = _expected_version(if_match)
    # The guards read the row at expected_version; the transition re-checks that version
    # under the row lock, so an edit between the two is rejected with 412.
    async with _sessions(request)() as session, session.begin():
        row = await session.scalar(
            select(PaymentRequest).where(
                PaymentRequest.id == request_id, PaymentRequest.org_id == member.organization_id
            )
        )
        if row is None:
            raise _not_found()
        if row.version == expected_version and row.status == RequestStatus.DRAFT.value:
            await _assert_submittable(session, row)
    return await _transition(
        request,
        response,
        member=member,
        request_id=request_id,
        action=TransitionAction.SUBMIT,
        target=RequestStatus.AWAITING_APPROVAL,
        expected_version=expected_version,
        reason="request submitted for approval",
    )


async def _assert_submittable(session: AsyncSession, row: PaymentRequest) -> None:
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
        raise _fail(
            409,
            "REQUEST_FIELDS_INCOMPLETE",
            "Request fields are incomplete",
            "Complete all required invoice fields before submitting this request.",
        )
    await _bound_fields(
        session,
        organization_id=row.org_id,
        treasury_id=row.treasury_id,
        vendor_id=row.vendor_id,
        payee_id=row.payee_id,
        asset_id=row.asset_id,
        paying_wallet_id=row.paying_wallet_id,
    )


@router.post("/{request_id}/withdraw", openapi_extra={"x-organization-scoped": True})
async def withdraw_request(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    member: MemberAccess = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    return await _transition(
        request,
        response,
        member=member,
        request_id=request_id,
        action=TransitionAction.WITHDRAW,
        target=RequestStatus.DRAFT,
        expected_version=_expected_version(if_match),
        reason="request withdrawn by operator",
    )


@router.post("/{request_id}/request-changes", openapi_extra={"x-organization-scoped": True})
async def request_changes(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: RequestReason,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    member: MemberAccess = Depends(_require_approver),  # noqa: B008
) -> dict[str, object]:
    return await _transition(
        request,
        response,
        member=member,
        request_id=request_id,
        action=TransitionAction.REQUEST_CHANGES,
        target=RequestStatus.DRAFT,
        expected_version=_expected_version(if_match),
        reason=payload.reason,
    )


@router.post("/{request_id}/flags/{flag_id}/ack", openapi_extra={"x-organization-scoped": True})
async def acknowledge_flag(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    flag_id: uuid.UUID,
    payload: FlagAcknowledgment,
    request: Request,
    member: MemberAccess = Depends(_require_approver),  # noqa: B008
) -> dict[str, object]:
    note = payload.note.strip()
    if len(note) < 10:
        raise _fail(422, "ACK_NOTE_TOO_SHORT", "Note too short", "Provide at least 10 characters.")
    async with _sessions(request)() as session, session.begin():
        row = await session.scalar(
            select(PaymentRequest)
            .where(PaymentRequest.id == request_id, PaymentRequest.org_id == member.organization_id)
            .with_for_update()
        )
        if row is None:
            raise _not_found()
        if row.status != RequestStatus.AWAITING_APPROVAL.value:
            raise _fail(
                409,
                "NOT_AWAITING_APPROVAL",
                "Request is not awaiting approval",
                "Flags can only be acknowledged while the request awaits approval.",
            )
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
        solo_mode = bool(
            await session.scalar(
                select(Organization.solo_mode).where(Organization.id == member.organization_id)
            )
        )
        # Same rule as the approve transition: the creator never acknowledges; the last
        # editor may only in solo mode.
        if member.user_id == row.created_by or (
            not solo_mode and member.user_id == row.last_edited_by
        ):
            raise maker_checker_conflict()
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
            MandateVersion.status == MandateVersionStatus.ACTIVE,
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
    if isinstance(approval_max_age_value, bool) or not isinstance(approval_max_age_value, int):
        raise _fail(
            409,
            "APPROVAL_UNAVAILABLE",
            "Approval unavailable",
            "The active mandate has an invalid approvalMaxAge setting.",
        )
    approval_max_age = approval_max_age_value
    if row.amount is None or row.due_at is None:  # unreachable: drafts cannot be in review
        raise RuntimeError("Approval inputs are incomplete")
    terms = confirmed_payment_terms(row)
    early_amount, early_pay_by = (_early_option(terms, int(row.amount)) if terms else None) or (
        0,
        0,
    )
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
    session: AsyncSession, organization_id: uuid.UUID, member: MemberAccess, row: PaymentRequest
) -> bool:
    """Reject makers unless the org is in solo mode; return the org's solo-mode flag."""
    solo_mode = bool(
        await session.scalar(
            select(Organization.solo_mode).where(Organization.id == organization_id)
        )
    )
    if not solo_mode and member.user_id in {row.created_by, row.last_edited_by}:
        raise maker_checker_conflict()
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
    member: MemberAccess = Depends(_require_approver),  # noqa: B008
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
    member: MemberAccess = Depends(_require_approver),  # noqa: B008
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
            await write_audit(
                session,
                org_id=organization_id,
                actor=AuditActor(AuditActorType.USER, member.user_id),
                action=TransitionAction.APPROVE.value,
                entity=AuditEntity("payment_request", row.id),
                data={"from": previous_status, "to": row.status, "soloMode": solo_mode},
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
            "uq_approvals_valid_request_revision_address",
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


@router.post("/{request_id}/reject", openapi_extra={"x-organization-scoped": True})
async def reject_request(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: RequestReason,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    member: MemberAccess = Depends(_require_approver),  # noqa: B008
) -> dict[str, object]:
    return await _transition(
        request,
        response,
        member=member,
        request_id=request_id,
        action=TransitionAction.REJECT,
        target=RequestStatus.REJECTED,
        expected_version=_expected_version(if_match),
        reason=payload.reason,
    )


@router.post("/{request_id}/cancel", openapi_extra={"x-organization-scoped": True})
async def cancel_request(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: RequestReason,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    member: MemberAccess = Depends(_require_canceller),  # noqa: B008
) -> dict[str, object]:
    return await _transition(
        request,
        response,
        member=member,
        request_id=request_id,
        action=TransitionAction.CANCEL,
        target=RequestStatus.CANCELLED,
        expected_version=_expected_version(if_match),
        reason=payload.reason,
    )


@router.post("/{request_id}/renew", openapi_extra={"x-organization-scoped": True})
async def renew_request(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: RenewRequest,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    member: MemberAccess = Depends(_require_renewer),  # noqa: B008
) -> dict[str, object]:
    expected_version = _expected_version(if_match)
    async with _sessions(request)() as session, session.begin():
        row = await session.scalar(
            select(PaymentRequest)
            .where(PaymentRequest.id == request_id, PaymentRequest.org_id == organization_id)
            .with_for_update()
        )
        if row is None:
            raise _not_found()
        if row.version != expected_version:
            raise _fail(412, "PRECONDITION_FAILED", "Request changed", "Reload and try again.")
        try:
            validate_transition(
                source=row.status,
                target=RequestStatus.DRAFT,
                actor=TransitionActor(
                    StatusEventActorType.USER,
                    TransitionAction.RENEW,
                    member.user_id,
                    frozenset(role for role in OrganizationRole if role.value in member.roles),
                ),
                created_by=row.created_by,
                last_edited_by=row.last_edited_by,
            )
        except RequestTransitionError as error:
            raise _fail(
                error.status_code, error.code, "Request cannot be renewed", error.detail
            ) from error
        today = datetime.now(UTC).date()
        if payload.due_date is not None and payload.due_date < today:
            raise _fail(
                422,
                "DUE_DATE_IN_PAST",
                "Due date invalid",
                "The renewed due date cannot be in the past.",
            )
        row.current_revision += 1
        row.due_at = payload.due_date or max(row.due_at or today, today + timedelta(days=1))
        vendor_ref, asset_address = (
            await session.execute(
                select(Vendor.normalized_ref, Asset.address)
                .join(Asset, Asset.id == row.asset_id)
                .where(Vendor.id == row.vendor_id)
            )
        ).one()
        # due_at is part of invoice_hash; the active-duplicate check also revives the fingerprint.
        _hashes(row, vendor_ref, asset_address or b"")
        await assert_no_active_duplicate(session, row)
        # Flip the status only after the check: Draft is active, so autoflush would hit the index.
        previous = row.status
        row.status = RequestStatus.DRAFT.value
        row.last_edited_by = member.user_id
        row.terms_hash = None
        row.terms_confirmed_by = None
        row.terms_confirmed_at = None
        session.add(
            RequestRevision(
                id=uuid7(),
                request_id=row.id,
                revision=row.current_revision,
                snapshot=_snapshot(row),
                edited_by=member.user_id,
                reason="renewed after expiry",
            )
        )
        session.add(
            RequestStatusEvent(
                id=uuid7(),
                request_id=row.id,
                from_status=previous,
                to_status=row.status,
                actor_type=StatusEventActorType.USER.value,
                actor_id=member.user_id,
                reason="request renewed after expiry",
            )
        )
        await session.flush()
        await session.refresh(row)
        result, version = _serialize(row), row.version
    response.headers["ETag"] = f'"{version}"'
    return {"request": result}


@router.get("/{request_id}/cancel-tx", openapi_extra={"x-organization-scoped": True})
async def get_cancel_transaction(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_cancel_tx_actor),  # noqa: B008
) -> dict[str, object]:
    # The repository has no deployed module ABI/event indexer or Safe governance builder yet.
    # Never return calldata that could be mistaken for a confirmed supported contract call.
    async with _sessions(request)() as session:
        row = await session.scalar(
            select(PaymentRequest).where(
                PaymentRequest.id == request_id, PaymentRequest.org_id == organization_id
            )
        )
        if row is None:
            raise _not_found()
        if row.cancel_onchain != "Pending":
            raise _fail(
                409,
                "CANCEL_NOT_NEEDED",
                "On-chain cancel not needed",
                "This request has no pending on-chain cancellation.",
            )
        if row.onchain_request_id is None:
            raise _fail(
                503,
                "ONCHAIN_CANCEL_UNAVAILABLE",
                "On-chain cancellation unavailable",
                "The request has no on-chain identifier; cancellation remains Pending.",
            )
    raise _fail(
        503,
        "ONCHAIN_CANCEL_UNAVAILABLE",
        "On-chain cancellation unavailable",
        "Contract support and the Safe transaction builder are not configured; cancellation remains Pending.",
    )
