from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base
from treasurypilot_api.identity.models import Organization  # noqa: F401


class AuditActorType(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    AI = "AI"
    CONTRACT = "CONTRACT"


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('USER', 'SYSTEM', 'AI', 'CONTRACT')",
            name="ck_audit_log_actor_type",
        ),
        CheckConstraint("length(btrim(action)) > 0", name="ck_audit_log_action"),
        CheckConstraint("length(btrim(entity_type)) > 0", name="ck_audit_log_entity_type"),
        CheckConstraint("octet_length(prev_hash) = 32", name="ck_audit_log_prev_hash_length"),
        CheckConstraint("octet_length(hash) = 32", name="ck_audit_log_hash_length"),
        CheckConstraint("jsonb_typeof(data) = 'object'", name="ck_audit_log_data_object"),
        Index("ix_audit_log_org_seq", "org_id", "seq"),
        Index("ix_audit_log_org_entity_seq", "org_id", "entity_type", "entity_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)


class AuditHead(Base):
    __tablename__ = "audit_heads"
    __table_args__ = (
        CheckConstraint("last_seq IS NULL OR last_seq > 0", name="ck_audit_heads_last_seq"),
        CheckConstraint("octet_length(last_hash) = 32", name="ck_audit_heads_hash_length"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    last_seq: Mapped[int | None] = mapped_column(BigInteger)
    last_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
