from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api.identity.oidc_repository import OIDCIdentityRepository

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

API_ROOT = Path(__file__).parents[1]
ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
ISSUER = "https://id.example"
GROUP_MAP = {"fin": ("Finance",)}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _scenario(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        repository = OIDCIdentityRepository(sessions)

        async def login(subject: str, email: str, groups: tuple[str, ...] | None) -> None:
            await repository.provision(
                issuer=ISSUER,
                subject=subject,
                email=email,
                display_name=None,
                organization_id=ORG_ID,
                groups=groups,
                group_role_map=GROUP_MAP,
            )

        async def membership(email: str) -> tuple[list[str], str]:
            async with sessions() as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT m.roles, m.status FROM memberships m "
                            "JOIN users u ON u.id = m.user_id WHERE u.email = :email"
                        ),
                        {"email": email},
                    )
                ).one()
            return list(row[0]), row[1]

        async with engine.begin() as connection:
            await connection.execute(
                text(f"INSERT INTO organizations (id, name) VALUES ('{ORG_ID}', 'SSO test')")
            )
            for email, roles, status in (
                ("owner@example.com", ["Owner", "Operator"], "active"),
                ("suspended@example.com", ["Operator"], "suspended"),
                ("manual-operator@example.com", ["Operator"], "active"),
            ):
                await connection.execute(
                    text(
                        "WITH u AS (INSERT INTO users (id, email) VALUES (gen_random_uuid(), :e) "
                        "RETURNING id) INSERT INTO memberships (id, org_id, user_id, roles, status)"
                        " SELECT gen_random_uuid(), :o, id, :r, :s FROM u"
                    ),
                    {"e": email, "o": ORG_ID, "r": roles, "s": status},
                )

        # A manually suspended member stays suspended: login is rejected.
        with pytest.raises(ValueError):
            await login("sub-suspended", "suspended@example.com", ("fin",))
        assert await membership("suspended@example.com") == (["Operator"], "suspended")

        # SSO manages only its own roles; the pre-existing Owner and Operator grants stay
        # manual, survive a remap, a missing claim and a claim with no mapped groups, and
        # the owner is never suspended.
        await login("sub-owner", "owner@example.com", ("fin",))
        roles, status = await membership("owner@example.com")
        assert (sorted(roles), status) == (["Finance", "Operator", "Owner"], "active")
        await login("sub-owner", "owner@example.com", None)
        assert await membership("owner@example.com") == (roles, "active")
        with pytest.raises(ValueError):
            await login("sub-owner", "owner@example.com", ())
        assert await membership("owner@example.com") == (["Operator", "Owner"], "active")

        # A user with no elevated role is suspended once the provider drops its groups.
        await login("sub-new", "new@example.com", ("fin",))
        with pytest.raises(ValueError):
            await login("sub-new", "new@example.com", ())
        assert await membership("new@example.com") == ([], "suspended")
        # No groups claim and no membership: nothing is provisioned.
        with pytest.raises(ValueError):
            await login("sub-nogroups", "nogroups@example.com", None)

        # The email links to an account that already has an identity for this issuer.
        with pytest.raises(ValueError):
            await login("sub-other", "owner@example.com", ("fin",))

        # Linking an existing manually managed member must not convert its existing
        # Operator grant into an OIDC grant that the next claim can remove.
        await login("sub-manual-operator", "manual-operator@example.com", ("fin",))
        assert await membership("manual-operator@example.com") == (
            ["Finance", "Operator"],
            "active",
        )
        with pytest.raises(ValueError):
            await login("sub-manual-operator", "manual-operator@example.com", ())
        assert await membership("manual-operator@example.com") == (["Operator"], "active")
    finally:
        # The downgrade refuses suspended memberships that no longer hold a role grant.
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM memberships WHERE cardinality(roles) = 0"))
        await engine.dispose()


def test_oidc_provisioning_protects_existing_memberships_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_scenario(database_url))
    finally:
        command.downgrade(config, "base")
