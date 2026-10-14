"""add consented, time-limited read support grants

Revision ID: 20261014_0018
Revises: 20261014_0017
Create Date: 2026-10-14 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0018"
down_revision: str | None = "20261014_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "support_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_user", sa.String(length=200), nullable=False),
        sa.Column("scope", sa.String(length=8), server_default="read", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope = 'read'", name="ck_support_grants_read_only"),
        sa.CheckConstraint("expires_at > created_at", name="ck_support_grants_expiry"),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="ck_support_grants_revoked_at"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_support_grants_org_staff_expiry",
        "support_grants",
        ["org_id", "staff_user", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_support_grants_org_staff_expiry", table_name="support_grants")
    op.drop_table("support_grants")
