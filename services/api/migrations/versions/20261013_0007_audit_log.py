"""create append-only per-organization audit log

Revision ID: 20261013_0007
Revises: 20261013_0006
Create Date: 2026-10-13 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0007"
down_revision: str | None = "20261013_0006"
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
        # Deleting an org removes its unused head; a started chain blocks it (trigger below).
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
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
    # Row triggers never fire on TRUNCATE.
    op.execute(
        """
        CREATE TRIGGER audit_log_no_truncate
        BEFORE TRUNCATE ON audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_log_mutation()
        """
    )
    # A head that has chained records must never disappear: the writer would otherwise
    # have nothing to link to. Only an unused head (last_seq IS NULL) can be deleted.
    op.execute(
        """
        CREATE FUNCTION protect_audit_head() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'TRUNCATE' OR OLD.last_seq IS NOT NULL THEN
                RAISE EXCEPTION 'audit_heads of a started chain cannot be removed'
                    USING ERRCODE = '55000';
            END IF;
            RETURN OLD;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_heads_no_delete
        BEFORE DELETE ON audit_heads
        FOR EACH ROW EXECUTE FUNCTION protect_audit_head()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_heads_no_truncate
        BEFORE TRUNCATE ON audit_heads
        FOR EACH STATEMENT EXECUTE FUNCTION protect_audit_head()
        """
    )
    # Every organization gets its genesis head when it is created, so the writer never
    # creates one on the hot path and a missing head is an error, not a new chain.
    op.execute(
        """
        CREATE FUNCTION create_audit_head() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO audit_heads (org_id, last_seq, last_hash)
            VALUES (NEW.id, NULL, decode(repeat('00', 32), 'hex'));
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER organizations_create_audit_head
        AFTER INSERT ON organizations
        FOR EACH ROW EXECUTE FUNCTION create_audit_head()
        """
    )
    op.execute(
        """
        INSERT INTO audit_heads (org_id, last_seq, last_hash)
        SELECT id, NULL, decode(repeat('00', 32), 'hex') FROM organizations
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS organizations_create_audit_head ON organizations")
    op.execute("DROP FUNCTION IF EXISTS create_audit_head()")
    op.execute("DROP TRIGGER IF EXISTS audit_heads_no_truncate ON audit_heads")
    op.execute("DROP TRIGGER IF EXISTS audit_heads_no_delete ON audit_heads")
    op.execute("DROP FUNCTION IF EXISTS protect_audit_head()")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_or_delete ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS reject_audit_log_mutation()")
    op.drop_table("audit_heads")
    op.drop_index("ix_audit_log_org_entity_seq", table_name="audit_log")
    op.drop_index("ix_audit_log_org_seq", table_name="audit_log")
    op.drop_table("audit_log")
