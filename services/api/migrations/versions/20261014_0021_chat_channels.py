"""add Slack, Lark and WeCom notification channels and delivery state

Revision ID: 20261014_0021
Revises: 20261014_0020
Create Date: 2026-10-14 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0021"
down_revision: str | None = "20261014_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_notification_channels_kind", "notification_channels", type_="check")
    op.create_check_constraint(
        "ck_notification_channels_kind",
        "notification_channels",
        "kind IN ('TELEGRAM', 'SLACK', 'LARK', 'WECOM')",
    )
    op.create_table(
        "chat_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED')", name="ck_chat_deliveries_status"
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_chat_deliveries_attempts"),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["notification_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notification_id", "channel_id", name="uq_chat_deliveries_pair"),
    )
    op.create_index(
        "ix_chat_deliveries_pending",
        "chat_deliveries",
        ["channel_id", "next_attempt_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("ix_chat_deliveries_pending", table_name="chat_deliveries")
    op.drop_table("chat_deliveries")
    op.drop_constraint("ck_notification_channels_kind", "notification_channels", type_="check")
    op.create_check_constraint(
        "ck_notification_channels_kind",
        "notification_channels",
        "kind IN ('TELEGRAM')",
    )
