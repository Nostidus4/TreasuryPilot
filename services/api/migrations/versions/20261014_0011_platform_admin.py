"""add platform tenant status and admin operation records

Revision ID: 20261014_0011
Revises: 20261014_0010
Create Date: 2026-10-14 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0011"
down_revision: str | None = "20261014_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("platform_status", sa.String(length=16), server_default="active", nullable=False),
    )
    op.create_check_constraint(
        "ck_organizations_platform_status",
        "organizations",
        "platform_status IN ('active', 'suspended')",
    )
    op.create_table(
        "platform_admin_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platform_admin_events_org_created", "platform_admin_events", ["org_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_platform_admin_events_org_created", table_name="platform_admin_events")
    op.drop_table("platform_admin_events")
    op.drop_constraint("ck_organizations_platform_status", "organizations", type_="check")
    op.drop_column("organizations", "platform_status")
