"""schedules: advisory append-only deadline schedule written by the 15-minute cycle (EXE-003)

Revision ID: 20261015_0075
Revises: 20261015_0073
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0075"
down_revision: str | None = "20261015_0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("solver", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="Computed", nullable=False),
        sa.Column("objective", postgresql.JSONB(), nullable=True),
        sa.Column("items", postgresql.JSONB(), nullable=False),
        sa.Column(
            "infeasible", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_schedules_treasury_org",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedules_treasury_computed", "schedules", ["treasury_id", "computed_at"])


def downgrade() -> None:
    op.drop_index("ix_schedules_treasury_computed", table_name="schedules")
    op.drop_table("schedules")
