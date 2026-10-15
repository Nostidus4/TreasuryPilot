"""add reconciliations and classified reconciliation lines

Revision ID: 20261015_0068
Revises: 20261015_0067
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0068"
down_revision: str | None = "20261015_0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reconciliations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="Pending"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # Written by REC-003 (match) and REC-005 (EAS receipt); nullable until then.
        sa.Column("matched_by", sa.String(length=8), nullable=True),
        sa.Column("matched_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("eas_uid", sa.String(length=66), nullable=True),
        sa.CheckConstraint("matched_by IN ('USER', 'AUTO')", name="ck_reconciliations_matched_by"),
        sa.ForeignKeyConstraint(["matched_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('NotReady', 'Pending', 'Matched', 'Discrepancy')",
            name="ck_reconciliations_status",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_reconciliations_request"),
    )
    op.create_index("ix_reconciliations_org_status", "reconciliations", ["org_id", "status"])
    op.create_table(
        "reconciliation_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reconciliation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("classification", sa.String(length=24), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tx_hash", postgresql.BYTEA(), nullable=False),
        sa.Column("from_address", postgresql.BYTEA(), nullable=False),
        # NULL for FEE lines: the fee is native ETH paid to the network, not to an address.
        sa.Column("to_address", postgresql.BYTEA(), nullable=True),
        sa.Column("asset_address", postgresql.BYTEA(), nullable=True),
        sa.Column("amount", sa.Numeric(78, 0), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("day", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "classification IN ('INTERNAL_TRANSFER', 'CONVERSION', 'EXTERNAL_EXPENSE', "
            "'LENDING_TRANSFER', 'FEE')",
            name="ck_reconciliation_lines_classification",
        ),
        sa.CheckConstraint("amount >= 0", name="ck_reconciliation_lines_amount"),
        sa.ForeignKeyConstraint(["reconciliation_id"], ["reconciliations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["operation_id"], ["operations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reconciliation_id",
            "transaction_id",
            "classification",
            name="uq_reconciliation_lines_tx_class",
        ),
    )


def downgrade() -> None:
    op.drop_table("reconciliation_lines")
    op.drop_index("ix_reconciliations_org_status", table_name="reconciliations")
    op.drop_table("reconciliations")
