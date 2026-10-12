"""create treasury and chain schema

Revision ID: 20261012_0002
Revises: 20261012_0001
Create Date: 2026-10-12 00:10:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261012_0002"
down_revision: str | None = "20261012_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

treasury_status = postgresql.ENUM(
    "Draft", "ModulePending", "Ready", "Paused", "Revoked", name="treasury_status"
)
treasury_coverage = postgresql.ENUM("UNKNOWN", "PARTIAL", "COMPLETE", name="treasury_coverage")
treasury_wallet_role = postgresql.ENUM("SOURCE", "OPERATIONAL", name="treasury_wallet_role")


def _audit_columns(*, use_row_version: bool = False) -> list[sa.Column[object]]:
    version_name = "row_version" if use_row_version else "version"
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(version_name, sa.Integer(), server_default="1", nullable=False),
    ]


def _audit_foreign_keys() -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    treasury_status.create(bind, checkfirst=False)
    treasury_coverage.create(bind, checkfirst=False)
    treasury_wallet_role.create(bind, checkfirst=False)

    op.create_table(
        "chains",
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_testnet", sa.Boolean(), nullable=False),
        sa.Column("confirmations", sa.SmallInteger(), nullable=False),
        sa.Column("explorer_url", sa.Text(), nullable=False),
        sa.Column("rpc_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint("chain_id > 0", name="ck_chains_chain_id_positive"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_chains_name"),
        sa.CheckConstraint("confirmations >= 0", name="ck_chains_confirmations"),
        sa.CheckConstraint("length(btrim(explorer_url)) > 0", name="ck_chains_explorer_url"),
        sa.CheckConstraint("jsonb_typeof(rpc_urls) = 'array'", name="ck_chains_rpc_urls_array"),
        sa.CheckConstraint("jsonb_array_length(rpc_urls) > 0", name="ck_chains_rpc_urls_not_empty"),
        sa.CheckConstraint("version > 0", name="ck_chains_version"),
        *_audit_foreign_keys(),
        sa.PrimaryKeyConstraint("chain_id"),
    )

    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("address", sa.LargeBinary(length=20), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("decimals", sa.SmallInteger(), nullable=False),
        sa.Column("issuer_label", sa.String(length=120), nullable=False),
        sa.Column("is_test", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_native", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "(is_native AND address IS NULL) OR (NOT is_native AND octet_length(address) = 20)",
            name="ck_assets_address",
        ),
        sa.CheckConstraint("length(btrim(symbol)) > 0", name="ck_assets_symbol"),
        sa.CheckConstraint("decimals BETWEEN 0 AND 255", name="ck_assets_decimals"),
        sa.CheckConstraint("length(btrim(issuer_label)) > 0", name="ck_assets_issuer_label"),
        sa.CheckConstraint("version > 0", name="ck_assets_version"),
        *_audit_foreign_keys(),
        sa.ForeignKeyConstraint(["chain_id"], ["chains.chain_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chain_id", "address", name="uq_assets_chain_address"),
        sa.UniqueConstraint("id", "chain_id", name="uq_assets_id_chain"),
    )
    op.create_index("ix_assets_chain_id", "assets", ["chain_id"])

    op.create_table(
        "deployments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        *_audit_columns(use_row_version=True),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_deployments_name"),
        sa.CheckConstraint("length(btrim(version)) > 0", name="ck_deployments_version_label"),
        sa.CheckConstraint("octet_length(address) = 20", name="ck_deployments_address_length"),
        sa.CheckConstraint("octet_length(code_hash) = 32", name="ck_deployments_code_hash_length"),
        sa.CheckConstraint("row_version > 0", name="ck_deployments_row_version"),
        *_audit_foreign_keys(),
        sa.ForeignKeyConstraint(["chain_id"], ["chains.chain_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chain_id", "name", "version", name="uq_deployments_chain_name_version"
        ),
    )
    op.create_index("ix_deployments_chain_id", "deployments", ["chain_id"])

    op.create_table(
        "treasuries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_address", sa.LargeBinary(length=20), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "Draft",
                "ModulePending",
                "Ready",
                "Paused",
                "Revoked",
                name="treasury_status",
                create_type=False,
            ),
            server_default="Draft",
            nullable=False,
        ),
        sa.Column(
            "coverage",
            postgresql.ENUM(
                "UNKNOWN",
                "PARTIAL",
                "COMPLETE",
                name="treasury_coverage",
                create_type=False,
            ),
            server_default="UNKNOWN",
            nullable=False,
        ),
        sa.Column("coverage_ack_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("coverage_ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_ack_reason", sa.Text(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "module_address IS NULL OR octet_length(module_address) = 20",
            name="ck_treasuries_module_address_length",
        ),
        sa.CheckConstraint(
            "(coverage_ack_by IS NULL AND coverage_ack_at IS NULL "
            "AND coverage_ack_reason IS NULL) OR "
            "(coverage_ack_by IS NOT NULL AND coverage_ack_at IS NOT NULL "
            "AND length(btrim(coverage_ack_reason)) > 0)",
            name="ck_treasuries_coverage_ack",
        ),
        sa.CheckConstraint("version > 0", name="ck_treasuries_version"),
        *_audit_foreign_keys(),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chain_id"], ["chains.chain_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["asset_id", "chain_id"],
            ["assets.id", "assets.chain_id"],
            name="fk_treasuries_asset_chain",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "coverage_ack_by"],
            ["memberships.org_id", "memberships.user_id"],
            name="fk_treasuries_coverage_ack_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["coverage_ack_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "org_id", name="uq_treasuries_id_org"),
    )
    op.create_index("ix_treasuries_org_id", "treasuries", ["org_id"])
    op.create_index("ix_treasuries_chain_id", "treasuries", ["chain_id"])

    op.create_table(
        "treasury_wallets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("treasury_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "SOURCE", "OPERATIONAL", name="treasury_wallet_role", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("safe_address", sa.LargeBinary(length=20), nullable=False),
        sa.Column("owners", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("threshold", sa.SmallInteger(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint("length(btrim(label)) > 0", name="ck_treasury_wallets_label"),
        sa.CheckConstraint(
            "octet_length(safe_address) = 20", name="ck_treasury_wallets_safe_address_length"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(owners) = 'array'", name="ck_treasury_wallets_owners_array"
        ),
        sa.CheckConstraint(
            "jsonb_array_length(owners) > 0", name="ck_treasury_wallets_owners_not_empty"
        ),
        sa.CheckConstraint("threshold > 0", name="ck_treasury_wallets_threshold_positive"),
        sa.CheckConstraint(
            "threshold <= jsonb_array_length(owners)",
            name="ck_treasury_wallets_threshold_owners",
        ),
        sa.CheckConstraint("version > 0", name="ck_treasury_wallets_version"),
        *_audit_foreign_keys(),
        sa.ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_treasury_wallets_treasury_org",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "org_id", name="uq_treasury_wallets_id_org"),
        sa.UniqueConstraint(
            "treasury_id", "safe_address", name="uq_treasury_wallets_treasury_address"
        ),
    )
    op.create_index(
        "ix_treasury_wallets_org_treasury", "treasury_wallets", ["org_id", "treasury_id"]
    )
    op.create_index(
        "uq_treasury_wallets_source",
        "treasury_wallets",
        ["treasury_id"],
        unique=True,
        postgresql_where=sa.text("role = 'SOURCE'::treasury_wallet_role"),
    )

    op.create_table(
        "safe_config_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("block_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("owners", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("threshold", sa.SmallInteger(), nullable=False),
        sa.Column("modules", postgresql.ARRAY(sa.LargeBinary(length=20)), nullable=False),
        sa.Column("guard", sa.LargeBinary(length=20), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("block_number >= 0", name="ck_safe_config_snapshots_block_number"),
        sa.CheckConstraint(
            "octet_length(block_hash) = 32", name="ck_safe_config_snapshots_block_hash_length"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(owners) = 'array'", name="ck_safe_config_snapshots_owners_array"
        ),
        sa.CheckConstraint(
            "jsonb_array_length(owners) > 0", name="ck_safe_config_snapshots_owners_not_empty"
        ),
        sa.CheckConstraint("threshold > 0", name="ck_safe_config_snapshots_threshold_positive"),
        sa.CheckConstraint(
            "threshold <= jsonb_array_length(owners)",
            name="ck_safe_config_snapshots_threshold_owners",
        ),
        sa.CheckConstraint(
            "array_position(modules, NULL) IS NULL",
            name="ck_safe_config_snapshots_modules_no_null",
        ),
        sa.CheckConstraint(
            "guard IS NULL OR octet_length(guard) = 20",
            name="ck_safe_config_snapshots_guard_length",
        ),
        sa.ForeignKeyConstraint(
            ["wallet_id", "org_id"],
            ["treasury_wallets.id", "treasury_wallets.org_id"],
            name="fk_safe_config_snapshots_wallet_org",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "wallet_id",
            "block_number",
            "block_hash",
            name="uq_safe_config_snapshots_wallet_block_hash",
        ),
    )
    op.create_index(
        "ix_safe_config_snapshots_org_wallet_block",
        "safe_config_snapshots",
        ["org_id", "wallet_id", sa.text("block_number DESC")],
    )
    op.create_index(
        "ix_safe_config_snapshots_wallet_block",
        "safe_config_snapshots",
        ["wallet_id", sa.text("block_number DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_safe_config_snapshots_wallet_block", table_name="safe_config_snapshots")
    op.drop_index("ix_safe_config_snapshots_org_wallet_block", table_name="safe_config_snapshots")
    op.drop_table("safe_config_snapshots")
    op.drop_index("uq_treasury_wallets_source", table_name="treasury_wallets")
    op.drop_index("ix_treasury_wallets_org_treasury", table_name="treasury_wallets")
    op.drop_table("treasury_wallets")
    op.drop_index("ix_treasuries_chain_id", table_name="treasuries")
    op.drop_index("ix_treasuries_org_id", table_name="treasuries")
    op.drop_table("treasuries")
    op.drop_index("ix_deployments_chain_id", table_name="deployments")
    op.drop_table("deployments")
    op.drop_index("ix_assets_chain_id", table_name="assets")
    op.drop_table("assets")
    op.drop_table("chains")

    bind = op.get_bind()
    treasury_wallet_role.drop(bind, checkfirst=False)
    treasury_coverage.drop(bind, checkfirst=False)
    treasury_status.drop(bind, checkfirst=False)
