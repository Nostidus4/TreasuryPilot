from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base
from treasurypilot_api.identity.models import uuid7


class RetentionPolicy(Base):
    """No row means no automatic deletion; a hold overrides the configured period."""

    __tablename__ = "retention_policies"
    __table_args__ = (
        CheckConstraint(
            "invite_retention_days IS NULL OR invite_retention_days BETWEEN 0 AND 36500",
            name="ck_retention_policies_invite_days",
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    invite_retention_days: Mapped[int | None] = mapped_column(Integer)
    legal_hold: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AuthRetentionPolicy(Base):
    """Explicit deployment-wide retention for expired authentication artifacts."""

    __tablename__ = "auth_retention_policies"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_auth_retention_policies_singleton"),
        CheckConstraint(
            "session_retention_days IS NULL OR session_retention_days BETWEEN 0 AND 36500",
            name="ck_auth_retention_policies_session_days",
        ),
        CheckConstraint(
            "magic_link_retention_days IS NULL OR magic_link_retention_days BETWEEN 0 AND 36500",
            name="ck_auth_retention_policies_magic_link_days",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1, server_default="1")
    session_retention_days: Mapped[int | None] = mapped_column(Integer)
    magic_link_retention_days: Mapped[int | None] = mapped_column(Integer)
    legal_hold: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DeletionReceipt(Base):
    """An irreversible digest of a random row id, without email, token or subject id."""

    __tablename__ = "deletion_receipts"
    __table_args__ = (
        CheckConstraint("octet_length(record_hash) = 32", name="ck_deletion_receipts_hash_length"),
        CheckConstraint(
            "record_type IN ('invite', 'session', 'magic_link')",
            name="ck_deletion_receipts_record_type",
        ),
    )

    record_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    record_type: Mapped[str] = mapped_column(String(32), nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ScreeningListEntry(Base):
    """Fixture screening-list entry. The source label must identify TEST DATA."""

    __tablename__ = "screening_lists"
    __table_args__ = (
        CheckConstraint("octet_length(address) = 20", name="ck_screening_lists_address"),
        CheckConstraint("length(btrim(source_label)) > 0", name="ck_screening_lists_source_label"),
        UniqueConstraint("address", "list_name", name="uq_screening_lists_address_list"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    source_label: Mapped[str] = mapped_column(String(300), nullable=False)
    list_name: Mapped[str] = mapped_column(String(120), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class KybVerification(Base):
    """One provider verdict for an organization; the newest row per provider is its KYB status."""

    __tablename__ = "kyb_verifications"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name="ck_kyb_status"),
        CheckConstraint("length(btrim(provider)) > 0", name="ck_kyb_provider"),
        Index("ix_kyb_lookup", "org_id", "provider", desc("checked_at")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
