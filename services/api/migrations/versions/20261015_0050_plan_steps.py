"""persist the signed plan fields needed by the live timeline

Revision ID: 20261015_0050
Revises: 20261015_0049
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0050"
down_revision: str | None = "20261015_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attestation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("step_id", postgresql.BYTEA(), nullable=False),
        sa.Column("action", sa.Integer(), nullable=False),
        sa.Column("request_id", postgresql.BYTEA(), nullable=False),
        sa.Column("treasury_address", postgresql.BYTEA(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("from_address", postgresql.BYTEA(), nullable=False),
        sa.Column("to_address", postgresql.BYTEA(), nullable=False),
        sa.Column("asset_address", postgresql.BYTEA(), nullable=False),
        sa.Column("amount", sa.Numeric(78, 0), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("seq >= 0", name="ck_plan_steps_seq_nonnegative"),
        sa.CheckConstraint("action BETWEEN 1 AND 5", name="ck_plan_steps_action"),
        sa.CheckConstraint("octet_length(step_id) = 32", name="ck_plan_steps_step_id_length"),
        sa.CheckConstraint("octet_length(request_id) = 32", name="ck_plan_steps_request_id_length"),
        sa.CheckConstraint(
            "octet_length(treasury_address) = 20", name="ck_plan_steps_treasury_length"
        ),
        sa.CheckConstraint("octet_length(from_address) = 20", name="ck_plan_steps_from_length"),
        sa.CheckConstraint("octet_length(to_address) = 20", name="ck_plan_steps_to_length"),
        sa.CheckConstraint("octet_length(asset_address) = 20", name="ck_plan_steps_asset_length"),
        sa.CheckConstraint("amount >= 0", name="ck_plan_steps_amount_nonnegative"),
        sa.ForeignKeyConstraint(["attestation_id"], ["attestations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attestation_id", "seq", name="uq_plan_steps_attestation_seq"),
        sa.UniqueConstraint("attestation_id", "step_id", name="uq_plan_steps_attestation_step"),
    )
    op.create_index("ix_plan_steps_plan", "plan_steps", ["plan_id", "seq"])
    op.create_index("ix_plan_steps_treasury", "plan_steps", ["chain_id", "treasury_address"])
    op.execute(
        """
        CREATE FUNCTION plan_steps_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'plan_steps is append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER plan_steps_append_only
        BEFORE UPDATE OR DELETE OR TRUNCATE ON plan_steps
        FOR EACH STATEMENT EXECUTE FUNCTION plan_steps_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER plan_steps_append_only ON plan_steps")
    op.execute("DROP FUNCTION plan_steps_append_only()")
    op.drop_index("ix_plan_steps_treasury", table_name="plan_steps")
    op.drop_index("ix_plan_steps_plan", table_name="plan_steps")
    op.drop_table("plan_steps")
