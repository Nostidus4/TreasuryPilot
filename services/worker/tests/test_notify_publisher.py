from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import pytest

from treasurypilot_worker.locks import create_worker_pool
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
        self.event = {
            "id": uuid.uuid4(),
            "org_id": self.org_id,
            "treasury_id": None,
            "type": "ApprovalNeeded",
            "entity_type": "payment_request",
            "entity_id": uuid.uuid4(),
            "payload": json.dumps({"requestId": str(uuid.uuid4())}),
            "published": False,
        }
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
        if "FOR UPDATE SKIP LOCKED" in query:
            self.claim_query = query
            return [self.event] if not self.event["published"] else []
        assert "m.roles && $2::text[]" in query
        roles = set(args[1])
        user_ids = set(args[2])
        creator_id = args[3]
        return [
            membership
            for membership in self.memberships
            if roles.intersection(membership["roles"])
            or membership["user_id"] in user_ids
            or membership["user_id"] == creator_id
        ]

    async def execute(self, query: str, *args: object) -> str:
        if "ON CONFLICT (user_id, event_id) DO NOTHING" in query:
            self.insert_query = query
            user_id = args[2]
            event_id = args[3]
            key = (user_id, event_id)
            if key in self.notifications:
                return "INSERT 0 0"
            self.notifications[key] = args
            return "INSERT 0 1"
        assert "UPDATE domain_events" in query
        self.event["published"] = True
        return "UPDATE 1"


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
