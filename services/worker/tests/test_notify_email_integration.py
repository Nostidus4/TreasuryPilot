from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.notify import delivery
from treasurypilot_worker.notify.email import PermanentEmailError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        "TEST_DATABASE_URL" not in os.environ,
        reason="TEST_DATABASE_URL is required for the PostgreSQL email delivery tests",
    ),
]

SETTINGS = SimpleNamespace(
    database_url="postgresql://unused",
    resend_api_key=SimpleNamespace(get_secret_value=lambda: "key"),
    resend_from_email="notify@example.test",
    environment="local",
    email_unsubscribe_key=SimpleNamespace(get_secret_value=lambda: "x" * 32),
    app_base_url="http://localhost:5173",
    public_api_base_url="http://localhost:8000",
)


class World:
    def __init__(self, pool: Any) -> None:
        self.pool = pool
        self.org_id = uuid.uuid4()
        self.sent: list[dict[str, Any]] = []

    async def user(self, mode: str | None = None) -> tuple[uuid.UUID, str]:
        user_id, address = uuid.uuid4(), f"{uuid.uuid4()}@example.test"
        async with self.pool.acquire() as c, c.transaction():
            await c.execute(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Email test') "
                "ON CONFLICT DO NOTHING",
                self.org_id,
            )
            await c.execute("INSERT INTO users (id, email) VALUES ($1, $2)", user_id, address)
            if mode:
                await c.execute(
                    "INSERT INTO notification_email_preferences (user_id, delivery_mode) "
                    "VALUES ($1, $2)",
                    user_id,
                    mode,
                )
        return user_id, address

    async def notify(
        self,
        user_id: uuid.UUID,
        *,
        event_type: str = "PaymentDone",
        severity: str = "INFO",
        deliver_in: timedelta = timedelta(0),
    ) -> uuid.UUID:
        event_id, notification_id = uuid.uuid4(), uuid.uuid4()
        async with self.pool.acquire() as c, c.transaction():
            await c.execute(
                "INSERT INTO domain_events (id, org_id, type, entity_type, entity_id, payload, "
                "published_at) VALUES ($1, $2, $3, 'payment_request', $4, '{}'::jsonb, now())",
                event_id,
                self.org_id,
                event_type,
                uuid.uuid4(),
            )
            await c.execute(
                "INSERT INTO notifications (id, org_id, user_id, event_id, type, title, body, "
                "link, severity, deliver_at) VALUES ($1, $2, $3, $4, $5, 'T', 'B', '/x', $6, now() + $7::interval)",
                notification_id,
                self.org_id,
                user_id,
                event_id,
                event_type,
                severity,
                deliver_in,
            )
        return notification_id

    async def state(self, notification_id: uuid.UUID) -> Any:
        async with self.pool.acquire() as c:
            return await c.fetchrow(
                "SELECT email_sent_at, email_claimed_at, email_attempts, email_next_attempt_at "
                "FROM notifications WHERE id = $1",
                notification_id,
            )

    async def run(
        self,
        cadence: str,
        monkeypatch: pytest.MonkeyPatch,
        send: Callable[..., None] | None = None,
    ) -> dict[str, int]:
        def fake_send(**kwargs: Any) -> None:
            if send is not None:
                send(**kwargs)
            self.sent.append(kwargs)

        monkeypatch.setattr(delivery, "send_resend_email", fake_send)
        return await delivery.deliver_pending_emails(self.pool, settings=SETTINGS, cadence=cadence)

    def to(self, address: str) -> list[dict[str, Any]]:
        return [call for call in self.sent if call["recipient"] == address]


def _with_world(
    body: Callable[[World], Awaitable[None]],
) -> None:
    async def main() -> None:
        pool = await create_worker_pool(os.environ["TEST_DATABASE_URL"], min_size=1, max_size=2)
        try:
            await body(World(pool))
        finally:
            await pool.close()

    asyncio.run(main())


@pytest.mark.parametrize("mode", ["daily", "off"])
def test_mandatory_non_critical_event_is_emailed_not_silently_consumed(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def body(world: World) -> None:
        user_id, address = await world.user(mode)
        mandatory = await world.notify(user_id, event_type="CoverageChanged", severity="ACTION")
        optional = await world.notify(user_id, event_type="PaymentDone")

        await world.run("immediate", monkeypatch)

        assert len(world.to(address)) == 1  # the mandatory one only
        assert (await world.state(mandatory))["email_sent_at"] is not None
        if mode == "off":
            assert (await world.state(optional))["email_sent_at"] is not None  # consumed
        else:
            assert (await world.state(optional))["email_sent_at"] is None  # waits for the digest

    _with_world(body)


def test_daily_digest_is_not_split_across_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    async def body(world: World) -> None:
        monkeypatch.setattr(delivery, "USERS_PER_PAGE", 1)
        users = [await world.user("daily") for _ in range(2)]
        for user_id, _ in users:
            for _ in range(3):
                await world.notify(user_id)

        await world.run("daily", monkeypatch)

        for _, address in users:
            [call] = world.to(address)
            assert call["message"].html.count("<li>") == 3

    _with_world(body)


def test_quiet_hours_rows_wait_for_deliver_at(monkeypatch: pytest.MonkeyPatch) -> None:
    async def body(world: World) -> None:
        user_id, address = await world.user()
        held = await world.notify(user_id, deliver_in=timedelta(hours=1))

        await world.run("immediate", monkeypatch)

        assert not world.to(address)
        assert (await world.state(held))["email_sent_at"] is None

    _with_world(body)


def test_transient_failure_backs_off_and_is_not_retried_in_the_same_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def body(world: World) -> None:
        user_id, address = await world.user()
        notification = await world.notify(user_id)

        def fail(**_: Any) -> None:
            raise RuntimeError("provider down")

        await world.run("immediate", monkeypatch, send=fail)
        state = await world.state(notification)
        assert state["email_attempts"] == 1
        assert state["email_claimed_at"] is None
        assert state["email_next_attempt_at"] > datetime.now(UTC)

        calls_before = len(world.to(address))
        await world.run("immediate", monkeypatch)
        assert len(world.to(address)) == calls_before  # still backing off

    _with_world(body)


def test_permanent_failure_is_capped_and_never_fetched_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def body(world: World) -> None:
        user_id, address = await world.user()
        notification = await world.notify(user_id)

        def reject(**_: Any) -> None:
            raise PermanentEmailError("rejected")

        await world.run("immediate", monkeypatch, send=reject)
        assert (await world.state(notification))["email_attempts"] == delivery.MAX_ATTEMPTS
        async with world.pool.acquire() as c:
            await c.execute(
                "UPDATE notifications SET email_next_attempt_at = NULL WHERE id = $1", notification
            )

        calls_before = len(world.to(address))
        await world.run("immediate", monkeypatch)
        assert len(world.to(address)) == calls_before

    _with_world(body)


def test_a_claimed_row_is_not_sent_twice_before_the_lease_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def body(world: World) -> None:
        user_id, address = await world.user()
        notification = await world.notify(user_id)
        async with world.pool.acquire() as c:
            await c.execute(
                "UPDATE notifications SET email_claimed_at = now() WHERE id = $1", notification
            )

        await world.run("immediate", monkeypatch)

        assert not world.to(address)

    _with_world(body)
