from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.models import uuid7
from treasurypilot_api.notifications.routes import SqlAlchemyNotificationRepository
from treasurypilot_api.notifications.stream import StreamOptions, event_stream, parse_cursor

API_ROOT = Path(__file__).parents[1]
OPTIONS = StreamOptions(poll_interval=0.2, heartbeat_interval=15, max_lifetime=None)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _never() -> bool:
    return False


async def _integration(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    repository = SqlAlchemyNotificationRepository(sessions)
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    user_a, user_b = uuid.uuid4(), uuid.uuid4()

    async def emit(org: uuid.UUID, entity_type: str = "operation") -> uuid.UUID:
        event_id = uuid7()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO domain_events (id, org_id, type, entity_type, entity_id, payload) "
                    "VALUES (:id, :org, 'OperationUpdated', :entity, :entity_id, "
                    "CAST(:payload AS jsonb))"
                ),
                {
                    "id": event_id,
                    "org": org,
                    "entity": entity_type,
                    "entity_id": uuid.uuid4(),
                    "payload": '{"operationId": "op", "excludeUserIds": ["secret"]}',
                },
            )
        return event_id

    async def notify(org: uuid.UUID, user: uuid.UUID, event_id: uuid.UUID) -> uuid.UUID:
        notification_id = uuid.uuid4()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO notifications (id, org_id, user_id, event_id, type, title, body, link, severity) "
                    "VALUES (:id, :org, :user, :event, 'OperationConfirmed', 't', 'b', '/x', 'INFO')"
                ),
                {"id": notification_id, "org": org, "user": user, "event": event_id},
            )
        return notification_id

    async def read(
        org: uuid.UUID, user: uuid.UUID, count: int, *, since: str | None = None
    ) -> list[str]:
        cursor = parse_cursor(since) or await repository.initial_cursor(
            organization_id=org, user_id=user
        )
        frames: list[str] = []
        floor = cursor.event_id, cursor.notification_at, cursor.notification_id

        async def run() -> None:
            async for frame in event_stream(
                repository,
                organization_id=org,
                user_id=user,
                cursor=cursor,
                options=OPTIONS,
                is_disconnected=_never,
                resumed=since is not None,
            ):
                if frame.startswith("id:"):
                    # A resumed stream may replay the lookback window; keep only newer frames.
                    sent = parse_cursor(frame.splitlines()[0][4:])
                    assert sent is not None
                    if (sent.event_id, sent.notification_at, sent.notification_id) <= floor:
                        continue
                    frames.append(frame)
                    if len(frames) >= count:
                        return

        await asyncio.wait_for(run(), timeout=5)
        return frames

    try:
        async with engine.begin() as connection:
            for user in (user_a, user_b):
                await connection.execute(
                    text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                    {"id": user, "email": f"stream-{user}@example.test"},
                )
            for org in (org_a, org_b):
                await connection.execute(
                    text("INSERT INTO organizations (id, name) VALUES (:id, 'Stream')"),
                    {"id": org},
                )

        # A status change after the client connected reaches it within 2 seconds.
        started: float = 0

        async def delayed_emit() -> None:
            nonlocal started
            await asyncio.sleep(0.5)
            started = time.monotonic()
            await emit(org_a)

        listener = asyncio.create_task(read(org_a, user_a, 1))
        await asyncio.sleep(0.1)  # let the listener take its initial cursor first
        await delayed_emit()
        frames = await listener
        assert time.monotonic() - started < 2
        assert "event: operation.status" in frames[0]
        assert "secret" not in frames[0] and "excludeUserIds" not in frames[0]
        assert '"operationId":"op"' in frames[0]

        # Another org's member receives nothing from org A, even from the start of time.
        leaked = asyncio.create_task(
            read(org_b, user_b, 1, since=f"{uuid.UUID(int=0)}.0.{uuid.UUID(int=0)}")
        )
        await asyncio.sleep(1)
        assert not leaked.done()
        own = await emit(org_b)
        assert f'"eventId":"{own}"' in (await leaked)[0]

        # Resume with Last-Event-ID returns exactly the events missed while disconnected.
        first = await emit(org_a)
        first_frames = await read(org_a, user_a, 1, since=frames[0].splitlines()[0][4:])
        assert str(first) in first_frames[0]
        resume_from = first_frames[0].splitlines()[0][4:]
        missed = [await emit(org_a), await emit(org_a)]
        replay = await read(org_a, user_a, 2, since=resume_from)
        assert [str(m) in f for m, f in zip(missed, replay, strict=True)] == [True, True]

        # Notifications are per user: user B never sees user A's, and read state is own-only.
        event = await emit(org_a)
        note = await notify(org_a, user_a, event)
        listed, unread = await repository.list_notifications(
            organization_id=org_a, user_id=user_a, unread=True, limit=10
        )
        assert [n.id for n in listed] == [note] and unread == 1
        assert await repository.list_notifications(
            organization_id=org_a, user_id=user_b, unread=False, limit=10
        ) == ((), 0)
        assert await repository.mark_read(organization_id=org_a, user_id=user_b, ids=[note]) == 0
        assert await repository.mark_read(organization_id=org_b, user_id=user_a, ids=[note]) == 0
        assert await repository.mark_read(organization_id=org_a, user_id=user_a, ids=[note]) == 1
        assert await repository.mark_read(organization_id=org_a, user_id=user_a, ids=[note]) == 1
        listed, unread = await repository.list_notifications(
            organization_id=org_a, user_id=user_a, unread=True, limit=10
        )
        assert listed == () and unread == 0
        nil = f"{uuid.UUID(int=0)}.0.{uuid.UUID(int=0)}"
        everything = await read(org_a, user_a, 6, since=nil)
        assert sum("event: notification.created" in f for f in everything) == 1
        assert any(str(note) in f for f in everything)
        assert not any(
            "event: notification.created" in f for f in await read(org_a, user_b, 5, since=nil)
        )
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for notification stream PostgreSQL tests",
)
def test_postgres_stream_is_live_org_scoped_and_resumable() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_integration(database_url))
    finally:
        command.downgrade(config, "base")
