from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base
from treasurypilot_api.identity.models import uuid7


class RequestStatus(StrEnum):
    DRAFT = "Draft"
    AWAITING_APPROVAL = "AwaitingApproval"
    APPROVED = "Approved"
    SCHEDULED = "Scheduled"
    PLANNING = "Planning"
    AWAITING_AUTHORITY = "AwaitingAuthority"
    PREPARING = "Preparing"
    PAYING = "Paying"
    PAID = "Paid"
    NEEDS_REVIEW = "NeedsReview"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"
    EXPIRED = "Expired"


class InvoiceApiKey(Base):
    __tablename__ = "invoice_api_keys"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 120", name="ck_invoice_api_keys_name"),
        CheckConstraint("octet_length(token_hash) = 32", name="ck_invoice_api_keys_hash"),
        CheckConstraint("cardinality(scopes) > 0", name="ck_invoice_api_keys_scopes"),
        CheckConstraint(
            "array_position(scopes, NULL) IS NULL", name="ck_invoice_api_keys_scopes_no_null"
        ),
        Index("ix_invoice_api_keys_org", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvoiceInboundEmail(Base):
    """Organization's private address for authenticated invoice email webhooks."""

    __tablename__ = "invoice_inbound_emails"
    __table_args__ = (
        CheckConstraint(
            "local_part ~ '^[a-f0-9]{48}$'", name="ck_invoice_inbound_emails_local_part"
        ),
        ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_invoice_inbound_emails_treasury_org",
            ondelete="CASCADE",
        ),
        Index("uq_invoice_inbound_emails_local_part", "local_part", unique=True),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    local_part: Mapped[str] = mapped_column(String(48), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sender_allowlist: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class InvoiceInboundQuarantine(Base):
    """A signed email held back from draft creation. Only metadata is kept, never content."""

    __tablename__ = "invoice_inbound_quarantine"
    __table_args__ = (
        UniqueConstraint("org_id", "message_digest", name="uq_invoice_inbound_quarantine_message"),
        CheckConstraint(
            "reason IN ('SENDER_NOT_ALLOWLISTED', 'SENDER_UNAUTHENTICATED')",
            name="ck_invoice_inbound_quarantine_reason",
        ),
        Index("ix_invoice_inbound_quarantine_org_received", "org_id", "received_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    message_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    # Untrusted, sanitised and length-capped; display only.
    sender: Mapped[str] = mapped_column(String(320), nullable=False)
    sender_domain: Mapped[str | None] = mapped_column(String(253))
    attachment_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RequestSource(StrEnum):
    MANUAL = "MANUAL"
    UPLOAD = "UPLOAD"
    CSV = "CSV"
    RECURRING = "RECURRING"


class ExtractionStatus(StrEnum):
    EXTRACTING = "Extracting"
    EXTRACTED = "Extracted"
    MANUAL_ENTRY = "ManualEntry"


class CancelOnchainStatus(StrEnum):
    NOT_NEEDED = "NotNeeded"
    PENDING = "Pending"
    CONFIRMED = "Confirmed"


class RequestFlagSeverity(StrEnum):
    LOW = "LOW"
    HIGH = "HIGH"


class RequestFlagSource(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    AI = "AI"


class RequestFlagStatus(StrEnum):
    OPEN = "Open"
    ACKNOWLEDGED = "Acknowledged"
    SUPERSEDED = "Superseded"


class ApprovalStatus(StrEnum):
    VALID = "Valid"
    INVALIDATED = "Invalidated"
    EXPIRED = "Expired"
    CANCELLED = "Cancelled"


class StatusEventActorType(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"


def _values(enum: type[StrEnum]) -> str:
    return ", ".join(f"'{value.value}'" for value in enum)


_REQUEST_STATUSES = _values(RequestStatus)
_REQUEST_SOURCES = _values(RequestSource)
_CANCEL_STATUSES = _values(CancelOnchainStatus)
_EXTRACTION_STATUSES = _values(ExtractionStatus)
_FLAG_SEVERITIES = _values(RequestFlagSeverity)
_FLAG_SOURCES = _values(RequestFlagSource)
_FLAG_STATUSES = _values(RequestFlagStatus)
_APPROVAL_STATUSES = _values(ApprovalStatus)
_EVENT_ACTOR_TYPES = _values(StatusEventActorType)
TERMINAL_REQUEST_STATUSES = (RequestStatus.REJECTED, RequestStatus.CANCELLED, RequestStatus.EXPIRED)
_TERMINAL_REQUEST_STATUSES = ", ".join(f"'{status.value}'" for status in TERMINAL_REQUEST_STATUSES)


class PaymentRequest(Base):
    __tablename__ = "payment_requests"
    __table_args__ = (
        CheckConstraint(f"status IN ({_REQUEST_STATUSES})", name="ck_payment_requests_status"),
        CheckConstraint(f"source IN ({_REQUEST_SOURCES})", name="ck_payment_requests_source"),
        CheckConstraint(
            f"cancel_onchain IN ({_CANCEL_STATUSES})", name="ck_payment_requests_cancel_status"
        ),
        CheckConstraint("amount > 0", name="ck_payment_requests_amount_positive"),
        CheckConstraint(
            "(fiat_amount_minor_units IS NULL AND fiat_currency IS NULL AND "
            "fx_reference_quote IS NULL AND fx_tolerance_bps IS NULL) OR "
            "(fiat_amount_minor_units IS NOT NULL AND fiat_amount_minor_units > 0 AND "
            "fiat_currency IS NOT NULL AND fiat_currency ~ '^[A-Z]{3}$' AND "
            "fx_reference_quote IS NOT NULL AND jsonb_typeof(fx_reference_quote) = 'object' AND "
            "fx_tolerance_bps IS NOT NULL AND fx_tolerance_bps BETWEEN 0 AND 10000)",
            name="ck_payment_requests_fiat_fx_pair",
        ),
        CheckConstraint("due_at >= issue_date", name="ck_payment_requests_due_after_issue"),
        CheckConstraint(
            f"fingerprint IS NOT NULL OR status IN ('Draft', {_TERMINAL_REQUEST_STATUSES})",
            name="ck_payment_requests_fingerprint_set",
        ),
        CheckConstraint("current_revision > 0", name="ck_payment_requests_revision_positive"),
        CheckConstraint("version > 0", name="ck_payment_requests_version"),
        CheckConstraint(
            "fingerprint IS NULL OR octet_length(fingerprint) = 32",
            name="ck_payment_requests_fingerprint_length",
        ),
        CheckConstraint(
            "invoice_hash IS NULL OR octet_length(invoice_hash) = 32",
            name="ck_payment_requests_invoice_hash_length",
        ),
        CheckConstraint(
            "onchain_request_id IS NULL OR octet_length(onchain_request_id) = 32",
            name="ck_payment_requests_onchain_id_length",
        ),
        CheckConstraint(
            "terms_hash IS NULL OR octet_length(terms_hash) = 32",
            name="ck_payment_requests_terms_hash_length",
        ),
        CheckConstraint(
            "cancel_tx_hash IS NULL OR octet_length(cancel_tx_hash) = 32",
            name="ck_payment_requests_cancel_tx_hash_length",
        ),
        CheckConstraint(
            "terms_confirmed_by IS NULL OR terms_confirmed_at IS NOT NULL",
            name="ck_payment_requests_terms_confirmation_pair",
        ),
        CheckConstraint(
            f"extraction_status IS NULL OR extraction_status IN ({_EXTRACTION_STATUSES})",
            name="ck_payment_requests_extraction_status",
        ),
        CheckConstraint(
            "extraction_confirmed_by IS NULL OR extraction_confirmed_at IS NOT NULL",
            name="ck_payment_requests_extraction_confirmation_pair",
        ),
        CheckConstraint(
            "status = 'Draft' OR (vendor_id IS NOT NULL AND payee_id IS NOT NULL AND "
            "invoice_no IS NOT NULL AND issue_date IS NOT NULL AND due_at IS NOT NULL "
            "AND amount IS NOT NULL)",
            name="ck_payment_requests_complete_before_transition",
        ),
        CheckConstraint(
            "source != 'UPLOAD' OR status = 'Draft' OR extraction_confirmed_by IS NOT NULL",
            name="ck_upload_request_confirmed_before_transition",
        ),
        ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_payment_requests_treasury_org",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["treasury_id", "chain_id"],
            ["treasuries.id", "treasuries.chain_id"],
            name="fk_payment_requests_treasury_chain",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["payee_id", "treasury_id", "vendor_id"],
            ["payees.id", "payees.treasury_id", "payees.vendor_id"],
            name="fk_payment_requests_payee_treasury_vendor",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["vendor_id", "org_id"],
            ["vendors.id", "vendors.org_id"],
            name="fk_payment_requests_vendor_org",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["asset_id", "chain_id"],
            ["assets.id", "assets.chain_id"],
            name="fk_payment_requests_asset_chain",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["paying_wallet_id", "treasury_id"],
            ["treasury_wallets.id", "treasury_wallets.treasury_id"],
            name="fk_payment_requests_paying_wallet_treasury",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["terms_confirmed_by"], ["users.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["extraction_confirmed_by"], ["users.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["last_edited_by"], ["users.id"], ondelete="SET NULL"),
        UniqueConstraint("id", "treasury_id", name="uq_payment_requests_id_treasury"),
        UniqueConstraint("org_id", "idempotency_key", name="uq_payment_requests_idempotency_key"),
        CheckConstraint(
            "(idempotency_key IS NULL AND idempotency_payload_hash IS NULL) OR "
            "(idempotency_key IS NOT NULL AND octet_length(idempotency_payload_hash) = 32)",
            name="ck_payment_requests_idempotency_hash",
        ),
        Index("ix_payment_requests_org_status", "org_id", "status"),
        Index("ix_payment_requests_treasury_due", "treasury_id", "due_at"),
        Index("ix_payment_requests_vendor_amount_issue_date", "vendor_id", "amount", "issue_date"),
        Index(
            "uq_payment_requests_active_fingerprint",
            "treasury_id",
            "fingerprint",
            unique=True,
            postgresql_where=text(
                f"status NOT IN ({_TERMINAL_REQUEST_STATUSES}) AND fingerprint IS NOT NULL"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    invoice_no: Mapped[str | None] = mapped_column(String(200))
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_at: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[int | None] = mapped_column(Numeric(78, 0))
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # For fiat requests, amount is the approved maximum in stablecoin base units.
    fiat_amount_minor_units: Mapped[int | None] = mapped_column(Numeric(78, 0))
    fiat_currency: Mapped[str | None] = mapped_column(String(3))
    fx_reference_quote: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    fx_tolerance_bps: Mapped[int | None] = mapped_column(SmallInteger)
    paying_wallet_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    terms: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    terms_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    terms_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    terms_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fingerprint: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    invoice_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    onchain_request_id: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    source: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=RequestSource.MANUAL,
        server_default=RequestSource.MANUAL,
    )
    # Set only on upload drafts: Extracting -> Extracted | ManualEntry (AGT-004).
    extraction_status: Mapped[str | None] = mapped_column(String(16))
    extraction_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    extraction_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=RequestStatus.DRAFT, server_default=RequestStatus.DRAFT
    )
    current_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_edited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_via_api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoice_api_keys.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    cost_center: Mapped[str | None] = mapped_column(String(120))
    cancel_onchain: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=CancelOnchainStatus.NOT_NEEDED,
        server_default=CancelOnchainStatus.NOT_NEEDED,
    )
    cancel_tx_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    idempotency_payload_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}


class RecurringScheduleStatus(StrEnum):
    ACTIVE = "Active"
    PAUSED = "Paused"
    COMPLETED = "Completed"


class RecurringPeriodStatus(StrEnum):
    GENERATED = "Generated"
    SKIPPED = "Skipped"


class RecurringPaymentSchedule(Base):
    __tablename__ = "recurring_payment_schedules"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(invoice_no_template)) > 0", name="ck_recurring_invoice_template"
        ),
        CheckConstraint("amount > 0", name="ck_recurring_amount_positive"),
        CheckConstraint("interval > 0", name="ck_recurring_interval_positive"),
        CheckConstraint("due_days_after_issue BETWEEN 0 AND 365", name="ck_recurring_due_offset"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_recurring_end_date"),
        CheckConstraint("version > 0", name="ck_recurring_version"),
        CheckConstraint("period_index >= 0", name="ck_recurring_period_index"),
        CheckConstraint(
            "cadence IN ('WEEKLY', 'MONTHLY', 'QUARTERLY', 'YEARLY')", name="ck_recurring_cadence"
        ),
        CheckConstraint("status IN ('Active', 'Paused', 'Completed')", name="ck_recurring_status"),
        ForeignKeyConstraint(
            ["treasury_id", "org_id"], ["treasuries.id", "treasuries.org_id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["treasury_id", "chain_id"],
            ["treasuries.id", "treasuries.chain_id"],
            name="fk_recurring_schedule_treasury_chain",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["vendor_id", "org_id"],
            ["vendors.id", "vendors.org_id"],
            name="fk_recurring_schedule_vendor_org",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["payee_id", "treasury_id", "vendor_id"],
            ["payees.id", "payees.treasury_id", "payees.vendor_id"],
            name="fk_recurring_schedule_payee_vendor",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["asset_id", "chain_id"],
            ["assets.id", "assets.chain_id"],
            name="fk_recurring_schedule_asset_chain",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["paying_wallet_id", "treasury_id"],
            ["treasury_wallets.id", "treasury_wallets.treasury_id"],
            name="fk_recurring_schedule_wallet_treasury",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["last_edited_by"], ["users.id"], ondelete="SET NULL"),
        Index("ix_recurring_schedules_due", "status", "next_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    paying_wallet_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    invoice_no_template: Mapped[str] = mapped_column(String(180), nullable=False)
    amount: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    terms: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    note: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    cost_center: Mapped[str | None] = mapped_column(String(120))
    cadence: Mapped[str] = mapped_column(String(12), nullable=False)
    interval: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    period_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    next_period: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    due_days_after_issue: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="Active", server_default="Active"
    )
    pause_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_edited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RecurringPaymentPeriod(Base):
    __tablename__ = "recurring_payment_periods"
    __table_args__ = (
        UniqueConstraint("schedule_id", "period_date", name="uq_recurring_period_schedule_date"),
        UniqueConstraint("request_id", name="uq_recurring_period_request"),
        CheckConstraint(
            "status IN ('Generated', 'Skipped', 'Failed')", name="ck_recurring_period_status"
        ),
        CheckConstraint(
            "(status = 'Generated' AND request_id IS NOT NULL AND skipped_by IS NULL AND skipped_at IS NULL) OR "
            "(status = 'Skipped' AND request_id IS NULL AND skipped_by IS NOT NULL AND skipped_at IS NOT NULL) OR "
            "(status = 'Failed' AND request_id IS NULL AND skipped_by IS NULL AND skipped_at IS NULL AND reason IS NOT NULL)",
            name="ck_recurring_period_outcome",
        ),
        ForeignKeyConstraint(
            ["schedule_id"], ["recurring_payment_schedules.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["skipped_by"], ["users.id"], ondelete="RESTRICT"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period_date: Mapped[date] = mapped_column(Date, nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    skipped_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RequestRevision(Base):
    __tablename__ = "request_revisions"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_request_revisions_revision_positive"),
        CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="ck_request_revisions_snapshot"),
        ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        # Users are soft-deleted; SET NULL would be rejected by the append-only trigger.
        ForeignKeyConstraint(["edited_by"], ["users.id"], ondelete="RESTRICT"),
        UniqueConstraint("request_id", "revision", name="uq_request_revisions_request_revision"),
        Index("ix_request_revisions_request_at", "request_id", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    edited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)


class RequestDocument(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("length(btrim(storage_key)) > 0", name="ck_documents_storage_key"),
        CheckConstraint("octet_length(sha256) = 32", name="ck_documents_sha256_length"),
        CheckConstraint("length(btrim(mime)) > 0", name="ck_documents_mime"),
        CheckConstraint("size > 0", name="ck_documents_size_positive"),
        CheckConstraint("pages IS NULL OR pages > 0", name="ck_documents_pages_positive"),
        ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        UniqueConstraint("storage_key", name="uq_documents_storage_key"),
        Index("ix_documents_request", "request_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pages: Mapped[int | None] = mapped_column(SmallInteger)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RequestFlag(Base):
    __tablename__ = "flags"
    __table_args__ = (
        CheckConstraint(f"severity IN ({_FLAG_SEVERITIES})", name="ck_flags_severity"),
        CheckConstraint(f"source IN ({_FLAG_SOURCES})", name="ck_flags_source"),
        CheckConstraint(f"status IN ({_FLAG_STATUSES})", name="ck_flags_status"),
        CheckConstraint("revision > 0", name="ck_flags_revision_positive"),
        CheckConstraint("jsonb_typeof(evidence) = 'object'", name="ck_flags_evidence_object"),
        CheckConstraint(
            "status != 'Acknowledged' "
            "OR (acknowledged_by IS NOT NULL AND acknowledged_at IS NOT NULL)",
            name="ck_flags_acknowledgement_actor",
        ),
        ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["request_id", "revision"],
            ["request_revisions.request_id", "request_revisions.revision"],
            name="fk_flags_request_revision",
            ondelete="RESTRICT",
        ),
        # ck_flags_acknowledgement_actor needs the actor, so it cannot be nulled.
        ForeignKeyConstraint(["acknowledged_by"], ["users.id"], ondelete="RESTRICT"),
        Index("ix_flags_request_revision_status", "request_id", "revision", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=RequestFlagStatus.OPEN,
        server_default=RequestFlagStatus.OPEN,
    )
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ack_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PaymentApproval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_approvals_revision_positive"),
        CheckConstraint("octet_length(approver_address) = 20", name="ck_approvals_address_length"),
        CheckConstraint("jsonb_typeof(typed_data) = 'object'", name="ck_approvals_typed_data"),
        CheckConstraint(f"status IN ({_APPROVAL_STATUSES})", name="ck_approvals_status"),
        CheckConstraint("length(signature) > 0", name="ck_approvals_signature"),
        CheckConstraint(
            "idempotency_key_hash IS NULL OR octet_length(idempotency_key_hash) = 32",
            name="ck_approvals_idempotency_key_hash",
        ),
        ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["request_id", "revision"],
            ["request_revisions.request_id", "request_revisions.revision"],
            name="fk_approvals_request_revision",
            ondelete="RESTRICT",
        ),
        # Users are soft-deleted; SET NULL would be rejected by the immutability trigger.
        ForeignKeyConstraint(["approver_user_id"], ["users.id"], ondelete="RESTRICT"),
        # Only one Valid approval per approver and revision; an ended one never revives,
        # so the approver signs again as a new row.
        Index(
            "uq_approvals_valid_request_revision_address",
            "request_id",
            "revision",
            "approver_address",
            unique=True,
            postgresql_where=text("status = 'Valid'"),
        ),
        UniqueConstraint(
            "request_id", "idempotency_key_hash", name="uq_approvals_request_idempotency_key"
        ),
        Index("ix_approvals_request_revision", "request_id", "revision"),
        Index(
            "ix_approvals_valid_expiry",
            "expires_at",
            postgresql_where=text("status = 'Valid'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approver_address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    idempotency_key_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    typed_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    signature: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    acknowledged_flag_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    solo_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ApprovalStatus.VALID,
        server_default=ApprovalStatus.VALID,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CsvImport(Base):
    __tablename__ = "csv_imports"
    __table_args__ = (
        CheckConstraint("octet_length(file_sha256) = 32", name="ck_csv_imports_sha256_length"),
        CheckConstraint("rows_total >= 0", name="ck_csv_imports_rows_total"),
        CheckConstraint(
            "rows_created >= 0 AND rows_created <= rows_total", name="ck_csv_imports_rows_created"
        ),
        CheckConstraint("jsonb_typeof(errors) = 'array'", name="ck_csv_imports_errors_array"),
        ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_csv_imports_treasury_org",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        Index("ix_csv_imports_org_created", "org_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    file_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_created: Mapped[int] = mapped_column(Integer, nullable=False)
    errors: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RequestStatusEvent(Base):
    __tablename__ = "request_status_events"
    __table_args__ = (
        CheckConstraint(f'"to" IN ({_REQUEST_STATUSES})', name="ck_request_status_events_to"),
        CheckConstraint(
            f'"from" IS NULL OR "from" IN ({_REQUEST_STATUSES})',
            name="ck_request_status_events_from",
        ),
        CheckConstraint('"from" <> "to"', name="ck_request_status_events_changed"),
        CheckConstraint(
            f"actor_type IN ({_EVENT_ACTOR_TYPES})", name="ck_request_status_events_actor_type"
        ),
        ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        # Users are soft-deleted; SET NULL would be rejected by the append-only trigger.
        ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        Index("ix_request_status_events_request_at", "request_id", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_status: Mapped[str | None] = mapped_column("from", String(24))
    to_status: Mapped[str] = mapped_column("to", String(24), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
