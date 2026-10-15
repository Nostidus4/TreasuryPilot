"""per-org account mappings for the journal export (REC-004)

Revision ID: 20261015_0084
Revises: 20261015_0075
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0084"
down_revision: str | None = "20261015_0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=6), nullable=False),
        sa.Column("account_code", sa.String(length=32), nullable=False),
        sa.Column("account_name", sa.String(length=100), nullable=False),
        sa.CheckConstraint("side IN ('DEBIT', 'CREDIT')", name="ck_account_mappings_side"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name="fk_account_mappings_org", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "classification", "side", name="uq_account_mappings_slot"),
    )
    # DAILY snapshots (UTC midnight, never pruned) back the supply-interest export line.
    op.drop_constraint("ck_snapshots_purpose", "snapshots", type_="check")
    op.create_check_constraint(
        "ck_snapshots_purpose",
        "snapshots",
        "purpose IN ('PLAN', 'PRE_STEP', 'DASHBOARD', 'READBACK', 'DAILY')",
    )


def downgrade() -> None:
    op.execute("ALTER TABLE snapshots DISABLE TRIGGER snapshots_immutable")
    op.execute("DELETE FROM snapshots WHERE purpose = 'DAILY'")
    op.execute("ALTER TABLE snapshots ENABLE TRIGGER snapshots_immutable")
    op.drop_constraint("ck_snapshots_purpose", "snapshots", type_="check")
    op.create_check_constraint(
        "ck_snapshots_purpose",
        "snapshots",
        "purpose IN ('PLAN', 'PRE_STEP', 'DASHBOARD', 'READBACK')",
    )
    op.drop_table("account_mappings")
