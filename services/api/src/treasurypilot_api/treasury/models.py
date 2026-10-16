from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from treasurypilot_api.database import Base, RowVersionedMixin, VersionedMixin
from treasurypilot_api.identity.models import uuid7


class TreasuryStatus(StrEnum):
    DRAFT = "Draft"
    MODULE_PENDING = "ModulePending"
    READY = "Ready"
    PAUSED = "Paused"
    REVOKED = "Revoked"


class Coverage(StrEnum):
    UNKNOWN = "UNKNOWN"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"


class WalletRole(StrEnum):
    SOURCE = "SOURCE"
    OPERATIONAL = "OPERATIONAL"


treasury_status_enum = Enum(
    TreasuryStatus,
    name="treasury_status",
    values_callable=lambda values: [value.value for value in values],
)
coverage_enum = Enum(
    Coverage,
    name="treasury_coverage",
    values_callable=lambda values: [value.value for value in values],
)
wallet_role_enum = Enum(
    WalletRole,
    name="treasury_wallet_role",
    values_callable=lambda values: [value.value for value in values],
)


class Chain(VersionedMixin, Base):
    __tablename__ = "chains"
    __table_args__ = (
        CheckConstraint("chain_id > 0", name="ck_chains_chain_id_positive"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_chains_name"),
        CheckConstraint("confirmations >= 0", name="ck_chains_confirmations"),
        CheckConstraint("length(btrim(explorer_url)) > 0", name="ck_chains_explorer_url"),
        CheckConstraint("jsonb_typeof(rpc_urls) = 'array'", name="ck_chains_rpc_urls_array"),
        CheckConstraint("jsonb_array_length(rpc_urls) > 0", name="ck_chains_rpc_urls_not_empty"),
        CheckConstraint("version > 0", name="ck_chains_version"),
    )

    chain_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_testnet: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confirmations: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    explorer_url: Mapped[str] = mapped_column(Text, nullable=False)
    rpc_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class Asset(VersionedMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("chain_id", "address", name="uq_assets_chain_address"),
        UniqueConstraint("id", "chain_id", name="uq_assets_id_chain"),
        CheckConstraint(
            "(is_native AND address IS NULL) OR (NOT is_native AND octet_length(address) = 20)",
            name="ck_assets_address",
        ),
        CheckConstraint("length(btrim(symbol)) > 0", name="ck_assets_symbol"),
        CheckConstraint("decimals BETWEEN 0 AND 255", name="ck_assets_decimals"),
        CheckConstraint("length(btrim(issuer_label)) > 0", name="ck_assets_issuer_label"),
        CheckConstraint("version > 0", name="ck_assets_version"),
        Index("ix_assets_chain_id", "chain_id"),
        Index(
            "uq_assets_chain_native",
            "chain_id",
            unique=True,
            postgresql_where=text("is_native"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    chain_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chains.chain_id", ondelete="RESTRICT"), nullable=False
    )
    address: Mapped[bytes | None] = mapped_column(LargeBinary(20))
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    decimals: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    issuer_label: Mapped[str] = mapped_column(String(120), nullable=False)
    is_test: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_native: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class Deployment(RowVersionedMixin, Base):
    __tablename__ = "deployments"
    __table_args__ = (
        UniqueConstraint("chain_id", "name", "version", name="uq_deployments_chain_name_version"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_deployments_name"),
        CheckConstraint("length(btrim(version)) > 0", name="ck_deployments_version_label"),
        CheckConstraint("octet_length(address) = 20", name="ck_deployments_address_length"),
        CheckConstraint("octet_length(code_hash) = 32", name="ck_deployments_code_hash_length"),
        CheckConstraint("row_version > 0", name="ck_deployments_row_version"),
        Index("ix_deployments_chain_id", "chain_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    chain_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chains.chain_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    code_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)


class Treasury(VersionedMixin, Base):
    __tablename__ = "treasuries"
    __table_args__ = (
        UniqueConstraint("id", "org_id", name="uq_treasuries_id_org"),
        UniqueConstraint("id", "chain_id", name="uq_treasuries_id_chain"),
        ForeignKeyConstraint(
            ["asset_id", "chain_id"],
            ["assets.id", "assets.chain_id"],
            name="fk_treasuries_asset_chain",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["org_id", "coverage_ack_by"],
            ["memberships.org_id", "memberships.user_id"],
            name="fk_treasuries_coverage_ack_membership",
            ondelete="NO ACTION",
        ),
        CheckConstraint(
            "module_address IS NULL OR octet_length(module_address) = 20",
            name="ck_treasuries_module_address_length",
        ),
        CheckConstraint(
            "(coverage_ack_by IS NULL AND coverage_ack_at IS NULL "
            "AND coverage_ack_reason IS NULL) OR "
            "(coverage_ack_by IS NOT NULL AND coverage_ack_at IS NOT NULL "
            "AND length(btrim(coverage_ack_reason)) > 0)",
            name="ck_treasuries_coverage_ack",
        ),
        CheckConstraint(
            "jsonb_typeof(coverage_details) = 'array'",
            name="ck_treasuries_coverage_details_array",
        ),
        CheckConstraint("version > 0", name="ck_treasuries_version"),
        Index("ix_treasuries_org_id", "org_id"),
        Index("ix_treasuries_chain_id", "chain_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    chain_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chains.chain_id", ondelete="RESTRICT"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    module_address: Mapped[bytes | None] = mapped_column(LargeBinary(20))
    status: Mapped[TreasuryStatus] = mapped_column(
        treasury_status_enum,
        nullable=False,
        default=TreasuryStatus.DRAFT,
        server_default=TreasuryStatus.DRAFT,
    )
    coverage: Mapped[Coverage] = mapped_column(
        coverage_enum,
        nullable=False,
        default=Coverage.UNKNOWN,
        server_default=Coverage.UNKNOWN,
    )
    coverage_ack_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="NO ACTION")
    )
    coverage_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coverage_ack_reason: Mapped[str | None] = mapped_column(Text)
    coverage_details: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )


class TreasuryWallet(VersionedMixin, Base):
    __tablename__ = "treasury_wallets"
    __table_args__ = (
        UniqueConstraint("id", "org_id", name="uq_treasury_wallets_id_org"),
        # Lets payment_requests pin its paying wallet to the request's treasury.
        UniqueConstraint("id", "treasury_id", name="uq_treasury_wallets_id_treasury"),
        # One on-chain Safe belongs to exactly one treasury across all tenants.
        UniqueConstraint("chain_id", "safe_address", name="uq_treasury_wallets_chain_address"),
        ForeignKeyConstraint(
            ["treasury_id", "org_id"],
            ["treasuries.id", "treasuries.org_id"],
            name="fk_treasury_wallets_treasury_org",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["treasury_id", "chain_id"],
            ["treasuries.id", "treasuries.chain_id"],
            name="fk_treasury_wallets_treasury_chain",
            ondelete="CASCADE",
        ),
        CheckConstraint("length(btrim(label)) > 0", name="ck_treasury_wallets_label"),
        CheckConstraint(
            "octet_length(safe_address) = 20", name="ck_treasury_wallets_safe_address_length"
        ),
        CheckConstraint("jsonb_typeof(owners) = 'array'", name="ck_treasury_wallets_owners_array"),
        CheckConstraint(
            "jsonb_array_length(owners) > 0", name="ck_treasury_wallets_owners_not_empty"
        ),
        CheckConstraint("threshold > 0", name="ck_treasury_wallets_threshold_positive"),
        CheckConstraint(
            "threshold <= jsonb_array_length(owners)", name="ck_treasury_wallets_threshold_owners"
        ),
        CheckConstraint("version > 0", name="ck_treasury_wallets_version"),
        Index("ix_treasury_wallets_org_treasury", "org_id", "treasury_id"),
        Index(
            "uq_treasury_wallets_source",
            "treasury_id",
            unique=True,
            postgresql_where=text("role = 'SOURCE'::treasury_wallet_role"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    treasury_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[WalletRole] = mapped_column(wallet_role_enum, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    safe_address: Mapped[bytes] = mapped_column(LargeBinary(20), nullable=False)
    owners: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    threshold: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class SafeConfigSnapshot(Base):
    __tablename__ = "safe_config_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["wallet_id", "org_id"],
            ["treasury_wallets.id", "treasury_wallets.org_id"],
            name="fk_safe_config_snapshots_wallet_org",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "wallet_id",
            "block_number",
            "block_hash",
            name="uq_safe_config_snapshots_wallet_block_hash",
        ),
        CheckConstraint("block_number >= 0", name="ck_safe_config_snapshots_block_number"),
        CheckConstraint(
            "octet_length(block_hash) = 32", name="ck_safe_config_snapshots_block_hash_length"
        ),
        CheckConstraint(
            "jsonb_typeof(owners) = 'array'", name="ck_safe_config_snapshots_owners_array"
        ),
        CheckConstraint(
            "jsonb_array_length(owners) > 0", name="ck_safe_config_snapshots_owners_not_empty"
        ),
        CheckConstraint("threshold > 0", name="ck_safe_config_snapshots_threshold_positive"),
        CheckConstraint(
            "threshold <= jsonb_array_length(owners)",
            name="ck_safe_config_snapshots_threshold_owners",
        ),
        CheckConstraint(
            "array_position(modules, NULL) IS NULL", name="ck_safe_config_snapshots_modules_no_null"
        ),
        CheckConstraint(
            "guard IS NULL OR octet_length(guard) = 20",
            name="ck_safe_config_snapshots_guard_length",
        ),
        CheckConstraint(
            "fallback_handler IS NULL OR octet_length(fallback_handler) = 20",
            name="ck_safe_config_snapshots_fallback_handler_length",
        ),
        CheckConstraint(
            "jsonb_typeof(module_implementations) = 'object'",
            name="ck_safe_config_snapshots_module_implementations_object",
        ),
        Index(
            "ix_safe_config_snapshots_org_wallet_block",
            "org_id",
            "wallet_id",
            desc("block_number"),
        ),
        Index("ix_safe_config_snapshots_wallet_block", "wallet_id", desc("block_number")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    wallet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    owners: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    threshold: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    modules: Mapped[list[bytes]] = mapped_column(ARRAY(LargeBinary(20)), nullable=False)
    guard: Mapped[bytes | None] = mapped_column(LargeBinary(20))
    fallback_handler: Mapped[bytes | None] = mapped_column(LargeBinary(20))
    module_implementations: Mapped[dict[str, str | None]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BorrowProposalRow(Base):
    """The borrow estimate for a liquidity shortfall (ENG-014, F-069); written by the worker.

    At most one is ``Proposed`` per treasury: a newer estimate supersedes it. It is advisory and
    never a transaction (BR-044). Amounts are base-unit integers (ADR-014).
    """

    __tablename__ = "borrow_proposals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Proposed', 'Authorized', 'Dismissed', 'Superseded')",
            name="ck_borrow_proposals_status",
        ),
        CheckConstraint("amount > 0 AND shortfall > 0", name="ck_borrow_proposals_amounts"),
        Index(
            "uq_borrow_proposals_open",
            "treasury_id",
            unique=True,
            postgresql_where=text("status = 'Proposed'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    treasury_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treasuries.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="Proposed")
    shortfall: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    amount: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    cost_to_repayment: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    withdraw_cost: Mapped[int] = mapped_column(Numeric(78, 0), nullable=False)
    health_factor_before: Mapped[int | None] = mapped_column(Numeric(78, 0))
    health_factor_after: Mapped[int | None] = mapped_column(Numeric(78, 0))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    due_day: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
