"""add post-condition verifications and verification-sourced circuit-breaker signals

Revision ID: 20261015_0067
Revises: 20261015_0066
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0067"
down_revision: str | None = "20261015_0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("expected", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("observed", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("diffs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "result IN ('PASSED', 'DISCREPANCY', 'UNKNOWN')", name="ck_verifications_result"
        ),
        sa.ForeignKeyConstraint(["operation_id"], ["operations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_verifications_operation_at", "verifications", ["operation_id", "at"])
    # One verdict per operation, so concurrent verifiers cannot raise duplicate breaker signals.
    op.create_index(
        "uq_verifications_operation_verdict",
        "verifications",
        ["operation_id"],
        unique=True,
        postgresql_where=sa.text("result <> 'UNKNOWN'"),
    )
    op.execute(
        """
        CREATE FUNCTION reject_verification_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'verifications is append-only' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER verifications_append_only BEFORE UPDATE OR DELETE ON verifications "
        "FOR EACH ROW EXECUTE FUNCTION reject_verification_mutation()"
    )

    # A DISCREPANCY trips the same breaker the indexer feeds, without a token movement.
    op.alter_column("chain_safety_signals", "observed_event_id", nullable=True)
    op.alter_column("chain_safety_signals", "token_movement_id", nullable=True)
    op.add_column(
        "chain_safety_signals",
        sa.Column("verification_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_chain_safety_signals_verification",
        "chain_safety_signals",
        "verifications",
        ["verification_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_chain_safety_signals_verification_type",
        "chain_safety_signals",
        ["verification_id", "signal_type"],
    )
    op.create_check_constraint(
        "ck_chain_safety_signals_source",
        "chain_safety_signals",
        "(token_movement_id IS NOT NULL AND observed_event_id IS NOT NULL) "
        "OR verification_id IS NOT NULL",
    )


def downgrade() -> None:
    op.execute("DELETE FROM chain_safety_signals WHERE verification_id IS NOT NULL")
    op.drop_constraint("ck_chain_safety_signals_source", "chain_safety_signals", type_="check")
    op.drop_constraint(
        "uq_chain_safety_signals_verification_type", "chain_safety_signals", type_="unique"
    )
    op.drop_constraint("fk_chain_safety_signals_verification", "chain_safety_signals", "foreignkey")
    op.drop_column("chain_safety_signals", "verification_id")
    op.alter_column("chain_safety_signals", "token_movement_id", nullable=False)
    op.alter_column("chain_safety_signals", "observed_event_id", nullable=False)
    op.execute("DROP TRIGGER verifications_append_only ON verifications")
    op.execute("DROP FUNCTION reject_verification_mutation()")
    op.drop_index("uq_verifications_operation_verdict", table_name="verifications")
    op.drop_index("ix_verifications_operation_at", table_name="verifications")
    op.drop_table("verifications")
