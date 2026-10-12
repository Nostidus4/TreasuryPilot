"""create mandate, governance, payee and fee policy schema

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

_MANDATE_STATUSES = (
    "'Draft', 'PendingActivation', 'Active', 'Superseded', 'Expired', 'Revoked', 'Discrepancy'"
)
_GOVERNANCE_STATUSES = (
    "'Collecting', 'Ready', 'Submitted', 'Executed', 'Failed', 'Superseded', 'Cancelled'"
)
_PAYEE_STATUSES = "'Proposed', 'Screening', 'ScreeningFailed', 'AwaitingOwner', 'Cooling', 'Active', 'Deactivated'"
_EXCEPTION_STATUSES = "'Requested', 'Proposed', 'Granted', 'Consumed', 'Expired', 'Invalidated', 'Rejected', 'Revoked'"
_SCREENING_RESULTS = "'CLEAR', 'HIT', 'ERROR'"
_OOB_METHODS = "'PHONE', 'IN_PERSON', 'SIGNED_LETTER', 'OTHER'"
_FEE_PRESETS = "'ECONOMY', 'NORMAL', 'FAST'"


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_ref", sa.String(length=320), nullable=False),
        sa.Column("tax_id", sa.LargeBinary(), nullable=True),
        sa.Column("contact", sa.LargeBinary(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_vendors_name"),
        sa.CheckConstraint("length(btrim(normalized_ref)) > 0", name="ck_vendors_normalized_ref"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "normalized_ref", name="uq_vendors_org_normalized_ref"),
    )
    op.create_index("ix_vendors_org_id", "vendors", ["org_id"])

    op.create_table(
        "governance_txs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("safe_address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("calls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("to_address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("value", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("operation", sa.SmallInteger(), nullable=False),
        sa.Column("safe_nonce", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("safe_tx_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column("threshold", sa.SmallInteger(), nullable=False),
        sa.Column("owners_snapshot", postgresql.ARRAY(sa.LargeBinary(length=20)), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("exec_tx_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(safe_address) = 20", name="ck_governance_txs_safe_address"
        ),
        sa.CheckConstraint(
            "purpose IN ('MODULE_SETUP', 'MANDATE', 'PAYEE_ADD', 'PAYEE_DEACTIVATE', "
            "'EXCEPTION_GRANT', 'EXCEPTION_REVOKE', 'ALLOW_DUPLICATE', 'CANCEL_REQUEST', "
            "'PAUSE', 'RESUME', 'REVOKE', 'GUARDIAN_SETUP')",
            name="ck_governance_txs_purpose",
        ),
        sa.CheckConstraint(f"status IN ({_GOVERNANCE_STATUSES})", name="ck_governance_txs_status"),
        sa.CheckConstraint("operation IN (0, 1)", name="ck_governance_txs_operation"),
        sa.CheckConstraint("threshold > 0", name="ck_governance_txs_threshold"),
        sa.CheckConstraint("jsonb_typeof(calls) = 'array'", name="ck_governance_txs_calls_array"),
        sa.CheckConstraint(
            "cardinality(owners_snapshot) > 0", name="ck_governance_txs_owners_snapshot_array"
        ),
        sa.CheckConstraint(
            "threshold <= cardinality(owners_snapshot)",
            name="ck_governance_txs_owners_snapshot_threshold",
        ),
        sa.CheckConstraint(
            "array_position(owners_snapshot, NULL) IS NULL",
            name="ck_governance_txs_owners_snapshot_no_null",
        ),
        sa.CheckConstraint(
            "safe_tx_hash IS NULL OR octet_length(safe_tx_hash) = 32",
            name="ck_governance_txs_safe_tx_hash",
        ),
        sa.CheckConstraint(
            "exec_tx_hash IS NULL OR octet_length(exec_tx_hash) = 32",
            name="ck_governance_txs_exec_tx_hash",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "treasury_id", name="uq_governance_txs_id_treasury"),
    )
    op.create_index(
        "ix_governance_txs_treasury_created", "governance_txs", ["treasury_id", "created_at"]
    )
    op.create_index(
        "uq_governance_txs_open_safe_nonce",
        "governance_txs",
        ["safe_address", "safe_nonce"],
        unique=True,
        postgresql_where=sa.text("status IN ('Collecting', 'Ready', 'Submitted')"),
    )

    op.create_table(
        "governance_signatures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("governance_tx_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.Column("signed_by_user", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "octet_length(owner_address) = 20", name="ck_governance_signatures_owner_address"
        ),
        sa.ForeignKeyConstraint(["governance_tx_id"], ["governance_txs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["signed_by_user"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "governance_tx_id", "owner_address", name="uq_governance_signatures_tx_owner"
        ),
    )
    op.create_index("ix_governance_signatures_tx_id", "governance_signatures", ["governance_tx_id"])

    op.create_table(
        "mandate_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("onchain_version", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("governance_tx_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_mandate_versions_version"),
        sa.CheckConstraint(
            "onchain_version IS NULL OR onchain_version >= 0",
            name="ck_mandate_versions_onchain_version",
        ),
        sa.CheckConstraint(f"status IN ({_MANDATE_STATUSES})", name="ck_mandate_versions_status"),
        sa.CheckConstraint(
            "octet_length(config_hash) = 32", name="ck_mandate_versions_config_hash"
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR valid_from IS NULL OR expires_at > valid_from",
            name="ck_mandate_versions_expiry",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["governance_tx_id"], ["governance_txs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "treasury_id", name="uq_mandate_versions_id_treasury"),
        sa.UniqueConstraint("treasury_id", "version", name="uq_mandate_versions_treasury_version"),
    )
    op.create_index(
        "ix_mandate_versions_treasury_status", "mandate_versions", ["treasury_id", "status"]
    )

    op.create_table(
        "mandate_status_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mandate_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from", sa.String(length=24), nullable=True),
        sa.Column("to", sa.String(length=24), nullable=False),
        sa.Column("tx_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["mandate_version_id"], ["mandate_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mandate_status_events_version_at", "mandate_status_events", ["mandate_version_id", "at"]
    )

    op.create_table(
        "payees",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("oob_verified_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("oob_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("oob_method", sa.String(length=24), nullable=True),
        sa.Column("oob_note", sa.Text(), nullable=True),
        sa.Column("registration_tx_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proposed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(btrim(label)) > 0", name="ck_payees_label"),
        sa.CheckConstraint("octet_length(address) = 20", name="ck_payees_address"),
        sa.CheckConstraint(f"status IN ({_PAYEE_STATUSES})", name="ck_payees_status"),
        sa.CheckConstraint(
            "oob_verified_at IS NULL OR oob_verified_by IS NOT NULL",
            name="ck_payees_oob_verification_actor",
        ),
        sa.CheckConstraint(
            "oob_verified_by IS NULL OR oob_method IS NOT NULL", name="ck_payees_oob_method"
        ),
        sa.ForeignKeyConstraint(["oob_verified_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["registration_tx_id"], ["governance_txs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "treasury_id", name="uq_payees_id_treasury"),
    )
    op.create_index("ix_payees_treasury_status", "payees", ["treasury_id", "status"])
    op.create_index(
        "uq_payees_active_treasury_address",
        "payees",
        ["treasury_id", "address"],
        unique=True,
        postgresql_where=sa.text("status != 'Deactivated'"),
    )

    op.create_table(
        "screenings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("address", sa.LargeBinary(length=20), nullable=True),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("source_ref", sa.String(length=300), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ttl_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"result IN ({_SCREENING_RESULTS})", name="ck_screenings_result"),
        sa.CheckConstraint(
            "payee_id IS NOT NULL OR address IS NOT NULL", name="ck_screenings_subject"
        ),
        sa.CheckConstraint(
            "address IS NULL OR octet_length(address) = 20", name="ck_screenings_address"
        ),
        sa.ForeignKeyConstraint(["payee_id"], ["payees.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_screenings_payee_checked", "screenings", ["payee_id", "checked_at"])
    op.create_index(
        "ix_screenings_address_checked", "screenings", ["address", sa.text("checked_at DESC")]
    )

    op.create_table(
        "exceptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mandate_onchain_version", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("payee", sa.LargeBinary(length=20), nullable=False),
        sa.Column("expiry", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("governance_tx_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("draft_ai_call_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("mandate_onchain_version >= 0", name="ck_exceptions_mandate_version"),
        sa.CheckConstraint("amount > 0", name="ck_exceptions_amount_positive"),
        sa.CheckConstraint("octet_length(payee) = 20", name="ck_exceptions_payee_address"),
        sa.CheckConstraint(f"status IN ({_EXCEPTION_STATUSES})", name="ck_exceptions_status"),
        sa.ForeignKeyConstraint(["governance_tx_id"], ["governance_txs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_exceptions_open_request",
        "exceptions",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('Proposed', 'Granted')"),
    )
    op.create_index("ix_exceptions_status_expiry", "exceptions", ["status", "expiry"])

    op.create_table(
        "guardian_setups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guardian_safe", sa.LargeBinary(length=20), nullable=False),
        sa.Column("human_owners", postgresql.ARRAY(sa.LargeBinary(length=20)), nullable=False),
        sa.Column("sentinel_address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("threshold", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("created_tx_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("octet_length(guardian_safe) = 20", name="ck_guardian_setups_safe"),
        sa.CheckConstraint("cardinality(human_owners) > 0", name="ck_guardian_setups_human_owners"),
        sa.CheckConstraint(
            "array_position(human_owners, NULL) IS NULL", name="ck_guardian_setups_no_null_owners"
        ),
        sa.CheckConstraint(
            "octet_length(sentinel_address) = 20", name="ck_guardian_setups_sentinel"
        ),
        sa.CheckConstraint("threshold = 1", name="ck_guardian_setups_threshold"),
        sa.CheckConstraint(
            "status IN ('Pending', 'Active', 'Failed', 'Revoked')", name="ck_guardian_setups_status"
        ),
        sa.ForeignKeyConstraint(["created_tx_id"], ["governance_txs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "treasury_id", name="uq_guardian_setups_id_treasury"),
    )
    op.create_index(
        "uq_guardian_setups_active_treasury",
        "guardian_setups",
        ["treasury_id"],
        unique=True,
        postgresql_where=sa.text("status = 'Active'"),
    )

    op.create_table(
        "treasury_fee_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preset", sa.String(length=16), nullable=False),
        sa.Column("max_fee_multiplier_bps", sa.Integer(), nullable=False),
        sa.Column("tip_percentile", sa.SmallInteger(), nullable=False),
        sa.Column("resend_after_s", sa.Integer(), nullable=False),
        sa.Column("bump_bps", sa.Integer(), nullable=False),
        sa.Column("per_plan_threshold_wei", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("daily_budget_wei", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("reference_eth_price", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(f"preset IN ({_FEE_PRESETS})", name="ck_treasury_fee_policies_preset"),
        sa.CheckConstraint(
            "max_fee_multiplier_bps > 0", name="ck_treasury_fee_policies_multiplier"
        ),
        sa.CheckConstraint(
            "tip_percentile BETWEEN 0 AND 100", name="ck_treasury_fee_policies_tip_percentile"
        ),
        sa.CheckConstraint("resend_after_s >= 0", name="ck_treasury_fee_policies_resend_after"),
        sa.CheckConstraint("bump_bps >= 0", name="ck_treasury_fee_policies_bump"),
        sa.CheckConstraint(
            "per_plan_threshold_wei >= 0", name="ck_treasury_fee_policies_plan_threshold"
        ),
        sa.CheckConstraint("daily_budget_wei >= 0", name="ck_treasury_fee_policies_daily_budget"),
        sa.CheckConstraint("reference_eth_price >= 0", name="ck_treasury_fee_policies_eth_price"),
        sa.CheckConstraint("version > 0", name="ck_treasury_fee_policies_version"),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_treasury_fee_policies_active",
        "treasury_fee_policies",
        ["treasury_id"],
        unique=True,
        postgresql_where=sa.text("active"),
    )
    op.create_index(
        "ix_treasury_fee_policies_treasury_version",
        "treasury_fee_policies",
        ["treasury_id", "version"],
    )

    op.create_table(
        "fee_acceptances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("estimated_fee_wei", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("accepted_cap_wei", sa.Numeric(precision=78, scale=0), nullable=False),
        sa.Column("accepted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.CheckConstraint("estimated_fee_wei >= 0", name="ck_fee_acceptances_estimated_fee"),
        sa.CheckConstraint("accepted_cap_wei >= estimated_fee_wei", name="ck_fee_acceptances_cap"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_fee_acceptances_reason"),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fee_acceptances_plan_at", "fee_acceptances", ["plan_id", "at"])

    op.create_table(
        "backend_pause",
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("onchain_status", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "onchain_status IN ('NotRequested', 'Requested', 'Effective')",
            name="ck_backend_pause_onchain_status",
        ),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_backend_pause_reason"),
        sa.ForeignKeyConstraint(["by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["treasury_id"], ["treasuries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("treasury_id"),
    )

    op.execute(
        """
        CREATE FUNCTION reject_mandate_version_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'mandate_versions rows cannot be deleted' USING ERRCODE = '55000';
            END IF;
            IF (to_jsonb(NEW) - ARRAY['status', 'onchain_version', 'activated_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status', 'onchain_version', 'activated_at']) THEN
                RAISE EXCEPTION 'mandate_versions configuration is immutable' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_mandate_versions_immutable
        BEFORE UPDATE OR DELETE ON mandate_versions
        FOR EACH ROW EXECUTE FUNCTION reject_mandate_version_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_mandate_status_event_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'mandate_status_events are append-only' USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_mandate_status_events_append_only
        BEFORE UPDATE OR DELETE ON mandate_status_events
        FOR EACH ROW EXECUTE FUNCTION reject_mandate_status_event_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_mandate_status_events_append_only ON mandate_status_events"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_mandate_status_event_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_mandate_versions_immutable ON mandate_versions")
    op.execute("DROP FUNCTION IF EXISTS reject_mandate_version_mutation()")
    op.drop_table("backend_pause")
    op.drop_index("ix_fee_acceptances_plan_at", table_name="fee_acceptances")
    op.drop_table("fee_acceptances")
    op.drop_index("ix_treasury_fee_policies_treasury_version", table_name="treasury_fee_policies")
    op.drop_index("uq_treasury_fee_policies_active", table_name="treasury_fee_policies")
    op.drop_table("treasury_fee_policies")
    op.drop_index("uq_guardian_setups_active_treasury", table_name="guardian_setups")
    op.drop_table("guardian_setups")
    op.drop_index("ix_exceptions_status_expiry", table_name="exceptions")
    op.drop_index("uq_exceptions_open_request", table_name="exceptions")
    op.drop_table("exceptions")
    op.drop_index("ix_screenings_address_checked", table_name="screenings")
    op.drop_index("ix_screenings_payee_checked", table_name="screenings")
    op.drop_table("screenings")
    op.drop_index("uq_payees_active_treasury_address", table_name="payees")
    op.drop_index("ix_payees_treasury_status", table_name="payees")
    op.drop_table("payees")
    op.drop_index("ix_mandate_status_events_version_at", table_name="mandate_status_events")
    op.drop_table("mandate_status_events")
    op.drop_index("ix_mandate_versions_treasury_status", table_name="mandate_versions")
    op.drop_table("mandate_versions")
    op.drop_index("ix_governance_signatures_tx_id", table_name="governance_signatures")
    op.drop_table("governance_signatures")
    op.drop_index("uq_governance_txs_open_safe_nonce", table_name="governance_txs")
    op.drop_index("ix_governance_txs_treasury_created", table_name="governance_txs")
    op.drop_table("governance_txs")
    op.drop_index("ix_vendors_org_id", table_name="vendors")
    op.drop_table("vendors")
