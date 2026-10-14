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
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api.identity.memberships import LastAdministrator, LastOwner
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
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM organizations WHERE id IN (:org, :other)"),
                {"org": organization_id, "other": other_org_id},
            )
        await engine.dispose()


def test_scim_deprovision_is_tenant_scoped_and_audited_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_scenario(database_url))
    finally:
        command.downgrade(config, "base")


async def _group_scenario(database_url: str) -> None:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    organization_id = uuid.uuid4()
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
                text("INSERT INTO organizations (id, name) VALUES (:org, 'SCIM groups')"),
                {"org": organization_id},
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
        scim_repository = SqlAlchemyScimIdentityRepository(sessions)
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
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM organizations WHERE id = :org"), {"org": organization_id}
            )
        await engine.dispose()


def test_scim_groups_keep_role_sources_separate_and_suspend_on_last_role_loss() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_group_scenario(database_url))
    finally:
        command.downgrade(config, "base")
