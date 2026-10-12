from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.auth import (
    AuthFailure,
    AuthService,
    SessionTokenCodec,
    VerifiedSession,
)
from treasurypilot_api.identity.models import MagicLink, Session, User
from treasurypilot_api.identity.repository import SqlAlchemyAuthRepository

API_ROOT = Path(__file__).parents[1]


class _CaptureSender:
    def __init__(self) -> None:
        self.url: str | None = None

    async def send_magic_link(self, *, email: str, url: str) -> None:
        self.url = url


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def _alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _exercise_postgres_auth_flow(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    repository = SqlAlchemyAuthRepository(sessions)
    sender = _CaptureSender()
    clock = _Clock()
    secret = b"postgres-integration-secret-value"
    service = AuthService(
        repository=repository,
        sender=sender,
        token_codec=SessionTokenCodec(secret),
        client_hash_secret=secret,
        magic_link_base_url="https://app.example.test/auth/verify",
        clock=clock,
    )
    user_id = uuid.UUID("00000000-0000-4000-8000-000000000201")

    try:
        async with sessions() as session, session.begin():
            session.add(
                User(
                    id=user_id,
                    email="database@example.com",
                    display_name="Database User",
                    created_at=clock.value,
                    updated_at=clock.value,
                )
            )

        await service.request_magic_link("DATABASE@example.com")
        assert sender.url is not None
        token = parse_qs(urlparse(sender.url).query)["token"][0]

        async with sessions() as session:
            link = (await session.scalars(select(MagicLink))).one()
            assert token not in repr(link.token_hash)
            assert len(link.token_hash) == 32

        attempts = await asyncio.gather(
            service.verify_magic_link(token=token, client_ip="127.0.0.1", user_agent="test"),
            service.verify_magic_link(token=token, client_ip="127.0.0.1", user_agent="test"),
            return_exceptions=True,
        )
        verified = [item for item in attempts if isinstance(item, VerifiedSession)]
        rejected = [item for item in attempts if isinstance(item, AuthFailure)]
        assert len(verified) == 1
        assert len(rejected) == 1
        assert rejected[0].code == "TOKEN_INVALID"

        async with sessions() as session:
            stored_session = (await session.scalars(select(Session))).one()
            assert await session.scalar(select(func.count()).select_from(Session)) == 1
            assert len(stored_session.token_hash) == 32
            assert verified[0].session_token not in repr(stored_session.token_hash)

        access = await service.authenticate(session_token=verified[0].session_token)
        assert access.user.id == user_id

        clock.value += timedelta(minutes=31)
        with pytest.raises(AuthFailure) as caught:
            await service.authenticate(session_token=verified[0].session_token)
        assert caught.value.code == "AUTH_REQUIRED"
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL auth integration test",
)
def test_postgres_magic_link_replay_and_session_expiry() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)

    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise_postgres_auth_flow(database_url))
    finally:
        command.downgrade(config, "base")
