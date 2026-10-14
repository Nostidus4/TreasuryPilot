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
        await engine.dispose()


def test_scim_deprovision_is_tenant_scoped_and_audited_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_scenario(database_url))
    finally:
        command.downgrade(config, "base")
