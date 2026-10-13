"""create append-only attestations (M08 §4.2)

Revision ID: 20261014_0009
Revises: 20261013_0008
Create Date: 2026-10-14 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0009"
down_revision: str | None = "20261013_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attestations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # shortcut: no FK yet because the plans table does not exist; add it with the plans ticket.
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.BYTEA(), nullable=False),
        sa.Column("plan_hash", postgresql.BYTEA(), nullable=False),
        sa.Column("step_ids", postgresql.ARRAY(postgresql.BYTEA()), nullable=False),
        sa.Column("policy_version", postgresql.BYTEA(), nullable=False),
        sa.Column("executor", sa.String(length=42), nullable=False),
        sa.Column("nonce", sa.Numeric(78, 0), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_digest", postgresql.BYTEA(), nullable=False),
        sa.Column("typed_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("signature", postgresql.BYTEA(), nullable=False),
        sa.Column("policy_signer", sa.String(length=42), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        # Replay protection (BR-059): a nonce is issued once.
        sa.UniqueConstraint("nonce", name="uq_attestations_nonce"),
    )
    op.create_index("ix_attestations_plan_id", "attestations", ["plan_id"])
    op.execute(
        """
        CREATE FUNCTION attestations_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'attestations is append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER attestations_append_only
        BEFORE UPDATE OR DELETE OR TRUNCATE ON attestations
        FOR EACH STATEMENT EXECUTE FUNCTION attestations_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER attestations_append_only ON attestations")
    op.execute("DROP FUNCTION attestations_append_only()")
    op.drop_index("ix_attestations_plan_id", table_name="attestations")
    op.drop_table("attestations")
