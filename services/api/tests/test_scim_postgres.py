from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api.identity.memberships import (
    LastAdministrator,
    LastOwner,
    SqlAlchemyMembershipRepository,
)
from treasurypilot_api.identity.oidc_repository import OIDCIdentityRepository
from treasurypilot_api.identity.scim import SqlAlchemyScimIdentityRepository

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

API_ROOT = Path(__file__).parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _downgrade_test_schema(config: Config, database_url: str) -> None:
    async def _restore_memberships_for_downgrade() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE memberships SET "
                        "roles = CASE WHEN cardinality(roles) = 0 "
                        "THEN ARRAY['Owner']::text[] ELSE roles END, "
                        "manual_roles = CASE WHEN cardinality(roles) = 0 "
                        "THEN ARRAY['Owner']::text[] ELSE roles END, "
                        "oidc_roles = ARRAY[]::text[], scim_roles = ARRAY[]::text[], "
                        "status = 'active'"
                    )
                )
        finally:
            await engine.dispose()

    # These tests use a disposable PostgreSQL schema and the downgrade guard
    # correctly rejects fixtures that leave grants suspended or SCIM-managed.
    asyncio.run(_restore_memberships_for_downgrade())
    command.downgrade(config, "base")


async def _scenario(database_url: str) -> None:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    organization_id, other_org_id = uuid.uuid4(), uuid.uuid4()
    operator_id, admin_id, owner_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    operator_scoped, operator_unscoped, operator_other_org = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    now = datetime.now(UTC)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, name) VALUES (:org, 'SCIM org'), "
                    "(:other, 'Other org')"
                ),
                {"org": organization_id, "other": other_org_id},
            )
            for user_id, email, roles in (
                (operator_id, "scim-operator@example.com", "Operator"),
                (admin_id, "scim-admin@example.com", "OrgAdmin"),
                (owner_id, "scim-owner@example.com", "Owner"),
            ):
                await connection.execute(
                    text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                    {"id": user_id, "email": email},
                )
                await connection.execute(
                    text(
                        "INSERT INTO memberships (id, org_id, user_id, roles) "
                        "VALUES (:id, :org, :user, ARRAY[:role]::text[])"
                    ),
                    {"id": uuid.uuid4(), "org": organization_id, "user": user_id, "role": roles},
                )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, roles) "
                    "VALUES (:id, :org, :user, ARRAY['Operator']::text[])"
                ),
                {"id": uuid.uuid4(), "org": other_org_id, "user": operator_id},
            )
            for session_id, scope, token_byte in (
                (operator_scoped, organization_id, b"a"),
                (operator_unscoped, None, b"b"),
                (operator_other_org, other_org_id, b"c"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO sessions "
                        "(id, user_id, organization_scope_id, token_hash, expires_at, ip_hash, ua_hash) "
                        "VALUES (:id, :user, :scope, :token, :expires, :ip, :ua)"
                    ),
                    {
                        "id": session_id,
                        "user": operator_id,
                        "scope": scope,
                        "token": token_byte * 32,
                        "expires": now.replace(year=now.year + 1),
                        "ip": b"i" * 32,
                        "ua": b"u" * 32,
                    },
                )

        repository = SqlAlchemyScimIdentityRepository(sessions)
        # Keep revocation timestamps after the database's transaction-timestamp defaults.
        now += timedelta(seconds=1)
        user = await repository.deactivate_user(
            organization_id=organization_id, user_id=operator_id, now=now
        )
        assert user is not None and not user.active
        other_org_user = await repository.get_user(
            organization_id=other_org_id, user_id=operator_id
        )
        assert other_org_user is not None and other_org_user.active

        async with sessions() as session:
            membership_status = await session.scalar(
                text("SELECT status FROM memberships WHERE org_id = :org AND user_id = :user"),
                {"org": organization_id, "user": operator_id},
            )
            sessions_by_id = dict(
                (
                    await session.execute(
                        text("SELECT id, revoked_at FROM sessions WHERE user_id = :user"),
                        {"user": operator_id},
                    )
                ).all()
            )
            audit = (
                await session.execute(
                    text(
                        "SELECT actor_type, actor_id, action, entity_type, data FROM audit_log "
                        "WHERE org_id = :org"
                    ),
                    {"org": organization_id},
                )
            ).one()
        assert membership_status == "suspended"
        assert sessions_by_id[operator_scoped] is not None
        assert sessions_by_id[operator_unscoped] is None
        assert sessions_by_id[operator_other_org] is None
        assert audit[0] == "SYSTEM"
        assert audit[1] == "scim"
        assert audit[2] == "identity.scim.deprovisioned"
        assert audit[3] == "membership"
        assert audit[4] == {"status": "suspended"}

        for protected_id, guard in ((admin_id, LastAdministrator), (owner_id, LastOwner)):
            with pytest.raises(guard):
                await repository.deactivate_user(
                    organization_id=organization_id, user_id=protected_id, now=now
                )
        async with sessions() as session:
            protected_statuses = (
                await session.execute(
                    text(
                        "SELECT user_id, status FROM memberships WHERE org_id = :org "
                        "AND user_id IN (:admin, :owner) ORDER BY user_id"
                    ),
                    {"org": organization_id, "admin": admin_id, "owner": owner_id},
                )
            ).all()
            audit_count = await session.scalar(
                text("SELECT count(*) FROM audit_log WHERE org_id = :org"),
                {"org": organization_id},
            )
        assert len(protected_statuses) == 2
        assert {row[1] for row in protected_statuses} == {"active"}
        assert audit_count == 1
    finally:
        await engine.dispose()


def test_scim_deprovision_is_tenant_scoped_and_audited_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_scenario(database_url))
    finally:
        _downgrade_test_schema(config, database_url)


async def _group_scenario(database_url: str) -> None:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    organization_id, other_organization_id = uuid.uuid4(), uuid.uuid4()
    manual_user_id, scim_only_user_id, oidc_manual_user_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    scoped_session_id = uuid.uuid4()
    now = datetime.now(UTC) + timedelta(seconds=1)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, name) VALUES "
                    "(:org, 'SCIM groups'), (:other_org, 'Other SCIM org')"
                ),
                {"org": organization_id, "other_org": other_organization_id},
            )
            for user_id, email in (
                (manual_user_id, "scim-manual@example.com"),
                (scim_only_user_id, "scim-only@example.com"),
                (oidc_manual_user_id, "scim-oidc-manual@example.com"),
            ):
                await connection.execute(
                    text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                    {"id": user_id, "email": email},
                )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, roles, manual_roles) "
                    "VALUES (:id, :org, :user, ARRAY['Finance']::text[], ARRAY['Finance']::text[]), "
                    "(:second_id, :org, :second_user, ARRAY['Operator']::text[], ARRAY['Operator']::text[])"
                ),
                {
                    "id": uuid.uuid4(),
                    "org": organization_id,
                    "user": manual_user_id,
                    "second_id": uuid.uuid4(),
                    "second_user": scim_only_user_id,
                },
            )
            # Simulate a member row written by an older API process during a rolling deploy.
            # Its existing manual grant must remain manual when the account is first linked.
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, roles) "
                    "VALUES (:id, :org, :user, ARRAY['Operator']::text[])"
                ),
                {"id": uuid.uuid4(), "org": organization_id, "user": oidc_manual_user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, roles) "
                    "VALUES (:id, :org, :user, ARRAY['Auditor', 'Operator']::text[])"
                ),
                {
                    "id": uuid.uuid4(),
                    "org": other_organization_id,
                    "user": oidc_manual_user_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO sessions "
                    "(id, user_id, organization_scope_id, token_hash, expires_at, ip_hash, ua_hash) "
                    "VALUES (:id, :user, :org, :token, :expires, :ip, :ua)"
                ),
                {
                    "id": scoped_session_id,
                    "user": scim_only_user_id,
                    "org": organization_id,
                    "token": b"s" * 32,
                    "expires": now + timedelta(days=1),
                    "ip": b"i" * 32,
                    "ua": b"u" * 32,
                },
            )

        oidc_repository = OIDCIdentityRepository(sessions)
        oidc_user = await oidc_repository.provision(
            issuer="https://id.example",
            subject="scim-coexistence",
            email="scim-oidc@example.com",
            display_name=None,
            organization_id=organization_id,
            groups=("auditors",),
            group_role_map={"auditors": ("Auditor",)},
        )
        linked_user = await oidc_repository.provision(
            issuer="https://id.example",
            subject="scim-manual-link",
            email="scim-oidc-manual@example.com",
            display_name=None,
            organization_id=organization_id,
            groups=("finance",),
            group_role_map={"finance": ("Finance",)},
        )
        assert linked_user.id == oidc_manual_user_id
        async with sessions() as session:
            linked_roles = (
                await session.execute(
                    text(
                        "SELECT roles, manual_roles, oidc_roles FROM memberships "
                        "WHERE org_id = :org AND user_id = :user"
                    ),
                    {"org": organization_id, "user": oidc_manual_user_id},
                )
            ).one()
        assert tuple(list(roles) for roles in linked_roles) == (
            ["Finance", "Operator"],
            ["Operator"],
            ["Finance"],
        )
        with pytest.raises(ValueError):
            await oidc_repository.provision(
                issuer="https://id.example",
                subject="scim-manual-link",
                email="scim-oidc-manual@example.com",
                display_name=None,
                organization_id=organization_id,
                groups=(),
                group_role_map={},
            )
        async with sessions() as session:
            linked_membership_after_oidc_removal = (
                await session.execute(
                    text(
                        "SELECT roles, manual_roles, oidc_roles, status FROM memberships "
                        "WHERE org_id = :org AND user_id = :user"
                    ),
                    {"org": organization_id, "user": oidc_manual_user_id},
                )
            ).one()
        linked_roles_after_oidc_removal = (
            list(linked_membership_after_oidc_removal[0]),
            list(linked_membership_after_oidc_removal[1]),
            list(linked_membership_after_oidc_removal[2]),
            linked_membership_after_oidc_removal[3],
        )
        assert linked_roles_after_oidc_removal == (["Operator"], ["Operator"], [], "active")
        scim_repository = SqlAlchemyScimIdentityRepository(
            sessions, oidc_organization_id=organization_id
        )
        role_map = {"Operators": ("Operator",)}
        group = await scim_repository.create_group(
            organization_id=organization_id,
            display_name="Operators",
            member_ids=(),
            role_map=role_map,
            now=now,
        )
        await scim_repository.patch_group_members(
            organization_id=organization_id,
            group_id=group.id,
            add_member_ids=(manual_user_id, scim_only_user_id, oidc_user.id),
            remove_member_ids=(),
            role_map=role_map,
            now=now,
        )

        async def membership(
            user_id: uuid.UUID,
        ) -> tuple[list[str], list[str], list[str], list[str], str]:
            async with sessions() as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT roles, manual_roles, oidc_roles, scim_roles, status "
                            "FROM memberships WHERE org_id = :org AND user_id = :user"
                        ),
                        {"org": organization_id, "user": user_id},
                    )
                ).one()
                return list(row[0]), list(row[1]), list(row[2]), list(row[3]), row[4]

        assert await membership(manual_user_id) == (
            ["Finance", "Operator"],
            ["Finance"],
            [],
            ["Operator"],
            "active",
        )
        await scim_repository.reconcile_group_roles(
            organization_id=None, role_map={}, now=now + timedelta(seconds=1)
        )
        assert (
            await scim_repository.get_group(organization_id=organization_id, group_id=group.id)
            is not None
        )
        assert await membership(manual_user_id) == (
            ["Finance", "Operator"],
            ["Finance"],
            [],
            ["Operator"],
            "active",
        )
        async with sessions() as session:
            no_config_revoked_at = await session.scalar(
                text("SELECT revoked_at FROM sessions WHERE id = :id"),
                {"id": scoped_session_id},
            )
        assert no_config_revoked_at is None

        other_group = await scim_repository.create_group(
            organization_id=other_organization_id,
            display_name="Operators",
            member_ids=(oidc_manual_user_id,),
            role_map=role_map,
            now=now,
        )
        async with sessions() as session:
            other_org_roles = (
                await session.execute(
                    text(
                        "SELECT roles, manual_roles, oidc_roles, scim_roles "
                        "FROM memberships WHERE org_id = :org AND user_id = :user"
                    ),
                    {"org": other_organization_id, "user": oidc_manual_user_id},
                )
            ).one()
        assert tuple(list(roles) for roles in other_org_roles) == (
            ["Auditor", "Operator"],
            ["Auditor", "Operator"],
            [],
            ["Operator"],
        )
        await scim_repository.delete_group(
            organization_id=other_organization_id,
            group_id=other_group.id,
            role_map=role_map,
            now=now + timedelta(seconds=1),
        )
        cross_org_member = await SqlAlchemyMembershipRepository(sessions).update_member(
            org_id=other_organization_id,
            user_id=oidc_manual_user_id,
            roles=("Auditor",),
            updated_by=oidc_manual_user_id,
        )
        assert cross_org_member is not None and cross_org_member.roles == ("Auditor",)
        async with sessions() as session:
            cross_org_role_sources = (
                await session.execute(
                    text(
                        "SELECT roles, manual_roles, oidc_roles, scim_roles "
                        "FROM memberships WHERE org_id = :org AND user_id = :user"
                    ),
                    {"org": other_organization_id, "user": oidc_manual_user_id},
                )
            ).one()
        assert tuple(list(roles) for roles in cross_org_role_sources) == (
            ["Auditor"],
            ["Auditor"],
            [],
            [],
        )
        await oidc_repository.provision(
            issuer="https://id.example",
            subject="scim-coexistence",
            email="scim-oidc@example.com",
            display_name=None,
            organization_id=organization_id,
            groups=("finance",),
            group_role_map={"finance": ("Finance",)},
        )
        assert (await membership(oidc_user.id))[0:4] == (
            ["Finance", "Operator"],
            [],
            ["Finance"],
            ["Operator"],
        )

        await scim_repository.patch_group_members(
            organization_id=organization_id,
            group_id=group.id,
            add_member_ids=(),
            remove_member_ids=(manual_user_id, scim_only_user_id, oidc_user.id),
            role_map=role_map,
            now=now + timedelta(seconds=1),
        )
        assert (await membership(manual_user_id))[0] == ["Finance"]
        assert (await membership(oidc_user.id))[0:5] == (
            ["Finance"],
            [],
            ["Finance"],
            [],
            "active",
        )
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE memberships SET manual_roles = ARRAY[]::text[] WHERE user_id = :user"),
                {"user": scim_only_user_id},
            )
        # Re-add and remove the only remaining role source; the member is suspended and scoped
        # sessions are revoked in the same transaction.
        await scim_repository.patch_group_members(
            organization_id=organization_id,
            group_id=group.id,
            add_member_ids=(scim_only_user_id,),
            remove_member_ids=(),
            role_map=role_map,
            now=now + timedelta(seconds=2),
        )
        await scim_repository.patch_group_members(
            organization_id=organization_id,
            group_id=group.id,
            add_member_ids=(),
            remove_member_ids=(scim_only_user_id,),
            role_map=role_map,
            now=now + timedelta(seconds=3),
        )
        roles, manual_roles, oidc_roles, scim_roles, status = await membership(scim_only_user_id)
        assert (roles, manual_roles, oidc_roles, scim_roles, status) == (
            [],
            [],
            [],
            [],
            "suspended",
        )
        async with sessions() as session:
            revoked_at = await session.scalar(
                text("SELECT revoked_at FROM sessions WHERE id = :id"),
                {"id": scoped_session_id},
            )
            audit_count = await session.scalar(
                text(
                    "SELECT count(*) FROM audit_log WHERE org_id = :org "
                    "AND action = 'identity.scim.group_roles.changed'"
                ),
                {"org": organization_id},
            )
        assert revoked_at is not None
        assert audit_count >= 5

        finance_group_map = {"Finance Team": ("Finance",)}
        finance_group = await scim_repository.create_group(
            organization_id=organization_id,
            display_name="Finance Team",
            member_ids=(manual_user_id,),
            role_map=finance_group_map,
            now=now + timedelta(seconds=4),
        )
        await scim_repository.reconcile_group_roles(
            organization_id=None, role_map={}, now=now + timedelta(seconds=5)
        )
        assert (
            await scim_repository.get_group(
                organization_id=organization_id, group_id=finance_group.id
            )
            is not None
        )
        assert await membership(manual_user_id) == (
            ["Finance"],
            ["Finance"],
            [],
            ["Finance"],
            "active",
        )

        # An explicitly configured empty allowlist revokes groups only for this tenant.
        # The manual Finance role keeps effective access unchanged, but group removal is audited.
        await scim_repository.reconcile_group_roles(
            organization_id=organization_id, role_map={}, now=now + timedelta(seconds=6)
        )
        assert (
            await scim_repository.get_group(
                organization_id=organization_id, group_id=finance_group.id
            )
            is None
        )
        assert await membership(manual_user_id) == (
            ["Finance"],
            ["Finance"],
            [],
            [],
            "active",
        )
        async with sessions() as session:
            config_removal_audit = await session.scalar(
                text(
                    "SELECT count(*) FROM audit_log WHERE org_id = :org "
                    "AND action = 'identity.scim.group.configuration_removed' "
                    "AND entity_id = :group_id"
                ),
                {"org": organization_id, "group_id": str(finance_group.id)},
            )
        assert config_removal_audit == 1
    finally:
        await engine.dispose()


def test_scim_groups_keep_role_sources_separate_and_suspend_on_last_role_loss() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_group_scenario(database_url))
    finally:
        _downgrade_test_schema(config, database_url)


async def _insert_pre_source_roles(database_url: str) -> None:
    engine = create_async_engine(database_url)
    primary_org_id = uuid.UUID("00000000-0000-7000-8000-000000000201")
    other_org_id = uuid.UUID("00000000-0000-7000-8000-000000000202")
    user_id = uuid.UUID("00000000-0000-7000-8000-000000000203")
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, name) VALUES "
                    "(:primary, 'Legacy OIDC org'), (:other, 'Legacy manual org')"
                ),
                {"primary": primary_org_id, "other": other_org_id},
            )
            await connection.execute(
                text("INSERT INTO users (id, email) VALUES (:id, 'legacy-scope@example.com')"),
                {"id": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO oidc_identities (issuer, subject, user_id) "
                    "VALUES ('https://id.example', 'legacy-scope-subject', :user)"
                ),
                {"user": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, roles) VALUES "
                    "(:primary_membership, :primary_org, :user, ARRAY['Finance', 'Owner']::text[]), "
                    "(:other_membership, :other_org, :user, ARRAY['Auditor', 'Operator']::text[])"
                ),
                {
                    "primary_membership": uuid.uuid4(),
                    "other_membership": uuid.uuid4(),
                    "primary_org": primary_org_id,
                    "other_org": other_org_id,
                    "user": user_id,
                },
            )
    finally:
        await engine.dispose()


async def _assert_legacy_role_sources_are_scoped(database_url: str) -> None:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    primary_org_id = uuid.UUID("00000000-0000-7000-8000-000000000201")
    other_org_id = uuid.UUID("00000000-0000-7000-8000-000000000202")
    user_id = uuid.UUID("00000000-0000-7000-8000-000000000203")
    now = datetime.now(UTC) + timedelta(seconds=1)
    try:
        oidc_repository = OIDCIdentityRepository(sessions)
        # Editing a migrated membership must not freeze the migration's temporary
        # all-manual attribution before configured-tenant OIDC sync can classify it.
        edited_member = await SqlAlchemyMembershipRepository(sessions).update_member(
            org_id=primary_org_id,
            user_id=user_id,
            roles=("Finance", "Owner"),
            updated_by=user_id,
        )
        assert edited_member is not None and edited_member.roles == ("Finance", "Owner")
        await oidc_repository.provision(
            issuer="https://id.example",
            subject="legacy-scope-subject",
            email="legacy-scope@example.com",
            display_name=None,
            organization_id=primary_org_id,
            groups=("finance",),
            group_role_map={"finance": ("Finance",)},
        )
        with pytest.raises(ValueError):
            await oidc_repository.provision(
                issuer="https://id.example",
                subject="legacy-scope-subject",
                email="legacy-scope@example.com",
                display_name=None,
                organization_id=primary_org_id,
                groups=(),
                group_role_map={},
            )
        async with sessions() as session:
            primary = (
                await session.execute(
                    text(
                        "SELECT roles, manual_roles, oidc_roles, role_sources_initialized, status "
                        "FROM memberships WHERE org_id = :org AND user_id = :user"
                    ),
                    {"org": primary_org_id, "user": user_id},
                )
            ).one()
            other_before_scim = (
                await session.execute(
                    text(
                        "SELECT roles, manual_roles, oidc_roles, role_sources_initialized "
                        "FROM memberships WHERE org_id = :org AND user_id = :user"
                    ),
                    {"org": other_org_id, "user": user_id},
                )
            ).one()
        assert tuple(
            list(value) if index < 3 else value for index, value in enumerate(primary)
        ) == (
            ["Owner"],
            ["Owner"],
            [],
            True,
            "active",
        )
        assert tuple(
            list(value) if index < 3 else value for index, value in enumerate(other_before_scim)
        ) == (
            ["Auditor", "Operator"],
            ["Auditor", "Operator"],
            [],
            False,
        )

        scim_repository = SqlAlchemyScimIdentityRepository(
            sessions, oidc_organization_id=primary_org_id
        )
        group = await scim_repository.create_group(
            organization_id=other_org_id,
            display_name="Operators",
            member_ids=(user_id,),
            role_map={"Operators": ("Operator",)},
            now=now,
        )
        await scim_repository.reconcile_group_roles(
            organization_id=primary_org_id, role_map={}, now=now
        )
        assert (
            await scim_repository.get_group(organization_id=other_org_id, group_id=group.id)
            is not None
        )
        await scim_repository.delete_group(
            organization_id=other_org_id,
            group_id=group.id,
            role_map={"Operators": ("Operator",)},
            now=now + timedelta(seconds=1),
        )
        member = await SqlAlchemyMembershipRepository(sessions).update_member(
            org_id=other_org_id,
            user_id=user_id,
            roles=("Auditor",),
            updated_by=user_id,
        )
        assert member is not None and member.roles == ("Auditor",)
        async with sessions() as session:
            other_after_edit = (
                await session.execute(
                    text(
                        "SELECT roles, manual_roles, oidc_roles, scim_roles "
                        "FROM memberships WHERE org_id = :org AND user_id = :user"
                    ),
                    {"org": other_org_id, "user": user_id},
                )
            ).one()
        assert tuple(list(value) for value in other_after_edit) == (
            ["Auditor"],
            ["Auditor"],
            [],
            [],
        )
    finally:
        await engine.dispose()


def test_migration_and_oidc_role_initialization_are_organization_scoped() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "20261015_0054")
    try:
        asyncio.run(_insert_pre_source_roles(database_url))
        command.upgrade(config, "head")
        asyncio.run(_assert_legacy_role_sources_are_scoped(database_url))
    finally:
        _downgrade_test_schema(config, database_url)


def test_migration_downgrade_refuses_active_scim_role_grants() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    organization_id, user_id = uuid.uuid4(), uuid.uuid4()
    try:

        async def _seed_active_scim_role() -> None:
            engine = create_async_engine(database_url)
            try:
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO organizations (id, name) "
                            "VALUES (:id, 'SCIM downgrade guard')"
                        ),
                        {"id": organization_id},
                    )
                    await connection.execute(
                        text(
                            "INSERT INTO users (id, email) VALUES (:id, 'scim-guard@example.com')"
                        ),
                        {"id": user_id},
                    )
                    await connection.execute(
                        text(
                            "INSERT INTO memberships "
                            "(id, org_id, user_id, roles, scim_roles, role_sources_initialized) "
                            "VALUES (:id, :org, :user, ARRAY['Operator']::text[], "
                            "ARRAY['Operator']::text[], true)"
                        ),
                        {"id": uuid.uuid4(), "org": organization_id, "user": user_id},
                    )
            finally:
                await engine.dispose()

        asyncio.run(_seed_active_scim_role())
        with pytest.raises(DBAPIError, match="clear all SCIM role grants"):
            command.downgrade(config, "20261015_0054")
    finally:
        _downgrade_test_schema(config, database_url)
