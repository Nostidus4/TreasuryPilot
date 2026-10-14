"""add block-consistent chain snapshots (M06 CHR-002)

Revision ID: 20261015_0040
Revises: 20261014_0036
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0040"
down_revision: str | None = "20261014_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("block_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("coverage", sa.String(length=8), nullable=False),
        sa.Column("missing", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('PLAN', 'PRE_STEP', 'DASHBOARD', 'READBACK')", name="ck_snapshots_purpose"
        ),
        sa.CheckConstraint("block_number >= 0", name="ck_snapshots_block_number"),
        sa.CheckConstraint("octet_length(block_hash) = 32", name="ck_snapshots_block_hash_length"),
        sa.CheckConstraint(
            "coverage IN ('UNKNOWN', 'PARTIAL', 'COMPLETE')", name="ck_snapshots_coverage"
        ),
        sa.CheckConstraint("jsonb_typeof(data) = 'object'", name="ck_snapshots_data_object"),
        sa.CheckConstraint("jsonb_typeof(missing) = 'array'", name="ck_snapshots_missing_array"),
        sa.ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_snapshots_treasury_org",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_snapshots_treasury_block", "snapshots", ["treasury_id", sa.text("block_number DESC")]
    )
    op.create_index(
        "ix_snapshots_dashboard_observed",
        "snapshots",
        ["observed_at"],
        postgresql_where=sa.text("purpose = 'DASHBOARD'"),
    )
    # Rows are evidence for plans (M06-D7): never edited; only expired DASHBOARD rows are pruned.
    op.execute(
        """
        CREATE FUNCTION guard_snapshots() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND OLD.purpose = 'DASHBOARD' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'snapshots are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER snapshots_immutable
        BEFORE UPDATE OR DELETE ON snapshots
        FOR EACH ROW EXECUTE FUNCTION guard_snapshots()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER snapshots_immutable ON snapshots")
    op.execute("DROP FUNCTION guard_snapshots()")
    op.drop_index("ix_snapshots_dashboard_observed", table_name="snapshots")
    op.drop_index("ix_snapshots_treasury_block", table_name="snapshots")
    op.drop_table("snapshots")
