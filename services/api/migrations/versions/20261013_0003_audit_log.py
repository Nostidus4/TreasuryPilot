"""create append-only per-organization audit log

Revision ID: 20261013_0003
Revises: 20261012_0002
Create Date: 2026-10-13 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0003"
down_revision: str | None = "20261012_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prev_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("hash", sa.LargeBinary(length=32), nullable=False),
        sa.CheckConstraint(
            "actor_type IN ('USER', 'SYSTEM', 'AI', 'CONTRACT')",
            name="ck_audit_log_actor_type",
        ),
        sa.CheckConstraint("length(btrim(action)) > 0", name="ck_audit_log_action"),
        sa.CheckConstraint("length(btrim(entity_type)) > 0", name="ck_audit_log_entity_type"),
        sa.CheckConstraint("octet_length(prev_hash) = 32", name="ck_audit_log_prev_hash_length"),
        sa.CheckConstraint("octet_length(hash) = 32", name="ck_audit_log_hash_length"),
        sa.CheckConstraint("jsonb_typeof(data) = 'object'", name="ck_audit_log_data_object"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("seq"),
    )
    op.create_index("ix_audit_log_org_seq", "audit_log", ["org_id", "seq"])
    op.create_index(
        "ix_audit_log_org_entity_seq",
        "audit_log",
        ["org_id", "entity_type", "entity_id", "seq"],
    )
    op.create_table(
        "audit_heads",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_seq", sa.BigInteger(), nullable=True),
        sa.Column("last_hash", sa.LargeBinary(length=32), nullable=False),
        sa.CheckConstraint("last_seq IS NULL OR last_seq > 0", name="ck_audit_heads_last_seq"),
        sa.CheckConstraint("octet_length(last_hash) = 32", name="ck_audit_heads_hash_length"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("org_id"),
    )
    op.execute(
        """
        CREATE FUNCTION reject_audit_log_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update_or_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_or_delete ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS reject_audit_log_mutation()")
    op.drop_table("audit_heads")
    op.drop_index("ix_audit_log_org_entity_seq", table_name="audit_log")
    op.drop_index("ix_audit_log_org_seq", table_name="audit_log")
    op.drop_table("audit_log")
