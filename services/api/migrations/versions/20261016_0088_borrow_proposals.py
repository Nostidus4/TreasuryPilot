"""borrow proposals: the current borrow estimate per treasury (ENG-014, TRS-009)

Revision ID: 20261016_0088
Revises: 20261016_0087
Create Date: 2026-10-16 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_0088"
down_revision: str | None = "20261016_0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "borrow_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="Proposed", nullable=False),
        sa.Column("shortfall", sa.Numeric(78, 0), nullable=False),
        sa.Column("amount", sa.Numeric(78, 0), nullable=False),
        sa.Column("cost_to_repayment", sa.Numeric(78, 0), nullable=False),
        sa.Column("withdraw_cost", sa.Numeric(78, 0), nullable=False),
        sa.Column("health_factor_before", sa.Numeric(78, 0), nullable=True),
        sa.Column("health_factor_after", sa.Numeric(78, 0), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("due_day", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('Proposed', 'Authorized', 'Dismissed', 'Superseded')",
            name="ck_borrow_proposals_status",
        ),
        sa.CheckConstraint("amount > 0 AND shortfall > 0", name="ck_borrow_proposals_amounts"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    # At most one open proposal per treasury; a newer estimate supersedes it.
    op.create_index(
        "uq_borrow_proposals_open",
        "borrow_proposals",
        ["treasury_id"],
        unique=True,
        postgresql_where=sa.text("status = 'Proposed'"),
    )


def downgrade() -> None:
    op.drop_index("uq_borrow_proposals_open", table_name="borrow_proposals")
    op.drop_table("borrow_proposals")
