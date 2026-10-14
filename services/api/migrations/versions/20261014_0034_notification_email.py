"""add user email cadence, delivery claims and retry state for notification mail

Revision ID: 20261014_0034
Revises: 20261014_0033
Create Date: 2026-10-14 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0034"
down_revision: str | None = "20261014_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_email_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "delivery_mode", sa.String(length=16), server_default="immediate", nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "delivery_mode IN ('immediate', 'daily', 'off')",
            name="ck_notification_email_preferences_mode",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.add_column(
        "notifications", sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "notifications", sa.Column("email_claimed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "notifications",
        sa.Column("email_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "notifications",
        sa.Column("email_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notifications_email_pending",
        "notifications",
        ["deliver_at", "id"],
        postgresql_where=sa.text("email_sent_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_email_pending", table_name="notifications")
    op.drop_column("notifications", "email_next_attempt_at")
    op.drop_column("notifications", "email_attempts")
    op.drop_column("notifications", "email_claimed_at")
    op.drop_column("notifications", "email_sent_at")
    op.drop_table("notification_email_preferences")
