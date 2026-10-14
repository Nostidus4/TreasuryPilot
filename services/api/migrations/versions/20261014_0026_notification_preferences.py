"""add per-user notification preferences and notifications.deliver_at

Revision ID: 20261014_0026
Revises: 20261014_0025
Create Date: 2026-10-13 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0026"
down_revision: str | None = "20261014_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column(
            "deliver_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.execute("UPDATE notifications SET deliver_at = created_at")
    op.create_index(
        "ix_notifications_user_deliver", "notifications", ["user_id", "org_id", "deliver_at"]
    )
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "channels",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text('\'{"in_app": true, "email": true, "telegram": true}\'::jsonb'),
            nullable=False,
        ),
        sa.Column(
            "categories",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("quiet_hours_start", sa.Time(timezone=False), nullable=True),
        sa.Column("quiet_hours_end", sa.Time(timezone=False), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.CheckConstraint(
            "(quiet_hours_start IS NULL) = (quiet_hours_end IS NULL)",
            name="ck_notification_preferences_quiet_hours_pair",
        ),
        sa.CheckConstraint(
            "length(btrim(timezone)) > 0", name="ck_notification_preferences_timezone"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_index("ix_notifications_user_deliver", table_name="notifications")
    op.drop_column("notifications", "deliver_at")
