from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any
from unittest.mock import Mock

import pytest

from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.notify import publisher as publisher_module
from treasurypilot_worker.notify import routing as routing_module
from treasurypilot_worker.notify.publisher import _link, publish_from_pool
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


def test_review_notifications_link_to_the_review_item() -> None:
    review_id = uuid.uuid4()
    assert _link("review_item", review_id, uuid.uuid4()) == f"/review-items/{review_id}"


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
        self.claim_query = ""
        self.insert_query = ""

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def fetch(self, query: str, *args: object) -> list[dict[str, Any]]:
        assert "FOR UPDATE SKIP LOCKED" in query
        self.claim_query = query
        return [event for event in self.events if not event["published"] and not event["failed"]]

    async def execute(self, query: str, *args: object) -> str:
        if "ON CONFLICT (user_id, event_id) DO NOTHING" in query:
            self.insert_query = query
            org_id, event_id = args[0], args[1]
            roles, user_ids, creator_id, excluded = (
                set(args[7]),
                set(args[8]),
                args[9],
                set(args[10]),
            )
            inserted = 0
            for membership in self.memberships:
                user_id = membership["user_id"]
                if user_id in excluded:
                    continue
                if (
                    roles.intersection(membership["roles"])
                    or user_id in user_ids
                    or user_id == creator_id
                ) and (user_id, event_id) not in self.notifications:
                    self.notifications[(user_id, event_id)] = args
                    inserted += 1
            assert org_id == self.org_id
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


def test_governance_signature_routes_only_to_safe_owner_user_ids() -> None:
    connection = _FakeConnection()
    connection.event["type"] = "GovernanceSignatureNeeded"
    connection.event["payload"] = json.dumps({"ownerUserIds": [str(connection.owner_id)]})

    async def exercise() -> None:
        assert await publish_from_pool(_FakePool(connection)) == 1  # type: ignore[arg-type]

    asyncio.run(exercise())

    recipients = {user_id for user_id, _ in connection.notifications}
    assert recipients == {connection.owner_id}


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
                await connection.execute("DELETE FROM domain_events WHERE id = $1", event_id)
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
