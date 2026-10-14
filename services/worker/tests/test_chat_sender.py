"""Chat delivery queue integration (set TEST_DATABASE_URL to a migrated database)."""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from treasurypilot_core.privacy import FieldCipher, FieldEncryptionKey
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.notify.chat_adapters import (
    ChatPermanentError,
    ChatPlatform,
    ChatTransientError,
    HttpChatWebhookClient,
)
from treasurypilot_worker.notify.chat_sender import deliver_chat_pending
from treasurypilot_worker.notify.telegram_sender import MAX_ATTEMPTS, TARGET_CONTEXT

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        "TEST_DATABASE_URL" not in os.environ,
        reason="TEST_DATABASE_URL is required for chat delivery integration tests",
    ),
]

CIPHER = FieldCipher(
    FieldEncryptionKey.from_base64(base64.urlsafe_b64encode(bytes(range(32))).decode())
)
BASE_URL = "https://app.example.test"
WEBHOOK_URL = "https://hooks.slack.com/services/T/B/secret"
LARK_URL = "https://open.larksuite.com/open-apis/bot/v2/hook/secret"


class FakeChatClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[tuple[str, str]] = []
        self.error = error

    async def send_message(self, webhook_url: str, text_value: str) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append((webhook_url, text_value))


class World:
    """One org and one user per channel, with notifications to deliver."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool
        self.org_id = uuid.uuid4()
        self.t0 = datetime.now(UTC)
        self.users: list[uuid.UUID] = []
        self.channels: list[uuid.UUID] = []

    async def seed(self) -> None:
        async with self.pool.acquire() as c:
            await c.execute(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Chat test')", self.org_id
            )

    async def user(
        self, kind: str = "SLACK", url: str = WEBHOOK_URL, *, verified_ago: float = 60
    ) -> tuple[uuid.UUID, uuid.UUID]:
        user_id, channel_id = uuid.uuid4(), uuid.uuid4()
        async with self.pool.acquire() as c, c.transaction():
            await c.execute(
                "INSERT INTO users (id, email) VALUES ($1, $2)",
                user_id,
                f"chat-{user_id}@example.test",
            )
            await c.execute(
                "INSERT INTO notification_channels "
                "(id, user_id, kind, target, target_hash, verified_at) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                channel_id,
                user_id,
                kind,
                CIPHER.encrypt_text(url, context=TARGET_CONTEXT),
                uuid.uuid4().bytes + uuid.uuid4().bytes,
                self.t0 - timedelta(seconds=verified_ago),
            )
        self.users.append(user_id)
        self.channels.append(channel_id)
        return user_id, channel_id

    async def notify(
        self,
        user_id: uuid.UUID,
        *,
        event_type: str = "ApprovalNeeded",
        title: str = "Approval required",
        deliver_after: float = 0,
    ) -> uuid.UUID:
        entity, event_id = uuid.uuid4(), uuid.uuid4()
        async with self.pool.acquire() as c, c.transaction():
            await c.execute(
                "INSERT INTO domain_events (id, org_id, type, entity_type, entity_id, payload, "
                "published_at) VALUES ($1, $2, $3, 'payment_request', $4, '{}'::jsonb, now())",
                event_id,
                self.org_id,
                event_type,
                entity,
            )
            await c.execute(
                "INSERT INTO notifications (id, org_id, user_id, event_id, type, title, body, "
                "link, severity, deliver_at) VALUES ($1, $2, $3, $4, $5, $6, 'generic body', "
                "$7, 'ACTION', $8)",
                uuid.uuid4(),
                self.org_id,
                user_id,
                event_id,
                event_type,
                title,
                f"/requests/{entity}",
                self.t0 + timedelta(seconds=deliver_after),
            )
        return entity

    async def run(self, clients: dict[ChatPlatform, Any], *, after: float = 0) -> int:
        return await deliver_chat_pending(
            self.pool,
            clients=clients,
            cipher=CIPHER,
            base_url=BASE_URL,
            now=self.t0 + timedelta(seconds=after),
        )

    async def rows(self, query: str, *args: object) -> list[Any]:
        async with self.pool.acquire() as c:
            return list(await c.fetch(query, *args))

    async def set_preferences(self, user_id: uuid.UUID, channels: str) -> None:
        async with self.pool.acquire() as c:
            await c.execute(
                "INSERT INTO notification_preferences (user_id, channels) VALUES ($1, $2::jsonb)",
                user_id,
                channels,
            )

    async def cleanup(self) -> None:
        async with self.pool.acquire() as c:
            await c.execute("DELETE FROM domain_events WHERE org_id = $1", self.org_id)
            await c.execute("DELETE FROM users WHERE id = ANY($1::uuid[])", self.users)
            await c.execute("DELETE FROM organizations WHERE id = $1", self.org_id)


def _run(scenario: Callable[[World], Awaitable[None]]) -> None:
    async def main() -> None:
        pool = await create_worker_pool(os.environ["TEST_DATABASE_URL"], min_size=1, max_size=2)
        world = World(pool)
        try:
            await world.seed()
            await scenario(world)
        finally:
            await world.cleanup()
            await pool.close()

    asyncio.run(main())


async def _status(world: World, channel_id: uuid.UUID) -> tuple[str, str | None, int]:
    (row,) = await world.rows(
        "SELECT status, last_error, attempts FROM chat_deliveries WHERE channel_id = $1",
        channel_id,
    )
    return row["status"], row["last_error"], row["attempts"]


def test_action_notification_is_delivered_to_encrypted_chat_target() -> None:
    async def scenario(world: World) -> None:
        user, channel = await world.user()
        entity = await world.notify(user)
        client = FakeChatClient()

        assert await world.run({ChatPlatform.SLACK: client}) == 1

        assert client.sent == [
            (
                WEBHOOK_URL,
                f"[TreasuryPilot] Approval required · open: {BASE_URL}/requests/{entity}",
            )
        ]
        assert await _status(world, channel) == ("SENT", None, 1)

    _run(scenario)


def test_pending_delivery_from_before_reverification_is_failed_without_send() -> None:
    async def scenario(world: World) -> None:
        user, channel = await world.user()
        await world.notify(user)
        (notification,) = await world.rows("SELECT id FROM notifications WHERE user_id = $1", user)
        async with world.pool.acquire() as c, c.transaction():
            await c.execute(
                "INSERT INTO chat_deliveries (id, notification_id, channel_id, next_attempt_at) "
                "VALUES ($1, $2, $3, $4)",
                uuid.uuid4(),
                notification["id"],
                channel,
                world.t0,
            )
            await c.execute(
                "UPDATE notification_channels SET verified_at = $2 WHERE id = $1",
                channel,
                world.t0 + timedelta(seconds=30),
            )
        client = FakeChatClient()

        assert await world.run({ChatPlatform.SLACK: client}, after=60) == 0

        assert client.sent == []
        assert await _status(world, channel) == ("FAILED", "channel_reverified", 0)

    _run(scenario)


def test_invalid_stored_webhook_fails_that_channel_only() -> None:
    """A send-time validation failure must not abort the run or block other channels."""

    async def scenario(world: World) -> None:
        bad_user, bad_channel = await world.user("SLACK", "https://evil.example/services/x")
        good_user, good_channel = await world.user("LARK", LARK_URL)
        await world.notify(bad_user)
        await world.notify(good_user)
        lark = FakeChatClient()
        clients: dict[ChatPlatform, Any] = {
            ChatPlatform.SLACK: HttpChatWebhookClient(ChatPlatform.SLACK),
            ChatPlatform.LARK: lark,
        }

        assert await world.run(clients) == 1

        assert len(lark.sent) == 1
        assert await _status(world, bad_channel) == ("FAILED", "ChatPermanentError", 1)
        assert await _status(world, good_channel) == ("SENT", None, 1)
        # The failed channel is not retried or re-selected on later runs.
        assert await world.run(clients, after=60) == 0

    _run(scenario)


def test_unexpected_client_error_is_contained_and_retried() -> None:
    async def scenario(world: World) -> None:
        user, channel = await world.user()
        await world.notify(user)
        client = FakeChatClient(RuntimeError("boom"))

        assert await world.run({ChatPlatform.SLACK: client}) == 0

        assert await _status(world, channel) == ("PENDING", "RuntimeError", 1)

    _run(scenario)


def test_transient_failure_retries_with_backoff_then_gives_up() -> None:
    async def scenario(world: World) -> None:
        user, channel = await world.user()
        await world.notify(user)
        client = FakeChatClient(ChatTransientError("down"))
        clients: dict[ChatPlatform, Any] = {ChatPlatform.SLACK: client}

        assert await world.run(clients) == 0
        assert await _status(world, channel) == ("PENDING", "ChatTransientError", 1)
        assert await world.run(clients, after=1) == 0  # still inside the backoff
        assert (await _status(world, channel))[2] == 1
        for attempt in range(2, MAX_ATTEMPTS + 1):
            await world.run(clients, after=60 * attempt)
        assert await _status(world, channel) == (
            "FAILED",
            "ChatTransientError",
            MAX_ATTEMPTS,
        )

    _run(scenario)


def test_permanent_rejection_is_not_retried() -> None:
    async def scenario(world: World) -> None:
        user, channel = await world.user()
        await world.notify(user)
        client = FakeChatClient(ChatPermanentError("rejected"))

        assert await world.run({ChatPlatform.SLACK: client}) == 0

        assert await _status(world, channel) == ("FAILED", "ChatPermanentError", 1)

    _run(scenario)


def test_a_deferred_notification_is_not_sent_before_deliver_at() -> None:
    async def scenario(world: World) -> None:
        user, _ = await world.user()
        await world.notify(user, deliver_after=3600)  # held back by quiet hours
        client = FakeChatClient()

        assert await world.run({ChatPlatform.SLACK: client}) == 0
        assert await world.rows("SELECT 1 FROM chat_deliveries") == []
        assert client.sent == []

    _run(scenario)


def test_a_user_with_the_channel_disabled_is_not_sent_optional_notifications() -> None:
    async def scenario(world: World) -> None:
        slack_user, slack_channel = await world.user("SLACK")
        lark_user, lark_channel = await world.user("LARK", LARK_URL)
        for user in (slack_user, lark_user):
            await world.set_preferences(user, '{"slack": false}')
            await world.notify(user)
        slack, lark = FakeChatClient(), FakeChatClient()

        assert await world.run({ChatPlatform.SLACK: slack, ChatPlatform.LARK: lark}) == 1

        assert slack.sent == []
        assert len(lark.sent) == 1  # each chat kind has its own preference toggle
        assert await _status(world, slack_channel) == ("FAILED", "preference_opt_out", 0)
        assert (await _status(world, lark_channel))[0] == "SENT"

    _run(scenario)


def test_mandatory_events_ignore_the_chat_preference() -> None:
    async def scenario(world: World) -> None:
        user, _ = await world.user()
        await world.set_preferences(user, '{"slack": false}')
        await world.notify(user, event_type="UnexpectedOutflow")
        client = FakeChatClient()

        assert await world.run({ChatPlatform.SLACK: client}) == 1

    _run(scenario)


def test_at_most_one_message_per_ten_seconds_and_bursts_are_merged() -> None:
    async def scenario(world: World) -> None:
        user, _ = await world.user()
        await world.notify(user)
        client = FakeChatClient()
        clients: dict[ChatPlatform, Any] = {ChatPlatform.SLACK: client}
        assert await world.run(clients) == 1
        await world.notify(user, title="Second")
        await world.notify(user, title="Third")

        assert await world.run(clients, after=5) == 0
        assert await world.run(clients, after=11) == 1

        assert len(client.sent) == 2
        assert "2 new notifications" in client.sent[1][1]

    _run(scenario)
