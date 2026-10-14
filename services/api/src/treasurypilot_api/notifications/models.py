from __future__ import annotations

import uuid
from datetime import datetime, time
from enum import StrEnum

from sqlalchemy import (
    ARRAY,
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
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base
from treasurypilot_api.identity.models import uuid7


class NotificationSeverity(StrEnum):
    INFO = "INFO"
    ACTION = "ACTION"
    CRITICAL = "CRITICAL"


class EmailDeliveryMode(StrEnum):
    IMMEDIATE = "immediate"
    DAILY = "daily"
    OFF = "off"


class NotificationEmailPreference(Base):
    """Email cadence selection, separate from channel/category preferences."""

    __tablename__ = "notification_email_preferences"
    __table_args__ = (
        CheckConstraint(
            "delivery_mode IN ('immediate', 'daily', 'off')",
            name="ck_notification_email_preferences_mode",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    delivery_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'immediate'")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WebhookEndpoint(Base):
    """An organization-owned callback destination and encrypted signing key."""

    __tablename__ = "webhook_endpoints"
    __table_args__ = (
        CheckConstraint("url LIKE 'https://%'", name="ck_webhook_endpoints_https"),
        CheckConstraint("cardinality(event_types) > 0", name="ck_webhook_endpoints_event_types"),
        UniqueConstraint("id", "org_id", name="uq_webhook_endpoints_id_org"),
        Index("ix_webhook_endpoints_org", "org_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    event_types: Mapped[list[str]] = mapped_column(ARRAY(String(80)), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WebhookDelivery(Base):
    """Durable delivery state; one delivery per endpoint and domain event."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'retrying', 'delivered', 'dead')",
            name="ck_webhook_deliveries_status",
        ),
        ForeignKeyConstraint(
            ["endpoint_id", "org_id"],
            ["webhook_endpoints.id", "webhook_endpoints.org_id"],
            name="fk_webhook_deliveries_endpoint_org",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["event_id", "org_id"],
            ["domain_events.id", "domain_events.org_id"],
            name="fk_webhook_deliveries_event_org",
            ondelete="CASCADE",
        ),
        UniqueConstraint("endpoint_id", "event_id", name="uq_webhook_deliveries_endpoint_event"),
        Index(
            "ix_webhook_deliveries_pending",
            "next_attempt_at",
            "id",
            postgresql_where=text("status IN ('pending', 'retrying')"),
        ),
        Index(
            "ix_webhook_deliveries_dead",
            "org_id",
            "created_at",
            postgresql_where=text("status = 'dead'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


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
            "ix_notifications_email_pending",
            "deliver_at",
            "id",
            postgresql_where=text("email_sent_at IS NULL"),
        ),
        Index("ix_notifications_user_deliver", "user_id", "org_id", "deliver_at"),
        Index(
            "ix_notifications_actionable_deliver",
            "deliver_at",
            postgresql_where=text("severity IN ('ACTION', 'CRITICAL')"),
        ),
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
    # When the notification becomes visible: later than created_at during quiet hours.
    # List, unread count and the SSE cursor all key on this, never on created_at.
    deliver_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    email_next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class NotificationPreference(Base):
    """Per-user delivery controls; mandatory events bypass every setting."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        CheckConstraint(
            "(quiet_hours_start IS NULL) = (quiet_hours_end IS NULL)",
            name="ck_notification_preferences_quiet_hours_pair",
        ),
        CheckConstraint("length(btrim(timezone)) > 0", name="ck_notification_preferences_timezone"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    channels: Mapped[dict[str, bool]] = mapped_column(
        postgresql.JSONB(astext_type=Text()),
        nullable=False,
        server_default=text('\'{"in_app": true, "email": true, "telegram": true}\'::jsonb'),
    )
    categories: Mapped[dict[str, bool]] = mapped_column(
        postgresql.JSONB(astext_type=Text()), nullable=False, server_default=text("'{}'::jsonb")
    )
    quiet_hours_start: Mapped[time | None] = mapped_column(Time(timezone=False))
    quiet_hours_end: Mapped[time | None] = mapped_column(Time(timezone=False))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="UTC")
