import uuid

from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT

from treasurypilot_api.database import Base
from treasurypilot_api.identity.models import OrganizationRole, uuid7


def test_identity_metadata_contains_required_tables() -> None:
    assert {
        "users",
        "sessions",
        "magic_links",
        "wallet_links",
        "siwe_nonces",
        "organizations",
        "memberships",
        "invites",
    }.issubset(Base.metadata.tables)


def test_email_columns_use_case_insensitive_postgres_type() -> None:
    for table_name in ("users", "magic_links", "invites"):
        assert isinstance(Base.metadata.tables[table_name].c.email.type, CITEXT)


def test_identity_uniqueness_constraints_match_data_model() -> None:
    users = Base.metadata.tables["users"]
    memberships = Base.metadata.tables["memberships"]
    invites = Base.metadata.tables["invites"]

    assert users.c.email.unique
    assert any(
        isinstance(constraint, UniqueConstraint)
        and tuple(column.name for column in constraint.columns) == ("org_id", "user_id")
        for constraint in memberships.constraints
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and tuple(column.name for column in constraint.columns) == ("token_hash",)
        for constraint in invites.constraints
    )


def test_active_wallet_address_index_is_partial_and_unique() -> None:
    wallet_links = Base.metadata.tables["wallet_links"]
    index = next(
        item
        for item in wallet_links.indexes
        if isinstance(item, Index) and item.name == "uq_wallet_links_active_address"
    )

    assert index.unique
    assert tuple(column.name for column in index.columns) == ("address",)
    assert str(index.dialect_options["postgresql"]["where"]) == "unlinked_at IS NULL"


def test_all_documented_organization_roles_are_available() -> None:
    assert {role.value for role in OrganizationRole} == {
        "OrgAdmin",
        "Owner",
        "Approver",
        "Operator",
        "Finance",
        "Guardian",
        "Auditor",
        "PlatformAdmin",
    }


def test_uuid7_generator_sets_version_and_rfc_variant() -> None:
    generated = uuid7()

    assert generated.version == 7
    assert generated.variant == uuid.RFC_4122
