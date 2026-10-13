from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
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


class ChannelKind(StrEnum):
    TELEGRAM = "TELEGRAM"


class NotificationChannel(Base):
    """A verified external delivery target. ``target`` is the encrypted Telegram chat id."""

    __tablename__ = "notification_channels"
    __table_args__ = (
        CheckConstraint("kind IN ('TELEGRAM')", name="ck_notification_channels_kind"),
        CheckConstraint(
            "octet_length(target_hash) = 32", name="ck_notification_channels_target_hash"
        ),
        UniqueConstraint("user_id", "kind", name="uq_notification_channels_user_kind"),
        # One Telegram chat belongs to one user, so a chat can never receive another
        # user's (or another organization's) notifications.
        UniqueConstraint("kind", "target_hash", name="uq_notification_channels_target"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    target_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    show_amounts: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # Rate limit anchor (M13-D7): at most one message per user per 10 s.
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TelegramLinkCode(Base):
    """Single-use, expiring link code. Only the SHA-256 of the code is stored."""

    __tablename__ = "telegram_link_codes"
    __table_args__ = (
        CheckConstraint("octet_length(code_hash) = 32", name="ck_telegram_link_codes_hash"),
        Index("ix_telegram_link_codes_user", "user_id"),
    )

    code_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TelegramDelivery(Base):
    """Outcome of sending one notification to one channel; written by the worker."""

    __tablename__ = "telegram_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED')", name="ck_telegram_deliveries_status"
        ),
        CheckConstraint("attempts >= 0", name="ck_telegram_deliveries_attempts"),
        UniqueConstraint("notification_id", "channel_id", name="uq_telegram_deliveries_pair"),
        Index(
            "ix_telegram_deliveries_pending",
            "channel_id",
            "next_attempt_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default="PENDING"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
