"""Record one notification per mandate expiry milestone.

Revision ID: 20261015_0053
Revises: 20261015_0052
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0053"
down_revision: str | None = "20261015_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mandate_expiry_notifications",
        sa.Column("mandate_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warning_hours", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "warning_hours IN (1, 48, 168)", name="ck_mandate_expiry_notifications_warning_hours"
        ),
        sa.ForeignKeyConstraint(
            ["mandate_version_id", "org_id"],
            ["mandate_versions.id", "mandate_versions.org_id"],
            name="fk_mandate_expiry_notifications_version_org",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "mandate_version_id", "warning_hours", name="pk_mandate_expiry_notifications"
        ),
    )


def downgrade() -> None:
    op.drop_table("mandate_expiry_notifications")
