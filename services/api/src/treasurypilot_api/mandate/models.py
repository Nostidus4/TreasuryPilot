from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base, RowVersionedMixin, VersionedMixin
from treasurypilot_core.ids import uuid7


class _Money(TypeDecorator[int]):
    """ADR-014: integer base units. ``asdecimal=False`` would round-trip through float."""

    impl = Numeric(78, 0)
    cache_ok = True

    def process_result_value(self, value: Any, dialect: Any) -> int | None:
        return None if value is None else int(value)


Money = _Money()


class MandateVersionStatus(StrEnum):
    DRAFT = "Draft"
    PENDING_ACTIVATION = "PendingActivation"
    ACTIVE = "Active"
    SUPERSEDED = "Superseded"
    EXPIRED = "Expired"
    REVOKED = "Revoked"
    DISCREPANCY = "Discrepancy"


class GovernanceTxPurpose(StrEnum):
    MODULE_SETUP = "MODULE_SETUP"
    MANDATE = "MANDATE"
    PAYEE_ADD = "PAYEE_ADD"
    PAYEE_DEACTIVATE = "PAYEE_DEACTIVATE"
    EXCEPTION_GRANT = "EXCEPTION_GRANT"
    EXCEPTION_REVOKE = "EXCEPTION_REVOKE"
    ALLOW_DUPLICATE = "ALLOW_DUPLICATE"
    CANCEL_REQUEST = "CANCEL_REQUEST"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    REVOKE = "REVOKE"
    GUARDIAN_SETUP = "GUARDIAN_SETUP"


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


class GuardianSetupStatus(StrEnum):
    PENDING = "Pending"
    ACTIVE = "Active"
    SUPERSEDED = "Superseded"


class FeePreset(StrEnum):
    ECONOMY = "ECONOMY"
    NORMAL = "NORMAL"
    FAST = "FAST"


class OnchainPauseStatus(StrEnum):
    NOT_REQUESTED = "NotRequested"
    REQUESTED = "Requested"
    EFFECTIVE = "Effective"


def _enum(enum_class: type[StrEnum], name: str) -> Enum:
    return Enum(enum_class, name=name, values_callable=lambda values: [v.value for v in values])


mandate_version_status_enum = _enum(MandateVersionStatus, "mandate_version_status")
governance_tx_purpose_enum = _enum(GovernanceTxPurpose, "governance_tx_purpose")
governance_tx_status_enum = _enum(GovernanceTxStatus, "governance_tx_status")
payee_status_enum = _enum(PayeeStatus, "payee_status")
oob_method_enum = _enum(OobMethod, "payee_oob_method")
screening_result_enum = _enum(ScreeningResult, "screening_result")
exception_status_enum = _enum(ExceptionStatus, "exception_status")
guardian_setup_status_enum = _enum(GuardianSetupStatus, "guardian_setup_status")
fee_preset_enum = _enum(FeePreset, "fee_preset")
onchain_pause_status_enum = _enum(OnchainPauseStatus, "onchain_pause_status")


def _treasury_fk(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["treasury_id", "org_id"],
        ["treasuries.id", "treasuries.org_id"],
        name=f"fk_{table}_treasury_org",
        ondelete="CASCADE",
    )


def _governance_tx_fk(table: str, column: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        [column, "org_id"],
        ["governance_txs.id", "governance_txs.org_id"],
        name=f"fk_{table}_{column}",
        ondelete="RESTRICT",
    )


class Vendor(VersionedMixin, Base):
    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("org_id", "normalized_ref", name="uq_vendors_org_ref"),
        UniqueConstraint("id", "org_id", name="uq_vendors_id_org"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_vendors_name"),
        CheckConstraint("length(btrim(normalized_ref)) > 0", name="ck_vendors_normalized_ref"),
        CheckConstraint("country IS NULL OR country ~ '^[A-Z]{2}$'", name="ck_vendors_country"),
        CheckConstraint("version > 0", name="ck_vendors_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str | None] = mapped_column(String(2))
    normalized_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    # Confidential PII (F-113): ciphertext only, never plaintext.
    tax_id_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    contact_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    notes: Mapped[str | None] = mapped_column(Text)


class GovernanceTx(VersionedMixin, Base):
    """A SafeTx built by the app; owners sign its hash in-app (M03-D1)."""

    __tablename__ = "governance_txs"
    __table_args__ = (
        UniqueConstraint("id", "org_id", name="uq_governance_txs_id_org"),
        _treasury_fk("governance_txs"),
        ForeignKeyConstraint(
            ["treasury_id", "chain_id"],
            ["treasuries.id", "treasuries.chain_id"],
            name="fk_governance_txs_treasury_chain",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "octet_length(safe_address) = 20", name="ck_governance_txs_safe_address_length"
        ),
        CheckConstraint('octet_length("to") = 20', name="ck_governance_txs_to_length"),
        CheckConstraint("jsonb_typeof(calls) = 'array'", name="ck_governance_txs_calls_array"),
        CheckConstraint("value >= 0", name="ck_governance_txs_value"),
        CheckConstraint("operation IN (0, 1)", name="ck_governance_txs_operation"),
        CheckConstraint("safe_nonce >= 0", name="ck_governance_txs_safe_nonce"),
        CheckConstraint(
            "octet_length(safe_tx_hash) = 32", name="ck_governance_txs_safe_tx_hash_length"
        ),
        CheckConstraint(
            "threshold > 0 AND threshold <= cardinality(owners_snapshot)",
            name="ck_governance_txs_threshold",
        ),
        CheckConstraint(
            "exec_tx_hash IS NULL OR octet_length(exec_tx_hash) = 32",
            name="ck_governance_txs_exec_tx_hash_length",
        ),
        CheckConstraint("version > 0", name="ck_governance_txs_version"),
        Index("ix_governance_txs_org_treasury", "org_id", "treasury_id"),
        # M03-D5: one open governance tx per Safe nonce; the next change queues at nonce + 1.
        Index(
            "uq_governance_txs_open_nonce",
            "chain_id",
            "safe_address",
            "safe_nonce",
            unique=True,
            postgresql_where=text(
                "status IN ('Collecting'::governance_tx_status, 'Ready'::governance_tx_status, "
                "'Submitted'::governance_tx_status)"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    safe_address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    purpose: Mapped[GovernanceTxPurpose] = mapped_column(governance_tx_purpose_enum, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    to: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    value: Mapped[int] = mapped_column(Money, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    operation: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    safe_nonce: Mapped[int] = mapped_column(BigInteger, nullable=False)
    safe_tx_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    threshold: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    owners_snapshot: Mapped[list[bytes]] = mapped_column(ARRAY(LargeBinary(20)), nullable=False)
    status: Mapped[GovernanceTxStatus] = mapped_column(
        governance_tx_status_enum,
        nullable=False,
        default=GovernanceTxStatus.COLLECTING,
        server_default=GovernanceTxStatus.COLLECTING,
    )
    exec_tx_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))


class GovernanceSignature(Base):
    __tablename__ = "governance_signatures"
    __table_args__ = (
        UniqueConstraint(
            "governance_tx_id", "owner_address", name="uq_governance_signatures_tx_owner"
        ),
        Index("ix_governance_signatures_org_tx", "org_id", "governance_tx_id"),
        ForeignKeyConstraint(
            ["governance_tx_id", "org_id"],
            ["governance_txs.id", "governance_txs.org_id"],
            name="fk_governance_signatures_tx_org",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "octet_length(owner_address) = 20", name="ck_governance_signatures_owner_length"
        ),
        CheckConstraint(
            "octet_length(signature) >= 65", name="ck_governance_signatures_signature_length"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    governance_tx_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    owner_address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    signature: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    signed_by_user: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MandateVersion(Base):
    """Immutable governance snapshot (M03-D4); a trigger allows only lifecycle columns to move."""

    __tablename__ = "mandate_versions"
    __table_args__ = (
        UniqueConstraint("treasury_id", "version", name="uq_mandate_versions_treasury_version"),
        UniqueConstraint("id", "org_id", name="uq_mandate_versions_id_org"),
        Index(
            "uq_mandate_versions_active",
            "treasury_id",
            unique=True,
            postgresql_where=text("status = 'Active'::mandate_version_status"),
        ),
        _treasury_fk("mandate_versions"),
        _governance_tx_fk("mandate_versions", "governance_tx_id"),
        CheckConstraint("version > 0", name="ck_mandate_versions_version"),
        CheckConstraint(
            "onchain_version IS NULL OR onchain_version > 0",
            name="ck_mandate_versions_onchain_version",
        ),
        CheckConstraint("jsonb_typeof(config) = 'object'", name="ck_mandate_versions_config"),
        CheckConstraint(
            "octet_length(config_hash) = 32", name="ck_mandate_versions_config_hash_length"
        ),
        CheckConstraint("expires_at > valid_from", name="ck_mandate_versions_validity"),
        CheckConstraint(
            "status <> 'Active'::mandate_version_status "
            "OR (onchain_version IS NOT NULL AND activated_at IS NOT NULL)",
            name="ck_mandate_versions_active",
        ),
        Index("ix_mandate_versions_org_treasury", "org_id", "treasury_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    onchain_version: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[MandateVersionStatus] = mapped_column(
        mandate_version_status_enum,
        nullable=False,
        default=MandateVersionStatus.DRAFT,
        server_default=MandateVersionStatus.DRAFT,
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    governance_tx_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # NO ACTION, not SET NULL: the immutability trigger would reject the cascaded update.
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="NO ACTION"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MandateStatusEvent(Base):
    """Append-only history of mandate version transitions."""

    __tablename__ = "mandate_status_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["mandate_version_id", "org_id"],
            ["mandate_versions.id", "mandate_versions.org_id"],
            name="fk_mandate_status_events_version_org",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "tx_hash IS NULL OR octet_length(tx_hash) = 32",
            name="ck_mandate_status_events_tx_hash_length",
        ),
        Index("ix_mandate_status_events_org_version_at", "org_id", "mandate_version_id", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mandate_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_status: Mapped[MandateVersionStatus | None] = mapped_column(mandate_version_status_enum)
    to_status: Mapped[MandateVersionStatus] = mapped_column(
        mandate_version_status_enum, nullable=False
    )
    tx_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # NULL means the system (watcher, scheduler) made the transition.
    by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="NO ACTION")
    )


class Payee(VersionedMixin, Base):
    """A vendor's payout address; ``created_by`` is the proposer."""

    __tablename__ = "payees"
    __table_args__ = (
        UniqueConstraint("id", "org_id", name="uq_payees_id_org"),
        _treasury_fk("payees"),
        ForeignKeyConstraint(
            ["vendor_id", "org_id"],
            ["vendors.id", "vendors.org_id"],
            name="fk_payees_vendor_org",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "treasury_id", "vendor_id", name="uq_payees_id_treasury_vendor"),
        _governance_tx_fk("payees", "registration_tx_id"),
        CheckConstraint("length(btrim(label)) > 0", name="ck_payees_label"),
        CheckConstraint("octet_length(address) = 20", name="ck_payees_address_length"),
        # M03-D7: an out-of-band verification is recorded whole or not at all.
        CheckConstraint(
            "(oob_verified_by IS NULL AND oob_verified_at IS NULL AND oob_method IS NULL "
            "AND oob_note IS NULL) OR (oob_verified_by IS NOT NULL "
            "AND oob_verified_at IS NOT NULL AND oob_method IS NOT NULL "
            "AND length(btrim(oob_note)) > 0)",
            name="ck_payees_oob",
        ),
        CheckConstraint(
            "status NOT IN ('Cooling'::payee_status, 'Active'::payee_status) "
            "OR (oob_verified_at IS NOT NULL AND active_from IS NOT NULL)",
            name="ck_payees_registered",
        ),
        CheckConstraint(
            "status <> 'Deactivated'::payee_status OR deactivated_at IS NOT NULL",
            name="ck_payees_deactivated",
        ),
        CheckConstraint("version > 0", name="ck_payees_version"),
        Index("ix_payees_org_treasury", "org_id", "treasury_id"),
        Index("ix_payees_vendor", "vendor_id"),
        Index("ix_payees_treasury_status", "treasury_id", "status"),
        Index(
            "uq_payees_treasury_address_live",
            "treasury_id",
            "address",
            unique=True,
            postgresql_where=text(
                "status NOT IN ('Deactivated'::payee_status, 'ScreeningFailed'::payee_status)"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    status: Mapped[PayeeStatus] = mapped_column(
        payee_status_enum,
        nullable=False,
        default=PayeeStatus.PROPOSED,
        server_default=PayeeStatus.PROPOSED,
    )
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    oob_verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="NO ACTION")
    )
    oob_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    oob_method: Mapped[OobMethod | None] = mapped_column(oob_method_enum)
    oob_note: Mapped[str | None] = mapped_column(Text)
    registration_tx_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Screening(Base):
    __tablename__ = "screenings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["payee_id", "org_id"],
            ["payees.id", "payees.org_id"],
            name="fk_screenings_payee_org",
            ondelete="SET NULL (payee_id)",
        ),
        CheckConstraint("octet_length(address) = 20", name="ck_screenings_address_length"),
        CheckConstraint("length(btrim(provider)) > 0", name="ck_screenings_provider"),
        CheckConstraint("ttl_until IS NULL OR ttl_until > checked_at", name="ck_screenings_ttl"),
        Index("ix_screenings_address_checked", "address", desc("checked_at")),
        Index("ix_screenings_org_payee", "org_id", "payee_id"),
        CheckConstraint("chain_id IS NULL OR chain_id > 0", name="ck_screenings_chain_id"),
        Index(
            "ix_screenings_lookup",
            "org_id",
            "address",
            "chain_id",
            "provider",
            desc("checked_at"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    payee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    # NULL only for legacy rows; screening cache lookups always require a chain.
    chain_id: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[ScreeningResult] = mapped_column(screening_result_enum, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ttl_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MandateException(VersionedMixin, Base):
    """One-time exception for a single request (F-025)."""

    __tablename__ = "exceptions"
    __table_args__ = (
        _treasury_fk("exceptions"),
        _governance_tx_fk("exceptions", "governance_tx_id"),
        CheckConstraint("mandate_onchain_version > 0", name="ck_exceptions_mandate_version"),
        CheckConstraint("amount > 0", name="ck_exceptions_amount"),
        CheckConstraint("octet_length(payee) = 20", name="ck_exceptions_payee_length"),
        CheckConstraint("version > 0", name="ck_exceptions_version"),
        Index("ix_exceptions_org_treasury", "org_id", "treasury_id"),
        # BR-041: at most one live exception per request.
        ForeignKeyConstraint(
            ["request_id", "treasury_id"],
            ["payment_requests.id", "payment_requests.treasury_id"],
            name="fk_exceptions_request_treasury",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_exceptions_open_request",
            "request_id",
            unique=True,
            postgresql_where=text(
                "status IN ('Requested'::exception_status, 'Proposed'::exception_status, "
                "'Granted'::exception_status)"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mandate_onchain_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[int] = mapped_column(Money, nullable=False)
    payee: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    expiry: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ExceptionStatus] = mapped_column(
        exception_status_enum,
        nullable=False,
        default=ExceptionStatus.REQUESTED,
        server_default=ExceptionStatus.REQUESTED,
    )
    governance_tx_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    draft_ai_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_calls.id", ondelete="RESTRICT")
    )
    reason: Mapped[str | None] = mapped_column(Text)


class GuardianSetup(VersionedMixin, Base):
    """Guardian Safe 1-of-N {humans, sentinel} that can only pause (M03-D2)."""

    __tablename__ = "guardian_setups"
    __table_args__ = (
        _treasury_fk("guardian_setups"),
        _governance_tx_fk("guardian_setups", "created_tx_id"),
        CheckConstraint(
            "octet_length(guardian_safe) = 20", name="ck_guardian_setups_guardian_safe_length"
        ),
        CheckConstraint(
            "cardinality(human_owners) > 0 AND array_position(human_owners, NULL) IS NULL",
            name="ck_guardian_setups_human_owners",
        ),
        CheckConstraint(
            "octet_length(sentinel_address) = 20", name="ck_guardian_setups_sentinel_length"
        ),
        CheckConstraint("threshold = 1", name="ck_guardian_setups_threshold"),
        CheckConstraint("version > 0", name="ck_guardian_setups_version"),
        Index("ix_guardian_setups_org_treasury", "org_id", "treasury_id"),
        Index(
            "uq_guardian_setups_active",
            "treasury_id",
            unique=True,
            postgresql_where=text("status = 'Active'::guardian_setup_status"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    guardian_safe: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    human_owners: Mapped[list[bytes]] = mapped_column(ARRAY(LargeBinary(20)), nullable=False)
    sentinel_address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    threshold: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default="1"
    )
    created_tx_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[GuardianSetupStatus] = mapped_column(
        guardian_setup_status_enum,
        nullable=False,
        default=GuardianSetupStatus.PENDING,
        server_default=GuardianSetupStatus.PENDING,
    )


class TreasuryFeePolicy(RowVersionedMixin, Base):
    """System-proposed, Owner-accepted fee policy (FEE-1); old rows are kept as history."""

    __tablename__ = "treasury_fee_policies"
    __table_args__ = (
        UniqueConstraint("treasury_id", "version", name="uq_treasury_fee_policies_version"),
        _treasury_fk("treasury_fee_policies"),
        CheckConstraint("max_fee_multiplier_bps > 0", name="ck_treasury_fee_policies_multiplier"),
        CheckConstraint(
            "tip_percentile BETWEEN 0 AND 100", name="ck_treasury_fee_policies_tip_percentile"
        ),
        CheckConstraint("resend_after_s > 0", name="ck_treasury_fee_policies_resend_after"),
        CheckConstraint("bump_bps >= 0", name="ck_treasury_fee_policies_bump"),
        CheckConstraint(
            "per_plan_threshold_wei >= 0", name="ck_treasury_fee_policies_per_plan_threshold"
        ),
        CheckConstraint("daily_budget_wei >= 0", name="ck_treasury_fee_policies_daily_budget"),
        CheckConstraint(
            "reference_eth_price IS NULL OR reference_eth_price > 0",
            name="ck_treasury_fee_policies_reference_eth_price",
        ),
        CheckConstraint(
            "(accepted_by IS NULL) = (accepted_at IS NULL)",
            name="ck_treasury_fee_policies_acceptance",
        ),
        CheckConstraint(
            "superseded_at IS NULL OR accepted_at IS NOT NULL",
            name="ck_treasury_fee_policies_superseded",
        ),
        CheckConstraint("version > 0", name="ck_treasury_fee_policies_version"),
        CheckConstraint("row_version > 0", name="ck_treasury_fee_policies_row_version"),
        Index("ix_treasury_fee_policies_org_treasury", "org_id", "treasury_id"),
        Index(
            "uq_treasury_fee_policies_active",
            "treasury_id",
            unique=True,
            postgresql_where=text("accepted_at IS NOT NULL AND superseded_at IS NULL"),
        ),
        Index(
            "uq_treasury_fee_policies_pending",
            "treasury_id",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND superseded_at IS NULL"),
        ),
        CheckConstraint("avg_plan_fee_7d_wei >= 0", name="ck_treasury_fee_policies_avg_plan_fee"),
        CheckConstraint("p90_plan_fee_7d_wei >= 0", name="ck_treasury_fee_policies_p90_plan_fee"),
        CheckConstraint("plans_per_day_7d >= 0", name="ck_treasury_fee_policies_plans_per_day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    preset: Mapped[FeePreset] = mapped_column(fee_preset_enum, nullable=False)
    max_fee_multiplier_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    tip_percentile: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    resend_after_s: Mapped[int] = mapped_column(Integer, nullable=False)
    bump_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    per_plan_threshold_wei: Mapped[int] = mapped_column(Money, nullable=False)
    daily_budget_wei: Mapped[int] = mapped_column(Money, nullable=False)
    # Asset base units per 1 ETH; only for comparing fees with payment values.
    reference_eth_price: Mapped[int | None] = mapped_column(Money)
    avg_plan_fee_7d_wei: Mapped[int] = mapped_column(Money, nullable=False, default=0)
    p90_plan_fee_7d_wei: Mapped[int] = mapped_column(Money, nullable=False, default=0)
    plans_per_day_7d: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, default=0)
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="NO ACTION")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class FeeAcceptance(Base):
    __tablename__ = "fee_acceptances"
    __table_args__ = (
        CheckConstraint("estimated_fee_wei >= 0", name="ck_fee_acceptances_estimated_fee"),
        CheckConstraint(
            "accepted_cap_wei >= estimated_fee_wei", name="ck_fee_acceptances_accepted_cap"
        ),
        UniqueConstraint("plan_id", name="uq_fee_acceptances_plan"),
        Index("ix_fee_acceptances_org_plan", "org_id", "plan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # shortcut: no FK yet, plans land with the planning schema; add the FK there.
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    estimated_fee_wei: Mapped[int] = mapped_column(Money, nullable=False)
    accepted_cap_wei: Mapped[int] = mapped_column(Money, nullable=False)
    accepted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="NO ACTION"), nullable=False
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reason: Mapped[str | None] = mapped_column(Text)


class BackendPause(VersionedMixin, Base):
    """Backend pause flag, set before any on-chain pause (M03-D14); ``updated_*`` = by/at."""

    __tablename__ = "backend_pause"
    __table_args__ = (
        _treasury_fk("backend_pause"),
        CheckConstraint("NOT paused OR length(btrim(reason)) > 0", name="ck_backend_pause_reason"),
        CheckConstraint("version > 0", name="ck_backend_pause_version"),
        Index("ix_backend_pause_org", "org_id"),
    )

    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    reason: Mapped[str | None] = mapped_column(Text)
    onchain_status: Mapped[OnchainPauseStatus] = mapped_column(
        onchain_pause_status_enum,
        nullable=False,
        default=OnchainPauseStatus.NOT_REQUESTED,
        server_default=OnchainPauseStatus.NOT_REQUESTED,
    )
