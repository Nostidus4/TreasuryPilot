"""Telegram linking guards that need no database."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from treasurypilot_api.notifications.telegram import (
    LinkOutcome,
    SqlAlchemyTelegramRepository,
    TelegramUnavailable,
)
from treasurypilot_core.privacy import FieldCipher, FieldEncryptionKey

CIPHER = FieldCipher(FieldEncryptionKey.from_base64("A" * 43))


def _repository(sessions: Any = None, **overrides: Any) -> SqlAlchemyTelegramRepository:
    options: dict[str, Any] = {"cipher": CIPHER, "hash_key": b"k" * 32} | overrides
    return SqlAlchemyTelegramRepository(sessions, **options)


@pytest.mark.parametrize("overrides", [{"cipher": None}, {"hash_key": None}, {"hash_key": b""}])
def test_no_link_code_is_issued_when_linking_could_never_complete(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(TelegramUnavailable):
        asyncio.run(_repository(**overrides).issue_link_code(user_id=uuid.uuid4()))


class _Session:
    def __init__(self, error: Exception) -> None:
        self._error = error

    @asynccontextmanager
    async def begin(self) -> Any:
        yield

    async def scalar(self, *_: Any) -> Any:
        return uuid.uuid4()

    async def execute(self, *_: Any) -> Any:
        raise self._error


def _sessions(error: Exception) -> Any:
    @asynccontextmanager
    async def factory() -> Any:
        yield _Session(error)

    return factory


def test_only_the_chat_uniqueness_violation_means_chat_taken() -> None:
    taken = IntegrityError("insert", {}, Exception('violates "uq_notification_channels_target"'))
    other = IntegrityError("insert", {}, Exception('violates "fk_notification_channels_user"'))

    outcome = asyncio.run(_repository(_sessions(taken)).complete_link(code="c", chat_id=1))
    assert outcome == LinkOutcome.CHAT_TAKEN
    with pytest.raises(IntegrityError):
        asyncio.run(_repository(_sessions(other)).complete_link(code="c", chat_id=1))
