from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base


class RetentionPolicy(Base):
    """No row means no automatic deletion; a hold overrides the configured period."""

    __tablename__ = "retention_policies"
    __table_args__ = (
        CheckConstraint(
            "invite_retention_days IS NULL OR invite_retention_days >= 0",
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


class DeletionReceipt(Base):
    """An irreversible digest of a random row id, without email, token or subject id."""

    __tablename__ = "deletion_receipts"
    __table_args__ = (
        CheckConstraint("octet_length(record_hash) = 32", name="ck_deletion_receipts_hash_length"),
        CheckConstraint("record_type = 'invite'", name="ck_deletion_receipts_record_type"),
    )

    record_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    record_type: Mapped[str] = mapped_column(String(32), nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
