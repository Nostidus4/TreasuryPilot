from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base
from treasurypilot_api.identity.models import uuid7


class NotificationSeverity(StrEnum):
    INFO = "INFO"
    ACTION = "ACTION"
    CRITICAL = "CRITICAL"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("length(btrim(type)) > 0", name="ck_notifications_type"),
        CheckConstraint("length(btrim(title)) > 0", name="ck_notifications_title"),
        CheckConstraint("length(btrim(body)) > 0", name="ck_notifications_body"),
        CheckConstraint("link LIKE '/%'", name="ck_notifications_internal_link"),
        CheckConstraint(
            "severity IN ('INFO', 'ACTION', 'CRITICAL')", name="ck_notifications_severity"
        ),
        ForeignKeyConstraint(
            ["event_id", "org_id"],
            ["domain_events.id", "domain_events.org_id"],
            name="fk_notifications_event_org",
            ondelete="CASCADE",
        ),
        UniqueConstraint("user_id", "event_id", name="uq_notifications_user_event"),
        Index("ix_notifications_org_created", "org_id", "created_at"),
        Index(
            "ix_notifications_user_unread",
            "user_id",
            "org_id",
            "created_at",
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column("type", String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
