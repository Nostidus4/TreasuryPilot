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

from treasurypilot_api.identity.saml_repository import (
    SAMLIdentityConflict,
    SAMLIdentityError,
    SAMLIdentityRepository,
)

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
    async def _restore_memberships() -> None:
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

    asyncio.run(_restore_memberships())
    command.downgrade(config, "base")


async def _saml_login_scenario(database_url: str) -> None:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SAMLIdentityRepository(sessions)
    organization_id = uuid.uuid4()
    other_organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(UTC)
    request_expiry = now + timedelta(minutes=10)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, name) VALUES "
                    "(:org, 'SAML integration'), (:other_org, 'Other SAML tenant')"
                ),
                {"org": organization_id, "other_org": other_organization_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'SAML User')"
                ),
                {"id": user_id, "email": "saml-user@example.com"},
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, roles, status) "
                    "VALUES (:id, :org, :user, ARRAY['Finance']::text[], 'active')"
                ),
                {"id": uuid.uuid4(), "org": organization_id, "user": user_id},
            )

        await repository.create_request(
            request_id="_saml-request-1",
            relay_state="relay-one-time-1",
            browser_nonce="browser-nonce-1",
            organization_id=organization_id,
            now=now,
            expires_at=request_expiry,
        )
        assert await repository.find_pending_request(
            relay_state="relay-one-time-1", browser_nonce="browser-nonce-1", now=now
        ) == ("_saml-request-1", organization_id)
        user = await repository.complete_login(
            request_id="_saml-request-1",
            relay_state="relay-one-time-1",
            browser_nonce="browser-nonce-1",
            organization_id=organization_id,
            issuer="https://id.example/saml",
            subject="persistent-subject-1",
            email="SAML-User@Example.com",
            response_id="_response-1",
            assertion_id="_assertion-1",
            assertion_expires_at=now + timedelta(minutes=5),
            now=now,
        )
        assert user.id == user_id
        assert user.email == "saml-user@example.com"
        assert (
            await repository.find_pending_request(
                relay_state="relay-one-time-1", browser_nonce="browser-nonce-1", now=now
            )
            is None
        )

        # A valid persistent identity in one organization must not fall back to the
        # globally shared user record when the same user has no membership in another.
        await repository.create_request(
            request_id="_saml-request-cross-tenant",
            relay_state="relay-cross-tenant",
            browser_nonce="browser-cross-tenant",
            organization_id=other_organization_id,
            now=now,
            expires_at=request_expiry,
        )
        with pytest.raises(
            SAMLIdentityError, match="does not match one active organization member"
        ):
            await repository.complete_login(
                request_id="_saml-request-cross-tenant",
                relay_state="relay-cross-tenant",
                browser_nonce="browser-cross-tenant",
                organization_id=other_organization_id,
                issuer="https://id.example/saml",
                subject="persistent-subject-1",
                email="saml-user@example.com",
                response_id="_response-cross-tenant",
                assertion_id="_assertion-cross-tenant",
                assertion_expires_at=now + timedelta(minutes=5),
                now=now,
            )
        assert await repository.find_pending_request(
            relay_state="relay-cross-tenant",
            browser_nonce="browser-cross-tenant",
            now=now,
        ) == ("_saml-request-cross-tenant", other_organization_id)
        async with sessions() as session:
            other_tenant_identity_count = await session.scalar(
                text("SELECT count(*) FROM saml_identities WHERE org_id = :org"),
                {"org": other_organization_id},
            )
        assert other_tenant_identity_count == 0

        with pytest.raises(SAMLIdentityError, match="already used"):
            await repository.complete_login(
                request_id="_saml-request-1",
                relay_state="relay-one-time-1",
                browser_nonce="browser-nonce-1",
                organization_id=organization_id,
                issuer="https://id.example/saml",
                subject="persistent-subject-1",
                email="saml-user@example.com",
                response_id="_response-replay",
                assertion_id="_assertion-replay",
                assertion_expires_at=now + timedelta(minutes=5),
                now=now,
            )

        await repository.create_request(
            request_id="_saml-request-2",
            relay_state="relay-one-time-2",
            browser_nonce="browser-nonce-2",
            organization_id=organization_id,
            now=now,
            expires_at=request_expiry,
        )
        with pytest.raises(SAMLIdentityError, match="already used"):
            await repository.complete_login(
                request_id="_saml-request-2",
                relay_state="relay-one-time-2",
                browser_nonce="browser-nonce-2",
                organization_id=organization_id,
                issuer="https://id.example/saml",
                subject="persistent-subject-1",
                email="saml-user@example.com",
                response_id="_response-1",
                assertion_id="_assertion-1",
                assertion_expires_at=now + timedelta(minutes=5),
                now=now,
            )

        await repository.create_request(
            request_id="_saml-request-3",
            relay_state="relay-one-time-3",
            browser_nonce="browser-nonce-3",
            organization_id=organization_id,
            now=now,
            expires_at=request_expiry,
        )
        with pytest.raises(SAMLIdentityError, match="no longer matches"):
            await repository.complete_login(
                request_id="_saml-request-3",
                relay_state="relay-one-time-3",
                browser_nonce="browser-nonce-3",
                organization_id=organization_id,
                issuer="https://id.example/saml",
                subject="persistent-subject-1",
                email="different-user@example.com",
                response_id="_response-3",
                assertion_id="_assertion-3",
                assertion_expires_at=now + timedelta(minutes=5),
                now=now,
            )
        assert await repository.find_pending_request(
            relay_state="relay-one-time-3", browser_nonce="browser-nonce-3", now=now
        ) == ("_saml-request-3", organization_id)

        # A different NameID for an already-linked user is a link conflict, not a replay.
        await repository.create_request(
            request_id="_saml-request-4",
            relay_state="relay-one-time-4",
            browser_nonce="browser-nonce-4",
            organization_id=organization_id,
            now=now,
            expires_at=request_expiry,
        )
        with pytest.raises(SAMLIdentityConflict, match="different NameID"):
            await repository.complete_login(
                request_id="_saml-request-4",
                relay_state="relay-one-time-4",
                browser_nonce="browser-nonce-4",
                organization_id=organization_id,
                issuer="https://id.example/saml",
                subject="persistent-subject-2",
                email="saml-user@example.com",
                response_id="_response-4",
                assertion_id="_assertion-4",
                assertion_expires_at=now + timedelta(minutes=5),
                now=now,
            )

        async with sessions() as session:
            counts = (
                await session.execute(
                    text(
                        "SELECT (SELECT count(*) FROM users), "
                        "(SELECT count(*) FROM saml_identities), "
                        "(SELECT count(*) FROM saml_replay_ids)"
                    )
                )
            ).one()
        assert tuple(counts) == (1, 1, 2)
    finally:
        await engine.dispose()


def test_saml_identity_mapping_is_org_scoped_and_one_time() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_saml_login_scenario(database_url))
    finally:
        _downgrade_test_schema(config, database_url)
