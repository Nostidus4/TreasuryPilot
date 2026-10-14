from sqlalchemy import ARRAY, Enum, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from treasurypilot_api.database import Base
from treasurypilot_api.treasury.models import (
    Asset,
    Chain,
    Coverage,
    Deployment,
    Treasury,
    TreasuryStatus,
    TreasuryWallet,
    WalletRole,
)

TREASURY_TABLES = {
    "chains",
    "assets",
    "deployments",
    "treasuries",
    "treasury_wallets",
    "safe_config_snapshots",
}


def _unique_columns(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_treasury_metadata_contains_required_tables() -> None:
    assert TREASURY_TABLES.issubset(Base.metadata.tables)


def test_postgres_enum_values_match_module_states() -> None:
    treasuries = Base.metadata.tables["treasuries"]
    wallets = Base.metadata.tables["treasury_wallets"]

    assert isinstance(treasuries.c.status.type, Enum)
    assert treasuries.c.status.type.enums == [status.value for status in TreasuryStatus]
    assert treasuries.c.coverage.type.enums == [coverage.value for coverage in Coverage]
    assert wallets.c.role.type.enums == [role.value for role in WalletRole]


def test_data_model_uniqueness_constraints_are_present() -> None:
    assert ("chain_id", "address") in _unique_columns("assets")
    assert ("chain_id", "name", "version") in _unique_columns("deployments")
    assert ("chain_id", "safe_address") in _unique_columns("treasury_wallets")


def test_only_one_native_asset_is_allowed_per_chain() -> None:
    assets = Base.metadata.tables["assets"]
    index = next(index for index in assets.indexes if index.name == "uq_assets_chain_native")

    assert index.unique
    assert tuple(column.name for column in index.columns) == ("chain_id",)
    assert str(index.dialect_options["postgresql"]["where"]) == "is_native"


def test_coverage_ack_foreign_keys_do_not_block_org_cascades() -> None:
    treasuries = Base.metadata.tables["treasuries"]

    for constraint in treasuries.constraints:
        if isinstance(constraint, ForeignKeyConstraint) and "coverage_ack_by" in {
            element.parent.name for element in constraint.elements
        }:
            assert constraint.ondelete == "NO ACTION"


def test_mutable_treasury_tables_use_optimistic_locking() -> None:
    for model in (Chain, Asset, Treasury, TreasuryWallet):
        assert model.__mapper__.version_id_col is model.__table__.c.version
        assert model.__table__.c.updated_at.onupdate is not None
    assert Deployment.__mapper__.version_id_col is Deployment.__table__.c.row_version


def test_tenant_owned_tables_have_org_first_indexes() -> None:
    for table_name in ("treasuries", "treasury_wallets", "safe_config_snapshots"):
        table = Base.metadata.tables[table_name]
        assert any(
            isinstance(index, Index) and next(iter(index.columns)).name == "org_id"
            for index in table.indexes
        )


def test_composite_foreign_keys_prevent_cross_chain_and_cross_tenant_links() -> None:
    treasuries = Base.metadata.tables["treasuries"]
    wallets = Base.metadata.tables["treasury_wallets"]
    snapshots = Base.metadata.tables["safe_config_snapshots"]

    treasury_foreign_keys = {
        tuple(element.parent.name for element in constraint.elements)
        for constraint in treasuries.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    wallet_foreign_keys = {
        tuple(element.parent.name for element in constraint.elements)
        for constraint in wallets.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    snapshot_foreign_keys = {
        tuple(element.parent.name for element in constraint.elements)
        for constraint in snapshots.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert ("asset_id", "chain_id") in treasury_foreign_keys
    assert ("org_id", "coverage_ack_by") in treasury_foreign_keys
    assert ("treasury_id", "org_id") in wallet_foreign_keys
    assert ("treasury_id", "chain_id") in wallet_foreign_keys
    assert ("wallet_id", "org_id") in snapshot_foreign_keys


def test_chain_and_safe_collection_columns_use_native_postgres_types() -> None:
    chains = Base.metadata.tables["chains"]
    wallets = Base.metadata.tables["treasury_wallets"]
    snapshots = Base.metadata.tables["safe_config_snapshots"]

    assert isinstance(chains.c.rpc_urls.type, JSONB)
    assert isinstance(wallets.c.owners.type, JSONB)
    assert isinstance(snapshots.c.owners.type, JSONB)
    assert isinstance(snapshots.c.modules.type, ARRAY)
    assert snapshots.c.modules.type.item_type.length == 20
    assert "fallback_handler" in snapshots.c
    assert isinstance(snapshots.c.module_implementations.type, JSONB)
    assert isinstance(Base.metadata.tables["treasuries"].c.coverage_details.type, JSONB)


def test_only_one_source_wallet_is_allowed_per_treasury() -> None:
    wallets = Base.metadata.tables["treasury_wallets"]
    index = next(index for index in wallets.indexes if index.name == "uq_treasury_wallets_source")

    assert index.unique
    assert tuple(column.name for column in index.columns) == ("treasury_id",)
    assert str(index.dialect_options["postgresql"]["where"]) == (
        "role = 'SOURCE'::treasury_wallet_role"
    )
