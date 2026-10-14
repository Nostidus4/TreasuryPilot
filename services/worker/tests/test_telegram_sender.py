"""Telegram delivery against PostgreSQL with a fake bot (set TEST_DATABASE_URL)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from treasurypilot_core.privacy import FieldCipher, FieldEncryptionKey
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.notify.telegram import (
    TelegramBotBlocked,
    TelegramPermanentError,
    TelegramTransientError,
)
from treasurypilot_worker.notify.telegram_fake import FakeTelegramClient
from treasurypilot_worker.notify.telegram_sender import (
    MAX_ATTEMPTS,
    TARGET_CONTEXT,
    deliver_pending,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        "TEST_DATABASE_URL" not in os.environ,
        reason="TEST_DATABASE_URL is required for the PostgreSQL Telegram delivery tests",
    ),
]

CIPHER = FieldCipher(
    FieldEncryptionKey.from_base64(base64.urlsafe_b64encode(bytes(range(32))).decode())
)
BASE_URL = "https://app.example.test"
CHAT_ID = "424242"


def _database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


class World:
    """Seeds one org, one linked user and helpers to emit notifications."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool
        self.org_id = uuid.uuid4()
        self.user_id = uuid.uuid4()
        self.other_user_id = uuid.uuid4()
        self.channel_id = uuid.uuid4()
        self.t0 = datetime.now(UTC)
        self._orgs = [self.org_id]
        self._vendors: list[uuid.UUID] = []
        self._assets: list[uuid.UUID] = []

    async def seed(self, *, show_amounts: bool = False) -> None:
        async with self.pool.acquire() as c, c.transaction():
            await c.execute(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Telegram test')", self.org_id
            )
            await c.execute(
                "INSERT INTO users (id, email) VALUES ($1, $2), ($3, $4)",
                self.user_id,
                f"tg-{self.user_id}@example.test",
                self.other_user_id,
                f"tg-{self.other_user_id}@example.test",
            )
            await c.execute(
                "INSERT INTO notification_channels "
                "(id, user_id, kind, target, target_hash, verified_at, show_amounts) "
                "VALUES ($1, $2, 'TELEGRAM', $3, $4, $5, $6)",
                self.channel_id,
                self.user_id,
                CIPHER.encrypt_text(CHAT_ID, context=TARGET_CONTEXT),
                uuid.uuid4().bytes + uuid.uuid4().bytes,
                self.t0 - timedelta(minutes=1),
                show_amounts,
            )

    async def notify(
        self,
        *,
        user_id: uuid.UUID | None = None,
        severity: str = "ACTION",
        entity_id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
        title: str = "Approval required",
        deliver_after: float = 0,
        event_type: str = "ApprovalNeeded",
    ) -> uuid.UUID:
        org = org_id or self.org_id
        entity = entity_id or uuid.uuid4()
        event_id = uuid.uuid4()
        async with self.pool.acquire() as c, c.transaction():
            await c.execute(
                "INSERT INTO domain_events (id, org_id, type, entity_type, entity_id, payload, published_at) "
                "VALUES ($1, $2, $4, 'payment_request', $3, '{}'::jsonb, now())",
                event_id,
                org,
                entity,
                event_type,
            )
            await c.execute(
                "INSERT INTO notifications (id, org_id, user_id, event_id, type, title, body, link, severity, deliver_at) "
                "VALUES ($1, $2, $3, $4, $8, $5, 'generic body', $6, $7, $9)",
                uuid.uuid4(),
                org,
                user_id or self.user_id,
                event_id,
                title,
                f"/requests/{entity}",
                severity,
                event_type,
                self.t0 + timedelta(seconds=deliver_after),
            )
        return entity

    async def payment_request(self, *, org_id: uuid.UUID | None = None) -> uuid.UUID:
        """A request for 1.5 USDC to Acme Ltd; FK checks are bypassed for unrelated tables."""

        org = org_id or self.org_id
        request_id, vendor_id, asset_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with self.pool.acquire() as c, c.transaction():
            try:
                await c.execute("SET LOCAL session_replication_role = replica")
            except Exception:  # noqa: BLE001
                pytest.skip("superuser needed to seed payment requests without a full treasury")
            await c.execute(
                "INSERT INTO assets (id, chain_id, symbol, decimals, issuer_label) "
                "VALUES ($1, 31337, 'USDC', 6, 'test')",
                asset_id,
            )
            await c.execute(
                "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES ($1, $2, 'Acme Ltd', $3)",
                vendor_id,
                org,
                f"acme-{vendor_id}",
            )
            await c.execute(
                "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, "
                "invoice_no, issue_date, due_at, amount, asset_id) "
                "VALUES ($1, $2, $3, 31337, $4, $5, 'INV-1', current_date, current_date, 1500000, $6)",
                request_id,
                org,
                uuid.uuid4(),
                vendor_id,
                uuid.uuid4(),
                asset_id,
            )
        self._vendors.append(vendor_id)
        self._assets.append(asset_id)
        return request_id

    async def run(self, client: FakeTelegramClient, *, after: float = 0) -> int:
        return await deliver_pending(
            self.pool,
            client=client,
            cipher=CIPHER,
            base_url=BASE_URL,
            now=self.t0 + timedelta(seconds=after),
        )

    async def rows(self, query: str, *args: object) -> list[Any]:
        async with self.pool.acquire() as c:
            return list(await c.fetch(query, *args))

    async def cleanup(self) -> None:
        async with self.pool.acquire() as c:
            async with c.transaction():
                # Replica mode skips FK triggers, so it is limited to the rows seeded that way.
                await c.execute("SET LOCAL session_replication_role = replica")
                await c.execute(
                    "DELETE FROM payment_requests WHERE org_id = ANY($1::uuid[])", self._orgs
                )
                await c.execute("DELETE FROM vendors WHERE id = ANY($1::uuid[])", self._vendors)
                await c.execute("DELETE FROM assets WHERE id = ANY($1::uuid[])", self._assets)
            await c.execute("DELETE FROM domain_events WHERE org_id = ANY($1::uuid[])", self._orgs)
            await c.execute(
                "DELETE FROM users WHERE id = ANY($1::uuid[])", [self.user_id, self.other_user_id]
            )
            await c.execute("DELETE FROM organizations WHERE id = ANY($1::uuid[])", self._orgs)


def _run(scenario: Callable[[World], Awaitable[None]], *, show_amounts: bool = False) -> None:
    async def main() -> None:
        pool = await create_worker_pool(_database_url(), min_size=1, max_size=2)
        world = World(pool)
        try:
            await world.seed(show_amounts=show_amounts)
            await scenario(world)
        finally:
            await world.cleanup()
            await pool.close()

    asyncio.run(main())


def test_a_linked_user_gets_a_minimal_message_with_a_deep_link() -> None:
    async def scenario(world: World) -> None:
        entity = await world.notify()
        client = FakeTelegramClient()

        assert await world.run(client) == 1

        assert client.sent == [
            (
                CHAT_ID,
                f"[TreasuryPilot] Approval required · open: {BASE_URL}/requests/{entity}",
            )
        ]
        (row,) = await world.rows("SELECT status, attempts FROM telegram_deliveries")
        assert (row["status"], row["attempts"]) == ("SENT", 1)

    _run(scenario)


def test_delivery_is_idempotent_across_runs_and_workers() -> None:
    async def scenario(world: World) -> None:
        await world.notify()
        client = FakeTelegramClient()
        results = await asyncio.gather(world.run(client), world.run(client))
        await world.run(client, after=30)

        assert sum(results) == 1
        assert len(client.sent) == 1

    _run(scenario)


def test_only_the_notified_user_with_a_channel_receives_anything() -> None:
    async def scenario(world: World) -> None:
        await world.notify(user_id=world.other_user_id)  # no channel linked
        await world.notify(severity="INFO")  # INFO stays in-app
        client = FakeTelegramClient()

        assert await world.run(client) == 0
        assert client.sent == []

    _run(scenario)


def test_notifications_from_before_linking_are_not_replayed() -> None:
    async def scenario(world: World) -> None:
        await world.notify()
        async with world.pool.acquire() as c:
            await c.execute(
                "UPDATE notification_channels SET verified_at = now() + interval '1 minute'"
            )
        client = FakeTelegramClient()

        assert await world.run(client) == 0

    _run(scenario)


def test_at_most_one_message_per_ten_seconds_and_bursts_are_merged() -> None:
    async def scenario(world: World) -> None:
        client = FakeTelegramClient()
        await world.notify(title="First")
        assert await world.run(client) == 1

        await world.notify(title="Second")
        await world.notify(title="Third")
        assert await world.run(client, after=3) == 0
        assert await world.run(client, after=9) == 0
        assert len(client.sent) == 1

        assert await world.run(client, after=10.5) == 1
        assert client.sent[1][1].startswith("[TreasuryPilot] 2 new notifications")
        assert "Second" not in client.sent[1][1]
        assert await world.run(client, after=40) == 0
        statuses = await world.rows("SELECT status FROM telegram_deliveries")
        assert [r["status"] for r in statuses] == ["SENT"] * 3

    _run(scenario)


def test_amounts_and_vendor_appear_only_after_opt_in() -> None:
    async def scenario(world: World) -> None:
        request_id = await world.payment_request()
        client = FakeTelegramClient()
        await world.notify(entity_id=request_id)
        await world.run(client)
        default_text = client.sent[0][1]
        assert "1.5" not in default_text and "USDC" not in default_text
        assert "Acme" not in default_text

        async with world.pool.acquire() as c:
            await c.execute("UPDATE notification_channels SET show_amounts = true")
        await world.notify(entity_id=request_id)
        await world.run(client, after=11)
        assert "1.5 USDC to Acme Ltd" in client.sent[1][1]

    _run(scenario)


def test_amounts_are_not_read_across_organizations() -> None:
    async def scenario(world: World) -> None:
        other_org = uuid.uuid4()
        async with world.pool.acquire() as c:
            await c.execute(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Other org')", other_org
            )
        world._orgs.append(other_org)
        foreign_request = await world.payment_request(org_id=other_org)
        client = FakeTelegramClient()
        # An event in our org that names another organization's request.
        await world.notify(entity_id=foreign_request)
        await world.run(client)

        assert len(client.sent) == 1
        assert "USDC" not in client.sent[0][1] and "Acme" not in client.sent[0][1]

    _run(scenario, show_amounts=True)


def test_transient_failure_retries_with_backoff_then_gives_up() -> None:
    async def scenario(world: World) -> None:
        await world.notify()
        client = FakeTelegramClient(*(TelegramTransientError("down") for _ in range(MAX_ATTEMPTS)))

        assert await world.run(client) == 0
        assert await world.run(client, after=2) == 0  # still backing off
        assert await world.run(client, after=6) == 0
        assert await world.run(client, after=40) == 0
        (row,) = await world.rows("SELECT status, attempts FROM telegram_deliveries")
        assert (row["status"], row["attempts"]) == ("FAILED", MAX_ATTEMPTS)
        assert await world.run(client, after=80) == 0
        assert client.sent == []

    _run(scenario)


def test_a_retry_succeeds_once_telegram_recovers() -> None:
    async def scenario(world: World) -> None:
        await world.notify()
        client = FakeTelegramClient(TelegramTransientError("down"))

        assert await world.run(client) == 0
        assert await world.run(client, after=6) == 1
        assert len(client.sent) == 1

    _run(scenario)


def test_a_blocked_bot_deactivates_the_channel() -> None:
    async def scenario(world: World) -> None:
        await world.notify()
        client = FakeTelegramClient(TelegramBotBlocked("blocked"))

        assert await world.run(client) == 0
        (channel,) = await world.rows("SELECT active FROM notification_channels")
        assert channel["active"] is False
        await world.notify()
        assert await world.run(client, after=60) == 0
        assert client.sent == []

    _run(scenario)


def test_a_permanent_rejection_is_not_retried() -> None:
    async def scenario(world: World) -> None:
        await world.notify()
        client = FakeTelegramClient(TelegramPermanentError("bad request"))

        assert await world.run(client) == 0
        assert await world.run(client, after=60) == 0
        (row,) = await world.rows("SELECT status FROM telegram_deliveries")
        assert row["status"] == "FAILED"

    _run(scenario)


def test_an_undecryptable_target_fails_closed() -> None:
    async def scenario(world: World) -> None:
        await world.notify()
        async with world.pool.acquire() as c:
            await c.execute("UPDATE notification_channels SET target = 'tpenc:v1:x:garbage'")
        client = FakeTelegramClient()

        assert await world.run(client) == 0
        assert client.sent == []

    _run(scenario)


def test_messages_carry_no_actionable_payload() -> None:
    async def scenario(world: World) -> None:
        await world.notify()
        client = FakeTelegramClient()
        await world.run(client)

        (chat_id, text) = client.sent[0]
        # The adapter takes text only; there is no channel for buttons or callbacks.
        assert isinstance(text, str) and "approve" not in text.lower()
        assert json.dumps(text).count("callback") == 0

    _run(scenario)


def test_no_row_lock_is_held_while_the_message_is_in_flight() -> None:
    async def scenario(world: World) -> None:
        await world.notify()
        probes: list[int] = []

        class ProbingClient(FakeTelegramClient):
            async def send_message(self, chat_id: str, text: str) -> None:
                # NOWAIT raises if the sender still holds the channel's row lock.
                rows = await world.rows(
                    "SELECT 1 FROM notification_channels WHERE id = $1 FOR UPDATE NOWAIT",
                    world.channel_id,
                )
                probes.append(len(rows))
                await super().send_message(chat_id, text)

        assert await world.run(ProbingClient()) == 1
        assert probes == [1]

    _run(scenario)


def test_an_unexpected_send_error_is_contained_and_counted_as_an_attempt() -> None:
    async def scenario(world: World) -> None:
        await world.notify()

        class BrokenClient(FakeTelegramClient):
            async def send_message(self, chat_id: str, text: str) -> None:
                raise RuntimeError("boom")

        assert await world.run(BrokenClient()) == 0  # does not raise
        (row,) = await world.rows("SELECT status, attempts FROM telegram_deliveries")
        assert (row["status"], row["attempts"]) == ("PENDING", 1)

    _run(scenario)


def test_a_deferred_notification_is_not_sent_before_deliver_at() -> None:
    async def scenario(world: World) -> None:
        await world.notify(deliver_after=3600)  # held back by quiet hours
        client = FakeTelegramClient()

        assert await world.run(client, after=60) == 0
        assert await world.rows("SELECT 1 FROM telegram_deliveries") == []
        # Once due it is sent, even though it was created more than the backlog window ago.
        assert await world.run(client, after=3601) == 1
        assert len(client.sent) == 1

    _run(scenario)


async def _set_preferences(world: World, channels: str, categories: str = "{}") -> None:
    async with world.pool.acquire() as c:
        await c.execute(
            "INSERT INTO notification_preferences (user_id, channels, categories) "
            "VALUES ($1, $2::jsonb, $3::jsonb)",
            world.user_id,
            channels,
            categories,
        )


def test_a_user_with_telegram_disabled_is_not_sent_optional_notifications() -> None:
    async def scenario(world: World) -> None:
        await _set_preferences(world, '{"telegram": false}')
        await world.notify()
        client = FakeTelegramClient()

        assert await world.run(client) == 0
        (row,) = await world.rows("SELECT status, last_error FROM telegram_deliveries")
        assert (row["status"], row["last_error"]) == ("FAILED", "preference_opt_out")
        assert await world.run(client, after=30) == 0  # not re-evaluated or sent later
        assert client.sent == []

    _run(scenario)


def test_mandatory_events_ignore_the_telegram_preference() -> None:
    async def scenario(world: World) -> None:
        await _set_preferences(world, '{"telegram": false}')
        await world.notify(severity="CRITICAL", event_type="UnexpectedOutflow")
        client = FakeTelegramClient()

        assert await world.run(client) == 1

    _run(scenario)


def test_a_disabled_category_is_not_sent() -> None:
    async def scenario(world: World) -> None:
        await _set_preferences(world, "{}", '{"approvals": false}')
        await world.notify()

        assert await world.run(FakeTelegramClient()) == 0

    _run(scenario)
