from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base


class PlatformAdminEvent(Base):
    """Append-only record of staff operations outside any tenant audit chain."""

    __tablename__ = "platform_admin_events"
    __table_args__ = (Index("ix_platform_admin_events_org_created", "org_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SupportGrant(Base):
    """Tenant consent for a platform staff member to read a bounded support view."""

    __tablename__ = "support_grants"
    __table_args__ = (
        CheckConstraint("scope = 'read'", name="ck_support_grants_read_only"),
        CheckConstraint("expires_at > created_at", name="ck_support_grants_expiry"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="ck_support_grants_revoked_at"
        ),
        Index("ix_support_grants_org_staff_expiry", "org_id", "staff_user", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    staff_user: Mapped[str] = mapped_column(String(200), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(8), nullable=False, default="read", server_default="read"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    granted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
