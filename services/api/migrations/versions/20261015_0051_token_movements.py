"""persist indexed token movements and safety signals

Revision ID: 20261015_0051
Revises: 20261015_0050
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0051"
down_revision: str | None = "20261015_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "token_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wallet", sa.LargeBinary(length=20), nullable=False),
        sa.Column("direction", sa.String(length=3), nullable=False),
        sa.Column("counterparty", sa.LargeBinary(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("class", sa.String(length=32), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("removed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledgement_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("octet_length(wallet) = 20", name="ck_token_movements_wallet"),
        sa.CheckConstraint(
            "octet_length(counterparty) = 20", name="ck_token_movements_counterparty"
        ),
        sa.CheckConstraint("amount >= 0", name="ck_token_movements_amount"),
        sa.CheckConstraint("direction IN ('IN', 'OUT')", name="ck_token_movements_direction"),
        sa.CheckConstraint(
            "\"class\" IN ('AGENT', 'INTERNAL_REFILL', 'INFLOW', 'UNEXPECTED_OUTFLOW', 'LENDING')",
            name="ck_token_movements_class",
        ),
        sa.CheckConstraint(
            "(acknowledged_by IS NULL AND acknowledged_at IS NULL "
            "AND acknowledgement_reason IS NULL) OR "
            "(acknowledged_at IS NOT NULL AND acknowledgement_reason IS NOT NULL "
            "AND length(btrim(acknowledgement_reason)) > 0)",
            name="ck_token_movements_acknowledgement",
        ),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["event_id"], ["observed_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["operation_id"], ["operations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_token_movements_event"),
    )
    op.create_index(
        "ix_token_movements_treasury_created",
        "token_movements",
        ["treasury_id", "created_at"],
    )
    op.create_index(
        "ix_token_movements_unacknowledged_outflow",
        "token_movements",
        ["treasury_id", "created_at"],
        postgresql_where=sa.text("\"class\" = 'UNEXPECTED_OUTFLOW' AND acknowledged_at IS NULL"),
    )

    op.create_table(
        "chain_safety_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observed_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_movement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_type", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "signal_type IN ('PRE_STEP_REVALIDATION', 'CIRCUIT_BREAKER')",
            name="ck_chain_safety_signals_type",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_chain_safety_signals_payload_object"
        ),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["observed_event_id"], ["observed_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["token_movement_id"], ["token_movements.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "token_movement_id", "signal_type", name="uq_chain_safety_signals_movement_type"
        ),
    )
    op.create_index(
        "ix_chain_safety_signals_pending",
        "chain_safety_signals",
        ["treasury_id", "created_at"],
        postgresql_where=sa.text("invalidated_at IS NULL AND consumed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_chain_safety_signals_pending", table_name="chain_safety_signals")
    op.drop_table("chain_safety_signals")
    op.drop_index("ix_token_movements_unacknowledged_outflow", table_name="token_movements")
    op.drop_index("ix_token_movements_treasury_created", table_name="token_movements")
    op.drop_table("token_movements")
