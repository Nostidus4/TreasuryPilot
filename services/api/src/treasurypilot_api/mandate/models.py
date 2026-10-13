from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base
from treasurypilot_api.identity.models import uuid7


class MandateVersionStatus(StrEnum):
    DRAFT = "Draft"
    DISCARDED = "Discarded"
    PENDING_ACTIVATION = "PendingActivation"
    ACTIVE = "Active"
    SUPERSEDED = "Superseded"
    EXPIRED = "Expired"
    REVOKED = "Revoked"
    DISCREPANCY = "Discrepancy"


class GovernanceTxStatus(StrEnum):
    COLLECTING = "Collecting"
    READY = "Ready"
    SUBMITTED = "Submitted"
    EXECUTED = "Executed"
    FAILED = "Failed"
    SUPERSEDED = "Superseded"
    CANCELLED = "Cancelled"


class PayeeStatus(StrEnum):
    PROPOSED = "Proposed"
    SCREENING = "Screening"
    SCREENING_FAILED = "ScreeningFailed"
    AWAITING_OWNER = "AwaitingOwner"
    COOLING = "Cooling"
    ACTIVE = "Active"
    DEACTIVATED = "Deactivated"


class OobMethod(StrEnum):
    PHONE = "PHONE"
    IN_PERSON = "IN_PERSON"
    SIGNED_LETTER = "SIGNED_LETTER"
    OTHER = "OTHER"


class ScreeningResult(StrEnum):
    CLEAR = "CLEAR"
    HIT = "HIT"
    ERROR = "ERROR"


class ExceptionStatus(StrEnum):
    REQUESTED = "Requested"
    PROPOSED = "Proposed"
    GRANTED = "Granted"
    CONSUMED = "Consumed"
    EXPIRED = "Expired"
    INVALIDATED = "Invalidated"
    REJECTED = "Rejected"
    REVOKED = "Revoked"


class FeePreset(StrEnum):
    ECONOMY = "ECONOMY"
    NORMAL = "NORMAL"
    FAST = "FAST"


class BackendPauseStatus(StrEnum):
    NOT_REQUESTED = "NotRequested"
    REQUESTED = "Requested"
    EFFECTIVE = "Effective"


_MANDATE_STATUSES = ", ".join(f"'{status.value}'" for status in MandateVersionStatus)
_PAYEE_STATUSES = ", ".join(f"'{status.value}'" for status in PayeeStatus)
_GOVERNANCE_STATUSES = ", ".join(f"'{status.value}'" for status in GovernanceTxStatus)
_SCREENING_RESULTS = ", ".join(f"'{result.value}'" for result in ScreeningResult)
_EXCEPTION_STATUSES = ", ".join(f"'{status.value}'" for status in ExceptionStatus)
_OOB_METHODS = ", ".join(f"'{method.value}'" for method in OobMethod)
_OPEN_EXCEPTION_STATUSES = ", ".join(
    f"'{status.value}'"
    for status in (ExceptionStatus.REQUESTED, ExceptionStatus.PROPOSED, ExceptionStatus.GRANTED)
)
_FEE_PRESETS = ", ".join(f"'{preset.value}'" for preset in FeePreset)
_BACKEND_PAUSE_STATUSES = ", ".join(f"'{status.value}'" for status in BackendPauseStatus)


class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("org_id", "normalized_ref", name="uq_vendors_org_normalized_ref"),
        UniqueConstraint("id", "org_id", name="uq_vendors_id_org"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_vendors_name"),
        CheckConstraint("length(btrim(normalized_ref)) > 0", name="ck_vendors_normalized_ref"),
        Index("ix_vendors_org_id", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_ref: Mapped[str] = mapped_column(String(320), nullable=False)
    # These byte fields contain application-encrypted confidential identifiers/contact data.
    tax_id: Mapped[bytes | None] = mapped_column(LargeBinary())
    contact: Mapped[bytes | None] = mapped_column(LargeBinary())
    notes: Mapped[str | None] = mapped_column(Text())
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class GovernanceTx(Base):
    __tablename__ = "governance_txs"
    __table_args__ = (
        CheckConstraint("octet_length(safe_address) = 20", name="ck_governance_txs_safe_address"),
        CheckConstraint(
            "purpose IN ('MODULE_SETUP', 'MANDATE', 'PAYEE_ADD', 'PAYEE_DEACTIVATE', "
            "'EXCEPTION_GRANT', 'EXCEPTION_REVOKE', 'ALLOW_DUPLICATE', 'CANCEL_REQUEST', "
            "'PAUSE', 'RESUME', 'REVOKE', 'GUARDIAN_SETUP')",
            name="ck_governance_txs_purpose",
        ),
        CheckConstraint(f"status IN ({_GOVERNANCE_STATUSES})", name="ck_governance_txs_status"),
        CheckConstraint("operation IN (0, 1)", name="ck_governance_txs_operation"),
        CheckConstraint("threshold > 0", name="ck_governance_txs_threshold"),
        CheckConstraint("jsonb_typeof(calls) = 'array'", name="ck_governance_txs_calls_array"),
        CheckConstraint(
            "cardinality(owners_snapshot) > 0", name="ck_governance_txs_owners_snapshot_array"
        ),
        CheckConstraint(
            "threshold <= cardinality(owners_snapshot)",
            name="ck_governance_txs_owners_snapshot_threshold",
        ),
        CheckConstraint(
            "array_position(owners_snapshot, NULL) IS NULL",
            name="ck_governance_txs_owners_snapshot_no_null",
        ),
        CheckConstraint(
            "safe_tx_hash IS NULL OR octet_length(safe_tx_hash) = 32",
            name="ck_governance_txs_safe_tx_hash",
        ),
        CheckConstraint(
            "exec_tx_hash IS NULL OR octet_length(exec_tx_hash) = 32",
            name="ck_governance_txs_exec_tx_hash",
        ),
        UniqueConstraint("id", "treasury_id", name="uq_governance_txs_id_treasury"),
        Index("ix_governance_txs_treasury_created", "treasury_id", "created_at"),
        Index(
            "uq_governance_txs_open_safe_nonce",
            "safe_address",
            "safe_nonce",
            unique=True,
            postgresql_where=text("status IN ('Collecting', 'Ready', 'Submitted')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id", ondelete="CASCADE"), nullable=False
    )
    safe_address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    calls: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    to_address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    value: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary(), nullable=False)
    operation: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    safe_nonce: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    safe_tx_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    threshold: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    owners_snapshot: Mapped[list[bytes]] = mapped_column(ARRAY(LargeBinary(20)), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    exec_tx_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class GovernanceSignature(Base):
    __tablename__ = "governance_signatures"
    __table_args__ = (
        UniqueConstraint(
            "governance_tx_id", "owner_address", name="uq_governance_signatures_tx_owner"
        ),
        CheckConstraint(
            "octet_length(owner_address) = 20", name="ck_governance_signatures_owner_address"
        ),
        Index("ix_governance_signatures_tx_id", "governance_tx_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    governance_tx_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_txs.id", ondelete="CASCADE"), nullable=False
    )
    owner_address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    signature: Mapped[bytes] = mapped_column(LargeBinary(), nullable=False)
    signed_by_user: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class MandateVersion(Base):
    __tablename__ = "mandate_versions"
    __table_args__ = (
        UniqueConstraint("treasury_id", "version", name="uq_mandate_versions_treasury_version"),
        UniqueConstraint("id", "treasury_id", name="uq_mandate_versions_id_treasury"),
        CheckConstraint("version > 0", name="ck_mandate_versions_version"),
        CheckConstraint(
            "onchain_version IS NULL OR onchain_version >= 0",
            name="ck_mandate_versions_onchain_version",
        ),
        CheckConstraint(f"status IN ({_MANDATE_STATUSES})", name="ck_mandate_versions_status"),
        CheckConstraint("octet_length(config_hash) = 32", name="ck_mandate_versions_config_hash"),
        CheckConstraint(
            "expires_at IS NULL OR valid_from IS NULL OR expires_at > valid_from",
            name="ck_mandate_versions_expiry",
        ),
        ForeignKeyConstraint(
            ["governance_tx_id", "treasury_id"],
            ["governance_txs.id", "governance_txs.treasury_id"],
            name="fk_mandate_versions_governance_tx_treasury",
        ),
        Index("ix_mandate_versions_treasury_status", "treasury_id", "status"),
        Index(
            "uq_mandate_versions_active_treasury",
            "treasury_id",
            unique=True,
            postgresql_where=text(f"status = '{MandateVersionStatus.ACTIVE.value}'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    onchain_version: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    governance_tx_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Users are soft-deleted; SET NULL would be rejected by the immutability trigger.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MandateStatusEvent(Base):
    __tablename__ = "mandate_status_events"
    __table_args__ = (Index("ix_mandate_status_events_version_at", "mandate_version_id", "at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    mandate_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mandate_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column("from", String(24))
    to_status: Mapped[str] = mapped_column("to", String(24), nullable=False)
    tx_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )


class Payee(Base):
    __tablename__ = "payees"
    __table_args__ = (
        CheckConstraint("length(btrim(label)) > 0", name="ck_payees_label"),
        CheckConstraint("octet_length(address) = 20", name="ck_payees_address"),
        CheckConstraint(f"status IN ({_PAYEE_STATUSES})", name="ck_payees_status"),
        CheckConstraint(
            "oob_verified_at IS NULL OR oob_verified_by IS NOT NULL",
            name="ck_payees_oob_verification_actor",
        ),
        CheckConstraint(
            "oob_verified_by IS NULL OR oob_method IS NOT NULL",
            name="ck_payees_oob_method",
        ),
        CheckConstraint(
            f"oob_method IS NULL OR oob_method IN ({_OOB_METHODS})",
            name="ck_payees_oob_method_value",
        ),
        ForeignKeyConstraint(
            ["registration_tx_id", "treasury_id"],
            ["governance_txs.id", "governance_txs.treasury_id"],
            name="fk_payees_registration_tx_treasury",
        ),
        ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_payees_treasury_org",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["vendor_id", "org_id"],
            ["vendors.id", "vendors.org_id"],
            name="fk_payees_vendor_org",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "treasury_id", name="uq_payees_id_treasury"),
        Index("ix_payees_treasury_status", "treasury_id", "status"),
        Index(
            "uq_payees_active_treasury_address",
            "treasury_id",
            "address",
            unique=True,
            # ScreeningFailed is terminal, so it must not block re-proposing the address.
            postgresql_where=text(
                f"status NOT IN ('{PayeeStatus.DEACTIVATED.value}', "
                f"'{PayeeStatus.SCREENING_FAILED.value}')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ck_payees_oob_verification_actor needs the verifier, so it cannot be nulled.
    oob_verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    oob_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    oob_method: Mapped[str | None] = mapped_column(String(24))
    oob_note: Mapped[str | None] = mapped_column(Text())
    registration_tx_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class Screening(Base):
    __tablename__ = "screenings"
    __table_args__ = (
        CheckConstraint(f"result IN ({_SCREENING_RESULTS})", name="ck_screenings_result"),
        CheckConstraint("octet_length(address) = 20", name="ck_screenings_address"),
        Index("ix_screenings_payee_checked", "payee_id", "checked_at"),
        Index("ix_screenings_address_checked", "address", text("checked_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    payee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payees.id", ondelete="SET NULL")
    )
    # Always snapshotted so the row stays meaningful after its payee is deleted.
    address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(300))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ttl_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExceptionRecord(Base):
    __tablename__ = "exceptions"
    __table_args__ = (
        CheckConstraint("mandate_onchain_version >= 0", name="ck_exceptions_mandate_version"),
        CheckConstraint("amount > 0", name="ck_exceptions_amount_positive"),
        CheckConstraint("octet_length(payee) = 20", name="ck_exceptions_payee_address"),
        CheckConstraint(f"status IN ({_EXCEPTION_STATUSES})", name="ck_exceptions_status"),
        ForeignKeyConstraint(
            ["governance_tx_id", "treasury_id"],
            ["governance_txs.id", "governance_txs.treasury_id"],
            name="fk_exceptions_governance_tx_treasury",
        ),
        Index(
            "uq_exceptions_open_request",
            "request_id",
            unique=True,
            postgresql_where=text(f"status IN ({_OPEN_EXCEPTION_STATUSES})"),
        ),
        Index("ix_exceptions_status_expiry", "status", "expiry"),
        Index("ix_exceptions_treasury_status", "treasury_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id", ondelete="CASCADE"), nullable=False
    )
    # payment_requests is introduced by M05; its FK is added in that migration.
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mandate_onchain_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    payee: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    expiry: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    governance_tx_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    draft_ai_call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class GuardianSetup(Base):
    __tablename__ = "guardian_setups"
    __table_args__ = (
        CheckConstraint("octet_length(guardian_safe) = 20", name="ck_guardian_setups_safe"),
        CheckConstraint("cardinality(human_owners) > 0", name="ck_guardian_setups_human_owners"),
        CheckConstraint(
            "array_position(human_owners, NULL) IS NULL",
            name="ck_guardian_setups_no_null_owners",
        ),
        CheckConstraint("octet_length(sentinel_address) = 20", name="ck_guardian_setups_sentinel"),
        CheckConstraint("threshold = 1", name="ck_guardian_setups_threshold"),
        CheckConstraint(
            "status IN ('Pending', 'Active', 'Failed', 'Revoked')", name="ck_guardian_setups_status"
        ),
        UniqueConstraint("id", "treasury_id", name="uq_guardian_setups_id_treasury"),
        ForeignKeyConstraint(
            ["created_tx_id", "treasury_id"],
            ["governance_txs.id", "governance_txs.treasury_id"],
            name="fk_guardian_setups_created_tx_treasury",
        ),
        Index(
            "uq_guardian_setups_active_treasury",
            "treasury_id",
            unique=True,
            postgresql_where=text("status = 'Active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id", ondelete="CASCADE"), nullable=False
    )
    guardian_safe: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    human_owners: Mapped[list[bytes]] = mapped_column(ARRAY(LargeBinary(20)), nullable=False)
    sentinel_address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    threshold: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_tx_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class TreasuryFeePolicy(Base):
    __tablename__ = "treasury_fee_policies"
    __table_args__ = (
        CheckConstraint(f"preset IN ({_FEE_PRESETS})", name="ck_treasury_fee_policies_preset"),
        CheckConstraint("max_fee_multiplier_bps > 0", name="ck_treasury_fee_policies_multiplier"),
        CheckConstraint(
            "tip_percentile BETWEEN 0 AND 100", name="ck_treasury_fee_policies_tip_percentile"
        ),
        CheckConstraint("resend_after_s >= 0", name="ck_treasury_fee_policies_resend_after"),
        CheckConstraint("bump_bps >= 0", name="ck_treasury_fee_policies_bump"),
        CheckConstraint(
            "per_plan_threshold_wei >= 0", name="ck_treasury_fee_policies_plan_threshold"
        ),
        CheckConstraint("daily_budget_wei >= 0", name="ck_treasury_fee_policies_daily_budget"),
        CheckConstraint("reference_eth_price >= 0", name="ck_treasury_fee_policies_eth_price"),
        CheckConstraint("version > 0", name="ck_treasury_fee_policies_version"),
        Index(
            "uq_treasury_fee_policies_active",
            "treasury_id",
            unique=True,
            postgresql_where=text("active"),
        ),
        UniqueConstraint(
            "treasury_id", "version", name="uq_treasury_fee_policies_treasury_version"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id", ondelete="CASCADE"), nullable=False
    )
    preset: Mapped[str] = mapped_column(String(16), nullable=False)
    max_fee_multiplier_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    tip_percentile: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    resend_after_s: Mapped[int] = mapped_column(Integer, nullable=False)
    bump_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    per_plan_threshold_wei: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    daily_budget_wei: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    reference_eth_price: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class FeeAcceptance(Base):
    __tablename__ = "fee_acceptances"
    __table_args__ = (
        CheckConstraint("estimated_fee_wei >= 0", name="ck_fee_acceptances_estimated_fee"),
        CheckConstraint("accepted_cap_wei >= estimated_fee_wei", name="ck_fee_acceptances_cap"),
        CheckConstraint("length(btrim(reason)) > 0", name="ck_fee_acceptances_reason"),
        Index("ix_fee_acceptances_plan_at", "plan_id", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    # plans is introduced by M07; its FK is added with that schema.
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    estimated_fee_wei: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    accepted_cap_wei: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class BackendPause(Base):
    __tablename__ = "backend_pause"
    __table_args__ = (
        CheckConstraint(
            f"onchain_status IN ({_BACKEND_PAUSE_STATUSES})", name="ck_backend_pause_onchain_status"
        ),
        CheckConstraint("length(btrim(reason)) > 0", name="ck_backend_pause_reason"),
    )

    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("treasuries.id", ondelete="CASCADE"),
        primary_key=True,
    )
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    onchain_status: Mapped[str] = mapped_column(String(16), nullable=False)
