"""add usage_monthly for platform billing metering

Revision ID: 20261015_0064
Revises: 20261015_0063
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0064"
down_revision: str | None = "20261015_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_monthly",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("paid_count", sa.BigInteger(), nullable=False),
        sa.Column("paid_volume", sa.Numeric(78, 0), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("paid_count >= 0 AND paid_volume >= 0", name="ck_usage_monthly_nonneg"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("org_id", "month"),
    )


def downgrade() -> None:
    op.drop_table("usage_monthly")
