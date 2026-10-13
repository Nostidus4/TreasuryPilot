"""create mandate, payee and exception schema

Revision ID: 20261013_0008
Revises: 20261013_0007
Create Date: 2026-10-13 12:00:00

"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0008"
down_revision: str | None = "20261013_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUMS = {
    "mandate_version_status": (
        "Draft",
        "PendingActivation",
        "Active",
        "Superseded",
        "Expired",
        "Revoked",
        "Discrepancy",
    ),
    "governance_tx_purpose": (
        "MODULE_SETUP",
        "MANDATE",
        "PAYEE_ADD",
        "PAYEE_DEACTIVATE",
        "EXCEPTION_GRANT",
        "EXCEPTION_REVOKE",
        "ALLOW_DUPLICATE",
        "CANCEL_REQUEST",
        "PAUSE",
        "RESUME",
        "REVOKE",
        "GUARDIAN_SETUP",
    ),
    "governance_tx_status": (
        "Collecting",
        "Ready",
        "Submitted",
        "Executed",
        "Failed",
        "Superseded",
        "Cancelled",
    ),
    "payee_status": (
        "Proposed",
        "Screening",
        "ScreeningFailed",
        "AwaitingOwner",
        "Cooling",
        "Active",
        "Deactivated",
    ),
    "payee_oob_method": ("PHONE", "IN_PERSON", "SIGNED_LETTER", "OTHER"),
    "screening_result": ("CLEAR", "HIT", "ERROR"),
    "exception_status": (
        "Requested",
        "Proposed",
        "Granted",
        "Consumed",
        "Expired",
        "Invalidated",
        "Rejected",
        "Revoked",
    ),
    "guardian_setup_status": ("Pending", "Active", "Superseded"),
    "fee_preset": ("ECONOMY", "NORMAL", "FAST"),
    "onchain_pause_status": ("NotRequested", "Requested", "Effective"),
}

MONEY = sa.Numeric(precision=78, scale=0)


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _uuid(name: str, *, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def _at(name: str, *, default: bool = False) -> sa.Column[object]:
    if default:
        return sa.Column(
            name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        )
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _audit_columns(table: str, *, version_name: str = "version") -> list[Any]:
    return [
        _at("created_at", default=True),
        _uuid("created_by", nullable=True),
        _at("updated_at", default=True),
        _uuid("updated_by", nullable=True),
        sa.Column(version_name, sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(f"{version_name} > 0", name=f"ck_{table}_{version_name}"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    ]


def _treasury_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["treasury_id", "org_id"],
        ["treasuries.id", "treasuries.org_id"],
        name=f"fk_{table}_treasury_org",
        ondelete="CASCADE",
    )


def _governance_tx_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column, "org_id"],
        ["governance_txs.id", "governance_txs.org_id"],
        name=f"fk_{table}_{column}",
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=False)

    op.create_table(
        "vendors",
        _uuid("id"),
        _uuid("org_id"),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_ref", sa.String(length=200), nullable=False),
        sa.Column("tax_id", sa.String(length=64), nullable=True),
        sa.Column("contact_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit_columns("vendors"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_vendors_name"),
        sa.CheckConstraint("length(btrim(normalized_ref)) > 0", name="ck_vendors_normalized_ref"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "normalized_ref", name="uq_vendors_org_ref"),
        sa.UniqueConstraint("id", "org_id", name="uq_vendors_id_org"),
    )

    op.create_table(
        "governance_txs",
        _uuid("id"),
        _uuid("org_id"),
        _uuid("treasury_id"),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("safe_address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("purpose", _enum("governance_tx_purpose"), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        _uuid("entity_id", nullable=True),
        sa.Column("calls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("to", sa.LargeBinary(length=20), nullable=False),
        sa.Column("value", MONEY, nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("operation", sa.SmallInteger(), nullable=False),
        sa.Column("safe_nonce", sa.BigInteger(), nullable=False),
        sa.Column("safe_tx_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("threshold", sa.SmallInteger(), nullable=False),
        sa.Column("owners_snapshot", postgresql.ARRAY(sa.LargeBinary(length=20)), nullable=False),
        sa.Column(
            "status",
            _enum("governance_tx_status"),
            server_default="Collecting",
            nullable=False,
        ),
        sa.Column("exec_tx_hash", sa.LargeBinary(length=32), nullable=True),
        *_audit_columns("governance_txs"),
        sa.CheckConstraint(
            "octet_length(safe_address) = 20", name="ck_governance_txs_safe_address_length"
        ),
        sa.CheckConstraint('octet_length("to") = 20', name="ck_governance_txs_to_length"),
        sa.CheckConstraint("jsonb_typeof(calls) = 'array'", name="ck_governance_txs_calls_array"),
        sa.CheckConstraint("value >= 0", name="ck_governance_txs_value"),
        sa.CheckConstraint("operation IN (0, 1)", name="ck_governance_txs_operation"),
        sa.CheckConstraint("safe_nonce >= 0", name="ck_governance_txs_safe_nonce"),
        sa.CheckConstraint(
            "octet_length(safe_tx_hash) = 32", name="ck_governance_txs_safe_tx_hash_length"
        ),
        sa.CheckConstraint(
            "threshold > 0 AND threshold <= cardinality(owners_snapshot)",
            name="ck_governance_txs_threshold",
        ),
        sa.CheckConstraint(
            "exec_tx_hash IS NULL OR octet_length(exec_tx_hash) = 32",
            name="ck_governance_txs_exec_tx_hash_length",
        ),
        _treasury_fk("governance_txs"),
        sa.ForeignKeyConstraint(
            ["treasury_id", "chain_id"],
            ["treasuries.id", "treasuries.chain_id"],
            name="fk_governance_txs_treasury_chain",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "org_id", name="uq_governance_txs_id_org"),
    )
    op.create_index("ix_governance_txs_org_treasury", "governance_txs", ["org_id", "treasury_id"])
    # M03-D5: one open governance tx per Safe nonce; the next change queues at nonce + 1.
    op.create_index(
        "uq_governance_txs_open_nonce",
        "governance_txs",
        ["chain_id", "safe_address", "safe_nonce"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('Collecting'::governance_tx_status, 'Ready'::governance_tx_status, "
            "'Submitted'::governance_tx_status)"
        ),
    )

    op.create_table(
        "governance_signatures",
        _uuid("id"),
        _uuid("org_id"),
        _uuid("governance_tx_id"),
        sa.Column("owner_address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        _uuid("signed_by_user", nullable=True),
        _at("at", default=True),
        sa.CheckConstraint(
            "octet_length(owner_address) = 20", name="ck_governance_signatures_owner_length"
        ),
        sa.CheckConstraint(
            "octet_length(signature) >= 65", name="ck_governance_signatures_signature_length"
        ),
        sa.ForeignKeyConstraint(
            ["governance_tx_id", "org_id"],
            ["governance_txs.id", "governance_txs.org_id"],
            name="fk_governance_signatures_tx_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["signed_by_user"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "governance_tx_id", "owner_address", name="uq_governance_signatures_tx_owner"
        ),
    )

    op.create_index(
        "ix_governance_signatures_org_tx",
        "governance_signatures",
        ["org_id", "governance_tx_id"],
    )

    op.create_table(
        "mandate_versions",
        _uuid("id"),
        _uuid("org_id"),
        _uuid("treasury_id"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("onchain_version", sa.BigInteger(), nullable=True),
        sa.Column(
            "status", _enum("mandate_version_status"), server_default="Draft", nullable=False
        ),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config_hash", sa.LargeBinary(length=32), nullable=False),
        _uuid("governance_tx_id", nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _uuid("created_by"),
        _at("created_at", default=True),
        _at("activated_at"),
        sa.CheckConstraint("version > 0", name="ck_mandate_versions_version"),
        sa.CheckConstraint(
            "onchain_version IS NULL OR onchain_version > 0",
            name="ck_mandate_versions_onchain_version",
        ),
        sa.CheckConstraint("jsonb_typeof(config) = 'object'", name="ck_mandate_versions_config"),
        sa.CheckConstraint(
            "octet_length(config_hash) = 32", name="ck_mandate_versions_config_hash_length"
        ),
        sa.CheckConstraint("expires_at > valid_from", name="ck_mandate_versions_validity"),
        sa.CheckConstraint(
            "status <> 'Active'::mandate_version_status "
            "OR (onchain_version IS NOT NULL AND activated_at IS NOT NULL)",
            name="ck_mandate_versions_active",
        ),
        _treasury_fk("mandate_versions"),
        _governance_tx_fk("mandate_versions", "governance_tx_id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="NO ACTION"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("treasury_id", "version", name="uq_mandate_versions_treasury_version"),
        sa.UniqueConstraint("id", "org_id", name="uq_mandate_versions_id_org"),
    )
    op.create_index(
        "ix_mandate_versions_org_treasury", "mandate_versions", ["org_id", "treasury_id"]
    )

    op.create_table(
        "mandate_status_events",
        _uuid("id"),
        _uuid("org_id"),
        _uuid("mandate_version_id"),
        sa.Column("from_status", _enum("mandate_version_status"), nullable=True),
        sa.Column("to_status", _enum("mandate_version_status"), nullable=False),
        sa.Column("tx_hash", sa.LargeBinary(length=32), nullable=True),
        _at("at", default=True),
        _uuid("by_user_id", nullable=True),
        sa.CheckConstraint(
            "tx_hash IS NULL OR octet_length(tx_hash) = 32",
            name="ck_mandate_status_events_tx_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["mandate_version_id", "org_id"],
            ["mandate_versions.id", "mandate_versions.org_id"],
            name="fk_mandate_status_events_version_org",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["by_user_id"], ["users.id"], ondelete="NO ACTION"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mandate_status_events_org_version_at",
        "mandate_status_events",
        ["org_id", "mandate_version_id", "at"],
    )

    op.create_table(
        "payees",
        _uuid("id"),
        _uuid("org_id"),
        _uuid("treasury_id"),
        _uuid("vendor_id"),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("status", _enum("payee_status"), server_default="Proposed", nullable=False),
        _at("active_from"),
        _uuid("oob_verified_by", nullable=True),
        _at("oob_verified_at"),
        sa.Column("oob_method", _enum("payee_oob_method"), nullable=True),
        sa.Column("oob_note", sa.Text(), nullable=True),
        _uuid("registration_tx_id", nullable=True),
        _at("deactivated_at"),
        *_audit_columns("payees"),
        sa.CheckConstraint("length(btrim(label)) > 0", name="ck_payees_label"),
        sa.CheckConstraint("octet_length(address) = 20", name="ck_payees_address_length"),
        sa.CheckConstraint(
            "(oob_verified_by IS NULL AND oob_verified_at IS NULL AND oob_method IS NULL "
            "AND oob_note IS NULL) OR (oob_verified_by IS NOT NULL "
            "AND oob_verified_at IS NOT NULL AND oob_method IS NOT NULL "
            "AND length(btrim(oob_note)) > 0)",
            name="ck_payees_oob",
        ),
        sa.CheckConstraint(
            "status NOT IN ('Cooling'::payee_status, 'Active'::payee_status) "
            "OR (oob_verified_at IS NOT NULL AND active_from IS NOT NULL)",
            name="ck_payees_registered",
        ),
        sa.CheckConstraint(
            "status <> 'Deactivated'::payee_status OR deactivated_at IS NOT NULL",
            name="ck_payees_deactivated",
        ),
        _treasury_fk("payees"),
        sa.ForeignKeyConstraint(
            ["vendor_id", "org_id"],
            ["vendors.id", "vendors.org_id"],
            name="fk_payees_vendor_org",
            ondelete="RESTRICT",
        ),
        _governance_tx_fk("payees", "registration_tx_id"),
        sa.ForeignKeyConstraint(["oob_verified_by"], ["users.id"], ondelete="NO ACTION"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "org_id", name="uq_payees_id_org"),
    )
    op.create_index("ix_payees_org_treasury", "payees", ["org_id", "treasury_id"])
    op.create_index("ix_payees_vendor", "payees", ["vendor_id"])
    op.create_index(
        "uq_payees_treasury_address_live",
        "payees",
        ["treasury_id", "address"],
        unique=True,
        postgresql_where=sa.text("status <> 'Deactivated'::payee_status"),
    )

    op.create_table(
        "screenings",
        _uuid("id"),
        _uuid("org_id"),
        _uuid("payee_id", nullable=True),
        sa.Column("address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("result", _enum("screening_result"), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ttl_until", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("octet_length(address) = 20", name="ck_screenings_address_length"),
        sa.CheckConstraint("length(btrim(provider)) > 0", name="ck_screenings_provider"),
        sa.CheckConstraint("ttl_until > checked_at", name="ck_screenings_ttl"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["payee_id", "org_id"],
            ["payees.id", "payees.org_id"],
            name="fk_screenings_payee_org",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_screenings_address_checked", "screenings", ["address", sa.text("checked_at DESC")]
    )
    op.create_index("ix_screenings_org_payee", "screenings", ["org_id", "payee_id"])

    op.create_table(
        "exceptions",
        _uuid("id"),
        _uuid("org_id"),
        _uuid("treasury_id"),
        _uuid("request_id"),
        sa.Column("mandate_onchain_version", sa.BigInteger(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("payee", sa.LargeBinary(length=20), nullable=False),
        sa.Column("expiry", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", _enum("exception_status"), server_default="Requested", nullable=False),
        _uuid("governance_tx_id", nullable=True),
        _uuid("draft_ai_call_id", nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        *_audit_columns("exceptions"),
        sa.CheckConstraint("mandate_onchain_version > 0", name="ck_exceptions_mandate_version"),
        sa.CheckConstraint("amount >= 0", name="ck_exceptions_amount"),
        sa.CheckConstraint("octet_length(payee) = 20", name="ck_exceptions_payee_length"),
        _treasury_fk("exceptions"),
        _governance_tx_fk("exceptions", "governance_tx_id"),
        sa.ForeignKeyConstraint(["draft_ai_call_id"], ["ai_calls.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_exceptions_org_treasury", "exceptions", ["org_id", "treasury_id"])
    # BR-041: at most one live exception per request.
    op.create_index(
        "uq_exceptions_open_request",
        "exceptions",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('Proposed'::exception_status, 'Granted'::exception_status)"
        ),
    )

    op.create_table(
        "guardian_setups",
        _uuid("id"),
        _uuid("org_id"),
        _uuid("treasury_id"),
        sa.Column("guardian_safe", sa.LargeBinary(length=20), nullable=False),
        sa.Column("human_owners", postgresql.ARRAY(sa.LargeBinary(length=20)), nullable=False),
        sa.Column("sentinel_address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("threshold", sa.SmallInteger(), server_default="1", nullable=False),
        _uuid("created_tx_id", nullable=True),
        sa.Column(
            "status", _enum("guardian_setup_status"), server_default="Pending", nullable=False
        ),
        *_audit_columns("guardian_setups"),
        sa.CheckConstraint(
            "octet_length(guardian_safe) = 20", name="ck_guardian_setups_guardian_safe_length"
        ),
        sa.CheckConstraint(
            "cardinality(human_owners) > 0 AND array_position(human_owners, NULL) IS NULL",
            name="ck_guardian_setups_human_owners",
        ),
        sa.CheckConstraint(
            "octet_length(sentinel_address) = 20", name="ck_guardian_setups_sentinel_length"
        ),
        sa.CheckConstraint("threshold = 1", name="ck_guardian_setups_threshold"),
        _treasury_fk("guardian_setups"),
        _governance_tx_fk("guardian_setups", "created_tx_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_guardian_setups_org_treasury", "guardian_setups", ["org_id", "treasury_id"])
    op.create_index(
        "uq_guardian_setups_active",
        "guardian_setups",
        ["treasury_id"],
        unique=True,
        postgresql_where=sa.text("status = 'Active'::guardian_setup_status"),
    )

    op.create_table(
        "treasury_fee_policies",
        _uuid("id"),
        _uuid("org_id"),
        _uuid("treasury_id"),
        sa.Column("preset", _enum("fee_preset"), nullable=False),
        sa.Column("max_fee_multiplier_bps", sa.Integer(), nullable=False),
        sa.Column("tip_percentile", sa.SmallInteger(), nullable=False),
        sa.Column("resend_after_s", sa.Integer(), nullable=False),
        sa.Column("bump_bps", sa.Integer(), nullable=False),
        sa.Column("per_plan_threshold_wei", MONEY, nullable=False),
        sa.Column("daily_budget_wei", MONEY, nullable=False),
        sa.Column("reference_eth_price", MONEY, nullable=False),
        _at("proposed_at", default=True),
        _uuid("accepted_by", nullable=True),
        _at("accepted_at"),
        _at("superseded_at"),
        sa.Column("version", sa.Integer(), nullable=False),
        *_audit_columns("treasury_fee_policies", version_name="row_version"),
        sa.CheckConstraint(
            "max_fee_multiplier_bps > 0", name="ck_treasury_fee_policies_multiplier"
        ),
        sa.CheckConstraint(
            "tip_percentile BETWEEN 0 AND 100", name="ck_treasury_fee_policies_tip_percentile"
        ),
        sa.CheckConstraint("resend_after_s > 0", name="ck_treasury_fee_policies_resend_after"),
        sa.CheckConstraint("bump_bps >= 0", name="ck_treasury_fee_policies_bump"),
        sa.CheckConstraint(
            "per_plan_threshold_wei >= 0", name="ck_treasury_fee_policies_per_plan_threshold"
        ),
        sa.CheckConstraint("daily_budget_wei >= 0", name="ck_treasury_fee_policies_daily_budget"),
        sa.CheckConstraint(
            "reference_eth_price > 0", name="ck_treasury_fee_policies_reference_eth_price"
        ),
        sa.CheckConstraint(
            "(accepted_by IS NULL) = (accepted_at IS NULL)",
            name="ck_treasury_fee_policies_acceptance",
        ),
        sa.CheckConstraint(
            "superseded_at IS NULL OR accepted_at IS NOT NULL",
            name="ck_treasury_fee_policies_superseded",
        ),
        sa.CheckConstraint("version > 0", name="ck_treasury_fee_policies_version"),
        _treasury_fk("treasury_fee_policies"),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"], ondelete="NO ACTION"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("treasury_id", "version", name="uq_treasury_fee_policies_version"),
    )
    op.create_index(
        "ix_treasury_fee_policies_org_treasury",
        "treasury_fee_policies",
        ["org_id", "treasury_id"],
    )
    op.create_index(
        "uq_treasury_fee_policies_active",
        "treasury_fee_policies",
        ["treasury_id"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NOT NULL AND superseded_at IS NULL"),
    )

    op.create_table(
        "fee_acceptances",
        _uuid("id"),
        _uuid("org_id"),
        _uuid("plan_id"),
        sa.Column("estimated_fee_wei", MONEY, nullable=False),
        sa.Column("accepted_cap_wei", MONEY, nullable=False),
        _uuid("accepted_by"),
        _at("at", default=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint("estimated_fee_wei >= 0", name="ck_fee_acceptances_estimated_fee"),
        sa.CheckConstraint(
            "accepted_cap_wei >= estimated_fee_wei", name="ck_fee_acceptances_accepted_cap"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"], ondelete="NO ACTION"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fee_acceptances_org_plan", "fee_acceptances", ["org_id", "plan_id"])

    op.create_table(
        "backend_pause",
        _uuid("treasury_id"),
        _uuid("org_id"),
        sa.Column("paused", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "onchain_status",
            _enum("onchain_pause_status"),
            server_default="NotRequested",
            nullable=False,
        ),
        *_audit_columns("backend_pause"),
        sa.CheckConstraint(
            "NOT paused OR length(btrim(reason)) > 0", name="ck_backend_pause_reason"
        ),
        _treasury_fk("backend_pause"),
        sa.PrimaryKeyConstraint("treasury_id"),
    )
    op.create_index("ix_backend_pause_org", "backend_pause", ["org_id"])

    # DATA_MODEL conventions: mandate_versions rows are immutable except their lifecycle
    # columns; only a Draft may be discarded. Comparing whole rows keeps future columns
    # immutable by default.
    op.execute(
        """
        CREATE FUNCTION guard_mandate_version() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            lifecycle CONSTANT text[] := ARRAY[
                'status', 'onchain_version', 'activated_at', 'governance_tx_id'
            ];
        BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION 'mandate_versions cannot be truncated' USING ERRCODE = '55000';
            ELSIF TG_OP = 'DELETE' THEN
                IF OLD.status = 'Draft' THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'only a Draft mandate version can be discarded'
                    USING ERRCODE = '55000';
            END IF;
            -- Without this, Active -> Draft -> DELETE would erase a used version.
            IF NEW.status = 'Draft' AND OLD.status <> 'Draft' THEN
                RAISE EXCEPTION 'a mandate version cannot return to Draft'
                    USING ERRCODE = '55000';
            END IF;
            IF to_jsonb(NEW) - lifecycle IS DISTINCT FROM to_jsonb(OLD) - lifecycle THEN
                RAISE EXCEPTION 'mandate_versions configuration is immutable'
                    USING ERRCODE = '55000';
            END IF;
            -- The bundle is rebuilt while drafting; once it left Draft the link is history.
            IF NEW.governance_tx_id IS DISTINCT FROM OLD.governance_tx_id
                AND OLD.status <> 'Draft' THEN
                RAISE EXCEPTION 'mandate_versions governance_tx_id is fixed after Draft'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER mandate_versions_immutable
        BEFORE UPDATE OR DELETE ON mandate_versions
        FOR EACH ROW EXECUTE FUNCTION guard_mandate_version()
        """
    )
    op.execute(
        """
        CREATE TRIGGER mandate_versions_no_truncate
        BEFORE TRUNCATE ON mandate_versions
        FOR EACH STATEMENT EXECUTE FUNCTION guard_mandate_version()
        """
    )
    # Row-level so a cascade that deletes no events (discarding a Draft) is not rejected.
    op.execute(
        """
        CREATE FUNCTION reject_mandate_status_event_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'mandate_status_events is append-only' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER mandate_status_events_append_only
        BEFORE UPDATE OR DELETE ON mandate_status_events
        FOR EACH ROW EXECUTE FUNCTION reject_mandate_status_event_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER mandate_status_events_no_truncate
        BEFORE TRUNCATE ON mandate_status_events
        FOR EACH STATEMENT EXECUTE FUNCTION reject_mandate_status_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER mandate_status_events_no_truncate ON mandate_status_events")
    op.execute("DROP TRIGGER mandate_status_events_append_only ON mandate_status_events")
    op.execute("DROP FUNCTION reject_mandate_status_event_mutation()")
    op.execute("DROP TRIGGER mandate_versions_no_truncate ON mandate_versions")
    op.execute("DROP TRIGGER mandate_versions_immutable ON mandate_versions")
    op.execute("DROP FUNCTION guard_mandate_version()")

    for table in (
        "backend_pause",
        "fee_acceptances",
        "treasury_fee_policies",
        "guardian_setups",
        "exceptions",
        "screenings",
        "payees",
        "mandate_status_events",
        "mandate_versions",
        "governance_signatures",
        "governance_txs",
        "vendors",
    ):
        op.drop_table(table)  # indexes go with their table

    bind = op.get_bind()
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)
