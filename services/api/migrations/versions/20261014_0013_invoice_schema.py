"""create invoice and payment request schema

Revision ID: 20261014_0013
Revises: 20261013_0012
Create Date: 2026-10-13 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0013"
down_revision: str | None = "20261013_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUEST_STATUSES = (
    "'Draft', 'AwaitingApproval', 'Approved', 'Scheduled', 'Planning', 'AwaitingAuthority', "
    "'Preparing', 'Paying', 'Paid', 'NeedsReview', 'Rejected', 'Cancelled', 'Expired'"
)
_REQUEST_SOURCES = "'MANUAL', 'UPLOAD', 'CSV'"
_CANCEL_STATUSES = "'NotNeeded', 'Pending', 'Confirmed'"
_FLAG_SEVERITIES = "'LOW', 'HIGH'"
_FLAG_SOURCES = "'DETERMINISTIC', 'AI'"
_FLAG_STATUSES = "'Open', 'Acknowledged', 'Superseded'"
_APPROVAL_STATUSES = "'Valid', 'Invalidated', 'Expired', 'Cancelled'"
_EVENT_ACTOR_TYPES = "'USER', 'SYSTEM'"
_TERMINAL_REQUEST_STATUSES = "'Rejected', 'Cancelled', 'Expired'"


def upgrade() -> None:
    # Lets a request pin its vendor to the payee's vendor with one composite FK.
    op.create_unique_constraint(
        "uq_payees_id_treasury_vendor", "payees", ["id", "treasury_id", "vendor_id"]
    )
    op.create_table(
        "payment_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_no", sa.String(length=200), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_at", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paying_wallet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("terms", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("terms_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column("terms_confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("terms_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fingerprint", sa.LargeBinary(length=32), nullable=True),
        sa.Column("invoice_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column("onchain_request_id", sa.LargeBinary(length=32), nullable=True),
        sa.Column("source", sa.String(length=16), server_default="MANUAL", nullable=False),
        sa.Column("extraction_confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("extraction_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="Draft", nullable=False),
        sa.Column("current_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_edited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("cost_center", sa.String(length=120), nullable=True),
        sa.Column(
            "cancel_onchain", sa.String(length=16), server_default="NotNeeded", nullable=False
        ),
        sa.Column("cancel_tx_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(f"status IN ({_REQUEST_STATUSES})", name="ck_payment_requests_status"),
        sa.CheckConstraint(f"source IN ({_REQUEST_SOURCES})", name="ck_payment_requests_source"),
        sa.CheckConstraint(
            f"cancel_onchain IN ({_CANCEL_STATUSES})", name="ck_payment_requests_cancel_status"
        ),
        sa.CheckConstraint("amount > 0", name="ck_payment_requests_amount_positive"),
        sa.CheckConstraint("current_revision > 0", name="ck_payment_requests_revision_positive"),
        sa.CheckConstraint("version > 0", name="ck_payment_requests_version"),
        sa.CheckConstraint(
            "fingerprint IS NULL OR octet_length(fingerprint) = 32",
            name="ck_payment_requests_fingerprint_length",
        ),
        sa.CheckConstraint(
            "invoice_hash IS NULL OR octet_length(invoice_hash) = 32",
            name="ck_payment_requests_invoice_hash_length",
        ),
        sa.CheckConstraint(
            "onchain_request_id IS NULL OR octet_length(onchain_request_id) = 32",
            name="ck_payment_requests_onchain_id_length",
        ),
        sa.CheckConstraint(
            "terms_hash IS NULL OR octet_length(terms_hash) = 32",
            name="ck_payment_requests_terms_hash_length",
        ),
        sa.CheckConstraint(
            "cancel_tx_hash IS NULL OR octet_length(cancel_tx_hash) = 32",
            name="ck_payment_requests_cancel_tx_hash_length",
        ),
        sa.CheckConstraint(
            "terms_confirmed_by IS NULL OR terms_confirmed_at IS NOT NULL",
            name="ck_payment_requests_terms_confirmation_pair",
        ),
        sa.CheckConstraint(
            "extraction_confirmed_by IS NULL OR extraction_confirmed_at IS NOT NULL",
            name="ck_payment_requests_extraction_confirmation_pair",
        ),
        sa.ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_payment_requests_treasury_org",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["treasury_id", "chain_id"],
            ["treasuries.id", "treasuries.chain_id"],
            name="fk_payment_requests_treasury_chain",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payee_id", "treasury_id", "vendor_id"],
            ["payees.id", "payees.treasury_id", "payees.vendor_id"],
            name="fk_payment_requests_payee_treasury_vendor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["vendor_id", "org_id"],
            ["vendors.id", "vendors.org_id"],
            name="fk_payment_requests_vendor_org",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "chain_id"],
            ["assets.id", "assets.chain_id"],
            name="fk_payment_requests_asset_chain",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["paying_wallet_id", "org_id"],
            ["treasury_wallets.id", "treasury_wallets.org_id"],
            name="fk_payment_requests_paying_wallet_org",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["terms_confirmed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["extraction_confirmed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["last_edited_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "treasury_id", name="uq_payment_requests_id_treasury"),
    )
    op.create_index("ix_payment_requests_org_status", "payment_requests", ["org_id", "status"])
    op.create_index(
        "ix_payment_requests_treasury_due", "payment_requests", ["treasury_id", "due_at"]
    )
    op.create_index(
        "uq_payment_requests_active_fingerprint",
        "payment_requests",
        ["treasury_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text(
            f"status NOT IN ({_TERMINAL_REQUEST_STATUSES}) AND fingerprint IS NOT NULL"
        ),
    )

    op.create_table(
        "request_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("edited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint("revision > 0", name="ck_request_revisions_revision_positive"),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'", name="ck_request_revisions_snapshot"
        ),
        sa.ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        # Users are soft-deleted; SET NULL would be rejected by the append-only trigger.
        sa.ForeignKeyConstraint(["edited_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "revision", name="uq_request_revisions_request_revision"),
    )
    op.create_index("ix_request_revisions_request_at", "request_revisions", ["request_id", "at"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("mime", sa.String(length=128), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("pages", sa.SmallInteger(), nullable=True),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(btrim(storage_key)) > 0", name="ck_documents_storage_key"),
        sa.CheckConstraint("octet_length(sha256) = 32", name="ck_documents_sha256_length"),
        sa.CheckConstraint("length(btrim(mime)) > 0", name="ck_documents_mime"),
        sa.CheckConstraint("size > 0", name="ck_documents_size_positive"),
        sa.CheckConstraint("pages IS NULL OR pages > 0", name="ck_documents_pages_positive"),
        sa.ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_documents_storage_key"),
    )
    op.create_index("ix_documents_request", "documents", ["request_id"])

    op.create_table(
        "flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="Open", nullable=False),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ack_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"severity IN ({_FLAG_SEVERITIES})", name="ck_flags_severity"),
        sa.CheckConstraint(f"source IN ({_FLAG_SOURCES})", name="ck_flags_source"),
        sa.CheckConstraint(f"status IN ({_FLAG_STATUSES})", name="ck_flags_status"),
        sa.CheckConstraint("revision > 0", name="ck_flags_revision_positive"),
        sa.CheckConstraint("jsonb_typeof(evidence) = 'object'", name="ck_flags_evidence_object"),
        sa.CheckConstraint(
            "status != 'Acknowledged' OR (acknowledged_by IS NOT NULL AND acknowledged_at IS NOT NULL)",
            name="ck_flags_acknowledgement_actor",
        ),
        sa.ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        # ck_flags_acknowledgement_actor needs the actor, so it cannot be nulled.
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_flags_request_revision_status", "flags", ["request_id", "revision", "status"]
    )

    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("approver_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approver_address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("typed_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.Column(
            "acknowledged_flag_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("solo_mode", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="Valid", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("revision > 0", name="ck_approvals_revision_positive"),
        sa.CheckConstraint(
            "octet_length(approver_address) = 20", name="ck_approvals_address_length"
        ),
        sa.CheckConstraint("jsonb_typeof(typed_data) = 'object'", name="ck_approvals_typed_data"),
        sa.CheckConstraint(f"status IN ({_APPROVAL_STATUSES})", name="ck_approvals_status"),
        sa.CheckConstraint("length(signature) > 0", name="ck_approvals_signature"),
        sa.ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        # Users are soft-deleted; SET NULL would be rejected by the immutability trigger.
        sa.ForeignKeyConstraint(["approver_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id",
            "revision",
            "approver_address",
            name="uq_approvals_request_revision_address",
        ),
    )
    op.create_index("ix_approvals_request_revision", "approvals", ["request_id", "revision"])

    op.create_table(
        "csv_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("rows_total", sa.Integer(), nullable=False),
        sa.Column("rows_created", sa.Integer(), nullable=False),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("octet_length(file_sha256) = 32", name="ck_csv_imports_sha256_length"),
        sa.CheckConstraint("rows_total >= 0", name="ck_csv_imports_rows_total"),
        sa.CheckConstraint(
            "rows_created >= 0 AND rows_created <= rows_total", name="ck_csv_imports_rows_created"
        ),
        sa.CheckConstraint("jsonb_typeof(errors) = 'array'", name="ck_csv_imports_errors_array"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_csv_imports_treasury_org",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_csv_imports_org_created", "csv_imports", ["org_id", "created_at"])

    op.create_table(
        "request_status_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from", sa.String(length=24), nullable=True),
        sa.Column("to", sa.String(length=24), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(f'"to" IN ({_REQUEST_STATUSES})', name="ck_request_status_events_to"),
        sa.CheckConstraint(
            f'"from" IS NULL OR "from" IN ({_REQUEST_STATUSES})',
            name="ck_request_status_events_from",
        ),
        sa.CheckConstraint(
            f"actor_type IN ({_EVENT_ACTOR_TYPES})", name="ck_request_status_events_actor_type"
        ),
        sa.ForeignKeyConstraint(["request_id"], ["payment_requests.id"], ondelete="RESTRICT"),
        # Users are soft-deleted; SET NULL would be rejected by the append-only trigger.
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_request_status_events_request_at", "request_status_events", ["request_id", "at"]
    )

    # exceptions (0003) may already hold rows whose request_id has no payment request.
    # Add the FK NOT VALID so the upgrade cannot fail on them while new rows are
    # still enforced, and validate it right away whenever no such rows exist.
    op.create_foreign_key(
        "fk_exceptions_request_treasury",
        "exceptions",
        "payment_requests",
        ["request_id", "treasury_id"],
        ["id", "treasury_id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM exceptions e
                WHERE NOT EXISTS (
                    SELECT 1 FROM payment_requests r
                    WHERE r.id = e.request_id AND r.treasury_id = e.treasury_id
                )
            ) THEN
                RAISE WARNING 'fk_exceptions_request_treasury left NOT VALID: exceptions '
                    'reference missing payment requests; clean them up and VALIDATE it';
            ELSE
                ALTER TABLE exceptions VALIDATE CONSTRAINT fk_exceptions_request_treasury;
            END IF;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE FUNCTION reject_request_approval_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'approvals are immutable' USING ERRCODE = '55000';
            END IF;
            IF (to_jsonb(NEW) - ARRAY['status']) IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status']) THEN
                RAISE EXCEPTION 'approvals are immutable except for status' USING ERRCODE = '55000';
            END IF;
            -- Only a Valid approval may end; an ended one never counts again.
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                OLD.status = 'Valid' AND NEW.status IN ('Invalidated', 'Expired', 'Cancelled')
            ) THEN
                RAISE EXCEPTION 'approval status cannot change from % to %', OLD.status, NEW.status
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_approvals_immutable
        BEFORE UPDATE OR DELETE ON approvals
        FOR EACH ROW EXECUTE FUNCTION reject_request_approval_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_request_revision_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'request_revisions are append-only' USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_request_revisions_append_only
        BEFORE UPDATE OR DELETE ON request_revisions
        FOR EACH ROW EXECUTE FUNCTION reject_request_revision_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_request_status_event_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'request_status_events are append-only' USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_request_status_events_append_only
        BEFORE UPDATE OR DELETE ON request_status_events
        FOR EACH ROW EXECUTE FUNCTION reject_request_status_event_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_request_status_events_append_only ON request_status_events"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_request_status_event_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_request_revisions_append_only ON request_revisions")
    op.execute("DROP FUNCTION IF EXISTS reject_request_revision_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_approvals_immutable ON approvals")
    op.execute("DROP FUNCTION IF EXISTS reject_request_approval_mutation()")
    op.drop_constraint("fk_exceptions_request_treasury", "exceptions", type_="foreignkey")
    op.drop_index("ix_request_status_events_request_at", table_name="request_status_events")
    op.drop_table("request_status_events")
    op.drop_index("ix_csv_imports_org_created", table_name="csv_imports")
    op.drop_table("csv_imports")
    op.drop_index("ix_approvals_request_revision", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_flags_request_revision_status", table_name="flags")
    op.drop_table("flags")
    op.drop_index("ix_documents_request", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_request_revisions_request_at", table_name="request_revisions")
    op.drop_table("request_revisions")
    op.drop_index("uq_payment_requests_active_fingerprint", table_name="payment_requests")
    op.drop_index("ix_payment_requests_treasury_due", table_name="payment_requests")
    op.drop_index("ix_payment_requests_org_status", table_name="payment_requests")
    op.drop_table("payment_requests")
    op.drop_constraint("uq_payees_id_treasury_vendor", "payees", type_="unique")
