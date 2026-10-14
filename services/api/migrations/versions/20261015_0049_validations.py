"""create append-only validations (M08 §4.2, POL-007)

Revision ID: 20261015_0049
Revises: 20261015_0047
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0049"
down_revision: str | None = "20261015_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "validations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # shortcut: no FK yet because the plans table does not exist; add it with the plans ticket.
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_seq", sa.Integer(), nullable=True),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("primary_code", sa.String(length=64), nullable=True),
        sa.Column("reason_codes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("warnings", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("checks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_version", postgresql.BYTEA(), nullable=False),
        sa.Column("snapshot_block", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "stage IN ('PLAN', 'PRE_STEP', 'SIMULATION')", name="ck_validations_stage"
        ),
        sa.CheckConstraint(
            "decision IN ('ALLOW', 'NEEDS_APPROVAL', 'BLOCK')", name="ck_validations_decision"
        ),
        sa.CheckConstraint(
            "(stage = 'PLAN') = (step_seq IS NULL)", name="ck_validations_step_seq_stage"
        ),
    )
    op.create_index("ix_validations_plan_id", "validations", ["plan_id", "created_at"])
    op.execute(
        """
        CREATE FUNCTION validations_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'validations is append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER validations_append_only
        BEFORE UPDATE OR DELETE OR TRUNCATE ON validations
        FOR EACH STATEMENT EXECUTE FUNCTION validations_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER validations_append_only ON validations")
    op.execute("DROP FUNCTION validations_append_only()")
    op.drop_index("ix_validations_plan_id", table_name="validations")
    op.drop_table("validations")
