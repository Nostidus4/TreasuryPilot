from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base


class ErpConnection(Base):
    """One org's OAuth link to one ERP; tokens are FieldCipher envelopes (REC-L01)."""

    __tablename__ = "erp_connections"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Connected', 'ReauthRequired')", name="ck_erp_connections_status"
        ),
        UniqueConstraint("org_id", "provider", name="uq_erp_connections_org_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="Connected")
    external_tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_name: Mapped[str | None] = mapped_column(String(200))
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scopes: Mapped[str | None] = mapped_column(Text)
    payment_account_code: Mapped[str | None] = mapped_column(String(64))
    connected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ErpSyncRecord(Base):
    """One exported object (bill or payment) per reconciliation and connection."""

    __tablename__ = "erp_sync_records"
    __table_args__ = (
        CheckConstraint("kind IN ('BILL', 'PAYMENT')", name="ck_erp_sync_records_kind"),
        CheckConstraint(
            "status IN ('Pending', 'Synced', 'AwaitingApproval', 'Failed')",
            name="ck_erp_sync_records_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_erp_sync_records_attempts"),
        UniqueConstraint(
            "connection_id", "reconciliation_id", "kind", name="uq_erp_sync_records_slot"
        ),
        UniqueConstraint("idempotency_key", name="uq_erp_sync_records_idempotency"),
        Index(
            "ix_erp_sync_records_due",
            "next_attempt_at",
            postgresql_where=text("status IN ('Pending', 'AwaitingApproval', 'Failed')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("erp_connections.id", ondelete="CASCADE"), nullable=False
    )
    reconciliation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reconciliations.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="Pending")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128))
    external_status: Mapped[str | None] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
