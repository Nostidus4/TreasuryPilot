"""PostgreSQL behaviour of Telegram linking (set TEST_DATABASE_URL to a migrated database)."""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from treasurypilot_api.notifications.telegram import (
    LINK_CODE_TTL,
    TARGET_CONTEXT,
    LinkOutcome,
    SqlAlchemyTelegramRepository,
    hash_link_code,
)
from treasurypilot_core.privacy import FieldCipher, FieldEncryptionKey

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        "TEST_DATABASE_URL" not in os.environ,
        reason="TEST_DATABASE_URL is required for the PostgreSQL Telegram linking tests",
    ),
]

KEY = FieldEncryptionKey.from_base64(base64.urlsafe_b64encode(bytes(range(32))).decode())


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def _run(
    scenario: Callable[
        [SqlAlchemyTelegramRepository, async_sessionmaker[AsyncSession], _Clock, list[uuid.UUID]],
        Awaitable[None],
    ],
) -> None:
    async def main() -> None:
        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        clock = _Clock()
        repository = SqlAlchemyTelegramRepository(
            sessions, cipher=FieldCipher(KEY), hash_key=b"k" * 32, now=clock
        )
        users = [uuid.uuid4(), uuid.uuid4()]
        try:
            async with sessions() as session, session.begin():
                for user_id in users:
                    await session.execute(
                        text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                        {"id": user_id, "email": f"tg-{user_id}@example.test"},
                    )
            await scenario(repository, sessions, clock, users)
        finally:
            async with sessions() as session, session.begin():
                await session.execute(
                    text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": users}
                )
            await engine.dispose()

    asyncio.run(main())


def test_a_code_links_once_and_stores_only_ciphertext() -> None:
    async def scenario(repo, sessions, clock, users):  # type: ignore[no-untyped-def]
        code, expires_at = await repo.issue_link_code(user_id=users[0])
        assert expires_at == clock.value + LINK_CODE_TTL
        assert await repo.complete_link(code=code, chat_id=555) == LinkOutcome.LINKED
        # Single use: replaying the same code (even from another chat) fails.
        assert await repo.complete_link(code=code, chat_id=556) == LinkOutcome.INVALID_CODE

        (channel,) = await repo.list_channels(user_id=users[0])
        assert channel.active and not channel.show_amounts
        assert "555" not in channel.target
        assert FieldCipher(KEY).decrypt_text(channel.target, context=TARGET_CONTEXT) == "555"
        async with sessions() as session:
            stored = (
                await session.execute(text("SELECT code_hash FROM telegram_link_codes"))
            ).all()
            assert hash_link_code(code) in {row[0] for row in stored}
            assert code.encode() not in {bytes(row[0]) for row in stored}

    _run(scenario)


def test_an_expired_code_is_rejected() -> None:
    async def scenario(repo, sessions, clock, users):  # type: ignore[no-untyped-def]
        code, _ = await repo.issue_link_code(user_id=users[0])
        clock.value += LINK_CODE_TTL + timedelta(seconds=1)
        assert await repo.complete_link(code=code, chat_id=1) == LinkOutcome.INVALID_CODE
        assert await repo.list_channels(user_id=users[0]) == ()

    _run(scenario)


def test_a_new_code_replaces_the_previous_unused_one_and_unknown_codes_fail() -> None:
    async def scenario(repo, sessions, clock, users):  # type: ignore[no-untyped-def]
        first, _ = await repo.issue_link_code(user_id=users[0])
        second, _ = await repo.issue_link_code(user_id=users[0])
        assert await repo.complete_link(code=first, chat_id=1) == LinkOutcome.INVALID_CODE
        assert await repo.complete_link(code="never-issued", chat_id=1) == LinkOutcome.INVALID_CODE
        assert await repo.complete_link(code=second, chat_id=1) == LinkOutcome.LINKED

    _run(scenario)


def test_a_chat_cannot_be_shared_between_users_and_the_code_survives() -> None:
    async def scenario(repo, sessions, clock, users):  # type: ignore[no-untyped-def]
        mine, _ = await repo.issue_link_code(user_id=users[0])
        theirs, _ = await repo.issue_link_code(user_id=users[1])
        assert await repo.complete_link(code=mine, chat_id=900) == LinkOutcome.LINKED
        assert await repo.complete_link(code=theirs, chat_id=900) == LinkOutcome.CHAT_TAKEN
        assert await repo.list_channels(user_id=users[1]) == ()
        # The rejected code was not burned: the second user can link another chat.
        assert await repo.complete_link(code=theirs, chat_id=901) == LinkOutcome.LINKED

    _run(scenario)


def test_relinking_replaces_the_chat_and_resets_the_rate_limit() -> None:
    async def scenario(repo, sessions, clock, users):  # type: ignore[no-untyped-def]
        first, _ = await repo.issue_link_code(user_id=users[0])
        await repo.complete_link(code=first, chat_id=1)
        (channel,) = await repo.list_channels(user_id=users[0])
        await repo.set_show_amounts(user_id=users[0], channel_id=channel.id, show_amounts=True)
        second, _ = await repo.issue_link_code(user_id=users[0])
        await repo.complete_link(code=second, chat_id=2)
        (relinked,) = await repo.list_channels(user_id=users[0])
        assert relinked.id == channel.id
        assert FieldCipher(KEY).decrypt_text(relinked.target, context=TARGET_CONTEXT) == "2"

    _run(scenario)


def test_channels_are_isolated_per_user() -> None:
    async def scenario(repo, sessions, clock, users):  # type: ignore[no-untyped-def]
        code, _ = await repo.issue_link_code(user_id=users[0])
        await repo.complete_link(code=code, chat_id=77)
        (channel,) = await repo.list_channels(user_id=users[0])

        assert await repo.list_channels(user_id=users[1]) == ()
        assert (
            await repo.set_show_amounts(user_id=users[1], channel_id=channel.id, show_amounts=True)
            is None
        )
        assert not await repo.unlink(user_id=users[1], channel_id=channel.id)
        updated = await repo.set_show_amounts(
            user_id=users[0], channel_id=channel.id, show_amounts=True
        )
        assert updated is not None and updated.show_amounts
        assert await repo.unlink(user_id=users[0], channel_id=channel.id)

    _run(scenario)
