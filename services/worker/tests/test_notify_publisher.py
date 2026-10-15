from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, time
from typing import Any
from unittest.mock import Mock

import pytest

from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.notify import publisher as publisher_module
from treasurypilot_worker.notify import routing as routing_module
from treasurypilot_worker.notify.publisher import publish_from_pool
from treasurypilot_worker.notify.routing import ROUTING_TABLE, policy_for_event


def test_approval_needed_routes_to_approvers_only() -> None:
    policy = policy_for_event("ApprovalNeeded")

    assert policy.roles == ("Approver",)
    assert policy.severity == "ACTION"


def test_routing_table_covers_documented_notification_events() -> None:
    assert {
        "ApprovalNeeded",
        "HighFlagRaised",
        "ExceptionNeeded",
        "GovernanceSignatureNeeded",
        "FeeAcceptanceNeeded",
        "PaymentDone",
        "UnknownOperation",
        "PauseRequested",
        "PauseEffective",
        "Resumed",
        "CircuitBreakerTripped",
        "UnexpectedOutflow",
        "CoverageChanged",
        "LowGas",
        "MandateExpiring",
        "Discrepancy",
    } <= ROUTING_TABLE.keys()
    assert policy_for_event("NeedsReview:Finance").roles == ("Finance",)


class _FakeTransaction:
    async def __aenter__(self) -> _FakeTransaction:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _FakeConnection:
    def __init__(self) -> None:
        self.org_id = uuid.uuid4()
        self.approver_id = uuid.uuid4()
        self.finance_id = uuid.uuid4()
        self.owner_id = uuid.uuid4()
        self.other_owner_id = uuid.uuid4()
        self.event_data = {
            "id": uuid.uuid4(),
            "org_id": self.org_id,
            "treasury_id": None,
            "type": "ApprovalNeeded",
            "entity_type": "payment_request",
            "entity_id": uuid.uuid4(),
            "payload": json.dumps({"requestId": str(uuid.uuid4())}),
            "published": False,
            "failed": False,
        }
        self.events = [self.event_data]
        self.memberships = (
            {"user_id": self.approver_id, "roles": ["Approver"]},
            {"user_id": self.finance_id, "roles": ["Finance"]},
            {"user_id": self.owner_id, "roles": ["Owner"]},
            {"user_id": self.other_owner_id, "roles": ["Owner"]},
        )
        self.notifications: dict[tuple[uuid.UUID, uuid.UUID], tuple[Any, ...]] = {}
        self.preferences: dict[uuid.UUID, tuple[dict[str, bool], dict[str, bool]]] = {}
        self.quiet_hours: dict[uuid.UUID, tuple[time, time, str]] = {}
        self.deliver_at: dict[uuid.UUID, datetime] = {}
        self.claim_query = ""
        self.webhook_event_ids: list[uuid.UUID] = []
        self.insert_query = ""

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def fetch(self, query: str, *args: object) -> list[dict[str, Any]]:
        if "FROM memberships" in query:
            roles, user_ids, creator_id, excluded = (
                set(args[1]),
                set(args[2]),
                args[3],
                set(args[4]),
            )  # type: ignore[call-overload]
            rows = []
            for membership in self.memberships:
                user_id = membership["user_id"]
                if user_id in excluded or not (
                    roles.intersection(membership["roles"])
                    or user_id in user_ids
                    or user_id == creator_id
                ):
                    continue
                channels, categories = self.preferences.get(user_id, ({}, {}))
                start, end, timezone = self.quiet_hours.get(user_id, (None, None, None))
                rows.append(
                    {
                        "user_id": user_id,
                        "channels": json.dumps(channels),
                        "categories": categories,
                        "quiet_hours_start": start,
                        "quiet_hours_end": end,
                        "timezone": timezone,
                    }
                )
            return rows
        assert "FOR UPDATE SKIP LOCKED" in query
        self.claim_query = query
        return [event for event in self.events if not event["published"] and not event["failed"]]

    async def execute(self, query: str, *args: object) -> str:
        if "INSERT INTO webhook_deliveries" in query:
            self.webhook_event_ids.append(args[1])  # type: ignore[arg-type]
            return "INSERT 0 0"
        if "ON CONFLICT (user_id, event_id) DO NOTHING" in query:
            self.insert_query = query
            assert args[0] == self.org_id
            event_id, user_ids, deliver_ats = args[1], args[7], args[8]
            inserted = 0
            for user_id, at in zip(user_ids, deliver_ats, strict=True):  # type: ignore[call-overload]
                if (user_id, event_id) not in self.notifications:
                    self.notifications[(user_id, event_id)] = args
                    self.deliver_at[user_id] = at
                    inserted += 1
            return f"INSERT 0 {inserted}"
        event = next(event for event in self.events if event["id"] == args[0])
        if "failed_at" in query:
            event["failed"] = True
            event["last_error"] = args[1]
        else:
            event["published"] = True
        return "UPDATE 1"

    @property
    def event(self) -> dict[str, Any]:
        return self.events[0]


class _FakeAcquire:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self.connection

    async def __aexit__(self, *_: object) -> None:
        return None


class _FakePool:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self.connection)


def test_publisher_claims_with_skip_locked_and_is_idempotent() -> None:
    connection = _FakeConnection()
    pool = _FakePool(connection)

    async def exercise() -> None:
        assert await publish_from_pool(pool) == 1  # type: ignore[arg-type]
        connection.event["published"] = False
        assert await publish_from_pool(pool) == 1  # type: ignore[arg-type]

    asyncio.run(exercise())

    assert "FOR UPDATE SKIP LOCKED" in connection.claim_query
    assert len(connection.notifications) == 1
    assert next(iter(connection.notifications))[0] == connection.approver_id
    assert "ON CONFLICT (user_id, event_id) DO NOTHING" in connection.insert_query


def test_execution_cycle_outbox_is_forwarded_to_core_dispatcher() -> None:
    connection = _FakeConnection()
    event = connection.event_data
    event["type"] = "ExecutionCycleRequested"
    event["treasury_id"] = uuid.uuid4()
    dispatched: list[tuple[uuid.UUID, uuid.UUID]] = []

    asyncio.run(
        publish_from_pool(
            _FakePool(connection),  # type: ignore[arg-type]
            dispatch_execution_cycle=lambda event_id, treasury_id: dispatched.append(
                (event_id, treasury_id)
            ),
        )
    )

    assert dispatched == [(event["id"], event["treasury_id"])]
    assert event["published"]
    assert connection.webhook_event_ids == []


def test_execution_cycle_dispatch_failure_leaves_event_unpublished_without_rollback() -> None:
    connection = _FakeConnection()
    event = connection.event_data
    event["type"] = "ExecutionCycleRequested"
    event["treasury_id"] = uuid.uuid4()

    def broken(_event_id: uuid.UUID, _treasury_id: uuid.UUID) -> None:
        raise ConnectionError("broker down")

    asyncio.run(
        publish_from_pool(
            _FakePool(connection),  # type: ignore[arg-type]
            dispatch_execution_cycle=broken,
        )
    )
    asyncio.run(publish_from_pool(_FakePool(connection)))  # type: ignore[arg-type]

    assert not event["published"] and not event["failed"]


def test_governance_signature_routes_only_to_safe_owner_user_ids() -> None:
    connection = _FakeConnection()
    connection.event["type"] = "GovernanceSignatureNeeded"
    connection.event["payload"] = json.dumps({"ownerUserIds": [str(connection.owner_id)]})

    async def exercise() -> None:
        assert await publish_from_pool(_FakePool(connection)) == 1  # type: ignore[arg-type]

    asyncio.run(exercise())

    recipients = {user_id for user_id, _ in connection.notifications}
    assert recipients == {connection.owner_id}


def test_preferences_filter_regular_events_but_never_mandatory_events() -> None:
    connection = _FakeConnection()
    connection.preferences[connection.approver_id] = ({"in_app": False}, {})
    connection.preferences[connection.owner_id] = ({}, {"mandatory": False})
    connection.preferences[connection.finance_id] = ({}, {"approvals": False})

    async def exercise() -> None:
        assert await publish_from_pool(_FakePool(connection)) == 1  # type: ignore[arg-type]

    asyncio.run(exercise())
    assert set(connection.notifications) == set()

    connection.events = [dict(connection.event_data)]
    event = connection.events[0]
    event.update(
        id=uuid.uuid4(),
        type="Discrepancy",
        payload="{}",
        published=False,
        failed=False,
    )

    async def publish_mandatory() -> None:
        assert await publish_from_pool(_FakePool(connection)) == 1  # type: ignore[arg-type]

    asyncio.run(publish_mandatory())
    assert {user for user, _ in connection.notifications} == {
        connection.owner_id,
        connection.other_owner_id,
        connection.finance_id,
    }


@pytest.mark.integration
@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required for the PostgreSQL notification publisher test",
)
def test_postgres_publisher_routes_and_deduplicates_notifications() -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    organization_id = uuid.uuid4()
    approver_id = uuid.uuid4()
    finance_id = uuid.uuid4()
    event_id = uuid.uuid4()
    quiet_event_id = uuid.uuid4()
    entity_id = uuid.uuid4()

    async def exercise() -> None:
        pool = await create_worker_pool(database_url, min_size=1, max_size=2)
        try:
            async with pool.acquire() as connection, connection.transaction():
                await connection.execute(
                    "INSERT INTO organizations (id, name) VALUES ($1, $2)",
                    organization_id,
                    "Notification publisher integration",
                )
                await connection.execute(
                    "INSERT INTO users (id, email) VALUES ($1, $2), ($3, $4)",
                    approver_id,
                    f"approver-{approver_id}@example.test",
                    finance_id,
                    f"finance-{finance_id}@example.test",
                )
                await connection.execute(
                    "INSERT INTO memberships (id, org_id, user_id, roles) "
                    "VALUES ($1, $2, $3, $4), ($5, $2, $6, $7)",
                    uuid.uuid4(),
                    organization_id,
                    approver_id,
                    ["Approver"],
                    uuid.uuid4(),
                    finance_id,
                    ["Finance"],
                )
                await connection.execute(
                    "INSERT INTO domain_events (id, org_id, type, entity_type, entity_id, payload) "
                    "VALUES ($1, $2, 'ApprovalNeeded', 'payment_request', $3, $4::jsonb)",
                    event_id,
                    organization_id,
                    entity_id,
                    json.dumps({"requestId": str(entity_id)}),
                )

            assert await publish_from_pool(pool) == 1
            async with pool.acquire() as connection:
                rows = await connection.fetch(
                    "SELECT user_id FROM notifications WHERE event_id = $1 ORDER BY user_id",
                    event_id,
                )
                assert [row["user_id"] for row in rows] == [approver_id]
                await connection.execute(
                    "UPDATE domain_events SET published_at = NULL WHERE id = $1", event_id
                )

            assert await publish_from_pool(pool) == 1
            async with pool.acquire() as connection:
                count = await connection.fetchval(
                    "SELECT count(*) FROM notifications WHERE event_id = $1", event_id
                )
                assert count == 1

                # A muted channel/category cannot suppress a mandatory event.
                await connection.execute(
                    "INSERT INTO notification_preferences "
                    "(user_id, channels, categories, timezone) "
                    "VALUES ($1, '{\"in_app\": false}'::jsonb, "
                    "'{\"approvals\": false, \"mandatory\": false}'::jsonb, 'UTC')",
                    finance_id,
                )
                await connection.execute(
                    "UPDATE domain_events SET type = 'Discrepancy', published_at = NULL "
                    "WHERE id = $1",
                    event_id,
                )
            assert await publish_from_pool(pool) == 1
            async with pool.acquire() as connection:
                mandatory_count = await connection.fetchval(
                    "SELECT count(*) FROM notifications WHERE event_id = $1 AND user_id = $2",
                    event_id,
                    finance_id,
                )
                assert mandatory_count == 1

                # Quiet hours hold an ordinary in-app notification until the
                # user's next local quiet-hours end.
                await connection.execute(
                    "UPDATE notification_preferences SET channels = '{\"in_app\": true}'::jsonb, "
                    "categories = '{}'::jsonb, quiet_hours_start = '00:00', "
                    "quiet_hours_end = '23:59:59', timezone = 'UTC' WHERE user_id = $1",
                    finance_id,
                )
                await connection.execute(
                    "INSERT INTO domain_events "
                    "(id, org_id, type, entity_type, entity_id, payload) "
                    "VALUES ($1, $2, 'PaymentDone', 'payment_request', $3, '{}'::jsonb)",
                    quiet_event_id,
                    organization_id,
                    entity_id,
                )
            assert await publish_from_pool(pool) == 1
            async with pool.acquire() as connection:
                deferred_at = await connection.fetchval(
                    "SELECT deliver_at FROM notifications WHERE event_id = $1 AND user_id = $2",
                    quiet_event_id,
                    finance_id,
                )
                assert deferred_at is not None and await connection.fetchval(
                    "SELECT $1::timestamptz > now()", deferred_at
                )
                await connection.execute("DELETE FROM domain_events WHERE id = $1", event_id)
                await connection.execute("DELETE FROM domain_events WHERE id = $1", quiet_event_id)
                await connection.execute("DELETE FROM organizations WHERE id = $1", organization_id)
                await connection.execute(
                    "DELETE FROM users WHERE id = ANY($1::uuid[])", [approver_id, finance_id]
                )
        finally:
            await pool.close()

    asyncio.run(exercise())


def _event(connection: _FakeConnection, event_type: str, payload: object) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "org_id": connection.org_id,
        "treasury_id": None,
        "type": event_type,
        "entity_type": "payment_request",
        "entity_id": uuid.uuid4(),
        "payload": json.dumps(payload),
        "published": False,
        "failed": False,
    }


def test_a_poison_event_is_dead_lettered_and_does_not_block_the_next() -> None:
    connection = _FakeConnection()
    poison = _event(connection, "PaymentDone", {"creatorId": "not-a-uuid"})
    connection.events = [poison, connection.event_data]

    asyncio.run(publish_from_pool(_FakePool(connection)))  # type: ignore[arg-type]

    assert poison["failed"] and "creatorId" in poison["last_error"]
    assert connection.event_data["published"]
    assert {user_id for user_id, _ in connection.notifications} == {connection.approver_id}
    # The parked event is not claimed again.
    assert asyncio.run(publish_from_pool(_FakePool(connection))) == 0  # type: ignore[arg-type]


def test_webhooks_are_enqueued_even_when_routing_dead_letters_the_event() -> None:
    connection = _FakeConnection()
    poison = _event(connection, "PaymentDone", {"creatorId": "not-a-uuid"})
    connection.events = [poison]

    asyncio.run(publish_from_pool(_FakePool(connection)))  # type: ignore[arg-type]

    assert poison["failed"]
    assert connection.webhook_event_ids == [poison["id"]]


def test_missing_owner_user_ids_falls_back_to_owners(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = Mock()
    monkeypatch.setattr(publisher_module, "logger", logger)
    connection = _FakeConnection()
    connection.events = [_event(connection, "GovernanceSignatureNeeded", {"ownerUserIds": []})]

    asyncio.run(publish_from_pool(_FakePool(connection)))  # type: ignore[arg-type]

    recipients = {user_id for user_id, _ in connection.notifications}
    assert recipients == {connection.owner_id, connection.other_owner_id}
    assert logger.warning.call_args_list[0].args[0] == "notification_recipients_missing"


def test_approval_needed_skips_the_requests_makers() -> None:
    connection = _FakeConnection()
    other_approver = uuid.uuid4()
    connection.memberships = (
        *connection.memberships,
        {"user_id": other_approver, "roles": ["Approver"]},
    )
    connection.events = [
        _event(
            connection,
            "ApprovalNeeded",
            {"requestId": str(uuid.uuid4()), "excludeUserIds": [str(connection.approver_id)]},
        )
    ]

    asyncio.run(publish_from_pool(_FakePool(connection)))  # type: ignore[arg-type]

    assert {user_id for user_id, _ in connection.notifications} == {other_approver}


def test_unknown_routing_is_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = Mock()
    monkeypatch.setattr(routing_module, "logger", logger)
    policy_for_event("NeedsReview:finance")
    policy_for_event("SomethingNew")
    assert [call.args[0] for call in logger.warning.call_args_list] == [
        "notification_review_role_unknown",
        "notification_event_type_unknown",
    ]


def test_deliver_at_defers_to_quiet_hours_end_in_the_users_zone() -> None:
    now = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)  # 22:00 in Ho Chi Minh (UTC+7)
    overnight = publisher_module.deliver_at(now, time(22), time(7), "Asia/Ho_Chi_Minh")
    assert overnight == datetime(2026, 10, 15, 0, 0, tzinfo=UTC)  # 07:00 local next day
    early = publisher_module.deliver_at(
        datetime(2026, 10, 14, 20, 0, tzinfo=UTC), time(22), time(7), "Asia/Ho_Chi_Minh"
    )
    assert early == datetime(2026, 10, 15, 0, 0, tzinfo=UTC)  # 03:00 local, same-day end
    assert publisher_module.deliver_at(now, time(23), time(7), "Asia/Ho_Chi_Minh") == now
    assert publisher_module.deliver_at(now, None, None, "UTC") == now


def test_deliver_at_falls_back_to_utc_for_an_unusable_timezone() -> None:
    now = datetime(2026, 10, 14, 23, 0, tzinfo=UTC)
    for bad in ("Not/AZone", "../etc/passwd", ""):
        assert publisher_module.deliver_at(now, time(22), time(7), bad) == datetime(
            2026, 10, 15, 7, 0, tzinfo=UTC
        )


def test_a_bad_stored_timezone_cannot_fail_the_batch() -> None:
    connection = _FakeConnection()
    connection.memberships = (
        {"user_id": connection.finance_id, "roles": ["Approver"]},
        {"user_id": connection.approver_id, "roles": ["Approver"]},
    )
    connection.quiet_hours[connection.finance_id] = (time(0), time(23, 59), "Mars/Olympus")

    asyncio.run(publish_from_pool(_FakePool(connection)))  # type: ignore[arg-type]

    assert connection.event["published"] and not connection.event["failed"]
    assert {user for user, _ in connection.notifications} == {
        connection.finance_id,
        connection.approver_id,
    }


def test_no_recipients_warning_only_when_nobody_was_targeted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = Mock()
    monkeypatch.setattr(publisher_module, "logger", logger)
    connection = _FakeConnection()
    connection.preferences[connection.approver_id] = ({"in_app": False}, {})

    asyncio.run(publish_from_pool(_FakePool(connection)))  # type: ignore[arg-type]
    assert connection.notifications == {}
    logger.warning.assert_not_called()

    connection.memberships = ()
    connection.event["published"] = False
    asyncio.run(publish_from_pool(_FakePool(connection)))  # type: ignore[arg-type]
    assert logger.warning.call_args.args[0] == "notification_without_recipients"
