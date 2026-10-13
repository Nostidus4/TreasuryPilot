from __future__ import annotations

import asyncio
import io
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.events.models import DomainEvent
from treasurypilot_api.invoices.models import PaymentRequest, RequestStatus, StatusEventActorType
from treasurypilot_api.invoices.state_machine import (
    RequestStateMachine,
    TransitionAction,
    TransitionActor,
    review_type_for_outcome,
)
from treasurypilot_api.review.models import ReviewAction, ReviewItem, ReviewStatus, ReviewType
from treasurypilot_api.review.routes import (
    ReviewForbidden,
    SqlAlchemyReviewRepository,
    StaleReviewItem,
)
from treasurypilot_api.review.service import default_sla_due_at, open_review_item, route_for_review

API_ROOT = Path(__file__).parents[1]


def test_review_routing_table_and_sla_defaults() -> None:
    assert route_for_review(ReviewType.NEEDS_AUTHORITY, "CAP_EXCEEDED").role == "Owner"
    assert route_for_review(ReviewType.NEEDS_AUTHORITY, "CAP_EXCEEDED").actions == {
        ReviewAction.GRANT_EXCEPTION,
        ReviewAction.CANCEL,
    }
    assert route_for_review(ReviewType.POLICY_BLOCK, "LIMIT_EXCEEDED").role == "Owner"
    assert route_for_review(ReviewType.POLICY_BLOCK, "AMOUNT_INVALID").role == "Operator"
    assert route_for_review(ReviewType.FEE_APPROVAL, "FEE_CAP").role == "Finance"
    assert route_for_review(ReviewType.UNCERTAIN_TX, "UNCERTAIN_TX").role == "Operator"
    assert route_for_review(ReviewType.DISCREPANCY, "BALANCE_MISMATCH").role == "Finance"
    assert route_for_review(ReviewType.AI_REJECTED, "AI_REJECTED").role == "Operator"
    assert route_for_review(ReviewType.INFRA, "RPC_UNAVAILABLE").role == "Operator"
    assert route_for_review(ReviewType.UNEXPECTED_OUTFLOW, "UNEXPECTED_OUTFLOW").role == "Owner"

    now = datetime(2026, 10, 13, 0, 0, tzinfo=UTC)
    assert default_sla_due_at(ReviewType.NEEDS_AUTHORITY, now=now) == now + timedelta(hours=24)
    assert default_sla_due_at(ReviewType.UNCERTAIN_TX, now=now) == now + timedelta(hours=1)
    assert default_sla_due_at(ReviewType.POLICY_BLOCK, now=now) == now + timedelta(hours=48)


@pytest.mark.parametrize(
    ("action", "reason", "expected"),
    [
        (TransitionAction.NEEDS_APPROVAL, None, ReviewType.NEEDS_AUTHORITY),
        (TransitionAction.PLAN_BLOCKED, "BUFFER_BREACH", ReviewType.POLICY_BLOCK),
        (TransitionAction.PREPARATION_FAILED, "AI_PLAN_REJECTED", ReviewType.AI_REJECTED),
        (TransitionAction.PREPARATION_FAILED, "PAYLOAD_MISMATCH", ReviewType.AI_REJECTED),
        (TransitionAction.PREPARATION_FAILED, "SIMULATION_REVERTED", ReviewType.POLICY_BLOCK),
        (TransitionAction.PREPARATION_FAILED, "RPC_TIMEOUT", ReviewType.INFRA),
        (TransitionAction.PAY_UNKNOWN, None, ReviewType.UNCERTAIN_TX),
        (TransitionAction.PLAN_ALLOWED, None, None),
    ],
)
def test_non_allow_request_outcomes_map_to_review_items(
    action: TransitionAction, reason: str | None, expected: ReviewType | None
) -> None:
    assert review_type_for_outcome(action, reason) == expected


def test_review_upgrade_and_downgrade_compile_offline() -> None:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://offline/offline")
    output = io.StringIO()
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)
    command.downgrade(config, "head:base", sql=True)

    sql = output.getvalue()
    assert "CREATE TABLE review_items" in sql
    assert "uq_review_items_open_request_type" in sql
    assert "WHERE status = 'Open'" in sql
    assert "fk_review_items_request_treasury" in sql
    assert "DROP TABLE review_items" in sql


def test_open_review_item_emits_only_on_first_insert() -> None:
    item = ReviewItem(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        treasury_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        type=ReviewType.POLICY_BLOCK.value,
        primary_code="LIMIT_EXCEEDED",
        reason_codes=["LIMIT_EXCEEDED"],
        completed_steps=[],
        assigned_role="Owner",
        status=ReviewStatus.OPEN.value,
        sla_due_at=datetime.now(UTC) + timedelta(hours=24),
        source_version=1,
        version=1,
    )

    class MemorySession:
        def __init__(self) -> None:
            self.insert_count = 0
            self.events: list[object] = []

        async def scalar(self, statement: object) -> object:
            if statement.__class__.__name__ == "Insert":
                self.insert_count += 1
                return item.id if self.insert_count == 1 else None
            return item

        def add(self, value: object) -> None:
            self.events.append(value)

    session = MemorySession()

    async def exercise() -> None:
        first, created = await open_review_item(
            cast(object, session),  # type: ignore[arg-type]
            organization_id=item.org_id,
            treasury_id=item.treasury_id,
            request_id=item.request_id,
            request_version=1,
            item_type=ReviewType.POLICY_BLOCK,
            primary_code="LIMIT_EXCEEDED",
        )
        duplicate, created_again = await open_review_item(
            cast(object, session),  # type: ignore[arg-type]
            organization_id=item.org_id,
            treasury_id=item.treasury_id,
            request_id=item.request_id,
            request_version=1,
            item_type=ReviewType.POLICY_BLOCK,
            primary_code="LIMIT_EXCEEDED",
        )
        assert first.id == duplicate.id
        assert created is True
        assert created_again is False

    asyncio.run(exercise())

    assert len(session.events) == 1


async def _integration_review_queue(database_url: str) -> None:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine, sessions = create_session_factory(database_url)
    repository = SqlAlchemyReviewRepository(sessions)
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    treasury_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    vendor_id = uuid.uuid4()
    payee_id = uuid.uuid4()
    request_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    chain_id = 1_000_000_000 + uuid.uuid4().int % 1_000_000_000

    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                {"id": user_id, "email": f"review-{user_id}@example.test"},
            )
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, name) VALUES (:id, 'Review queue integration')"
                ),
                {"id": org_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
                    "VALUES (:chain_id, 'Review Test Chain', true, 1, 'https://explorer.test', '[\"https://rpc.test\"]')"
                ),
                {"chain_id": chain_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                    "VALUES (:id, :chain_id, decode(repeat('11', 20), 'hex'), 'tUSD', 6, 'Test')"
                ),
                {"id": asset_id, "chain_id": chain_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES (:id, :org_id, :chain_id, :asset_id)"
                ),
                {"id": treasury_id, "org_id": org_id, "chain_id": chain_id, "asset_id": asset_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES (:id, :org_id, 'Review vendor', :ref)"
                ),
                {"id": vendor_id, "org_id": org_id, "ref": f"review-{vendor_id}"},
            )
            await connection.execute(
                text(
                    "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
                    "VALUES (:id, :treasury_id, :org_id, :vendor_id, 'Review payee', decode(repeat('22', 20), 'hex'), 'Active')"
                ),
                {
                    "id": payee_id,
                    "treasury_id": treasury_id,
                    "org_id": org_id,
                    "vendor_id": vendor_id,
                },
            )
            for index, request_id in enumerate(request_ids):
                await connection.execute(
                    text(
                        "INSERT INTO payment_requests "
                        "(id, org_id, treasury_id, chain_id, vendor_id, payee_id, invoice_no, issue_date, due_at, amount, asset_id) "
                        "VALUES (:id, :org_id, :treasury_id, :chain_id, :vendor_id, :payee_id, :invoice_no, '2026-10-01', '2026-10-31', 100, :asset_id)"
                    ),
                    {
                        "id": request_id,
                        "org_id": org_id,
                        "treasury_id": treasury_id,
                        "chain_id": chain_id,
                        "vendor_id": vendor_id,
                        "payee_id": payee_id,
                        "invoice_no": f"REVIEW-{index}",
                        "asset_id": asset_id,
                    },
                )
            await connection.execute(
                text("UPDATE payment_requests SET status = 'Planning' WHERE id = :request_id"),
                {"request_id": request_ids[2]},
            )

        async with sessions() as session, session.begin():
            first, created = await open_review_item(
                session,
                organization_id=org_id,
                treasury_id=treasury_id,
                request_id=request_ids[0],
                request_version=1,
                item_type=ReviewType.POLICY_BLOCK,
                primary_code="LIMIT_EXCEEDED",
            )
            assert created is True
            first_id = first.id
        async with sessions() as session, session.begin():
            duplicate, created = await open_review_item(
                session,
                organization_id=org_id,
                treasury_id=treasury_id,
                request_id=request_ids[0],
                request_version=1,
                item_type=ReviewType.POLICY_BLOCK,
                primary_code="LIMIT_EXCEEDED",
            )
            assert created is False
            assert duplicate.id == first_id

        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ReviewItem)
                    .where(ReviewItem.request_id == request_ids[0])
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DomainEvent)
                    .where(DomainEvent.entity_id == first_id)
                )
                == 1
            )

        class NoopAudit:
            async def append(self, *, session: object, entry: object) -> None:
                del session, entry

        class NoPayOperationGuard:
            async def has_in_flight_pay(self, *, session: object, request_id: uuid.UUID) -> bool:
                del session, request_id
                return False

        machine = RequestStateMachine(
            sessions,
            audit=NoopAudit(),  # type: ignore[arg-type]
            pay_operation_guard=NoPayOperationGuard(),  # type: ignore[arg-type]
        )
        result = await machine.transition(
            organization_id=org_id,
            request_id=request_ids[2],
            target=RequestStatus.NEEDS_REVIEW,
            actor=TransitionActor(
                actor_type=StatusEventActorType.SYSTEM,
                action=TransitionAction.PLAN_BLOCKED,
            ),
            reason="BUFFER_BREACH",
            review_reason_codes=("BUFFER_BREACH", "BALANCE_TOO_LOW"),
            completed_steps=[{"stepId": "refill-1", "status": "Confirmed"}],
            plan_id=uuid.uuid4(),
        )
        assert result.status == RequestStatus.NEEDS_REVIEW
        async with sessions() as session:
            transition_item = await session.scalar(
                select(ReviewItem).where(ReviewItem.request_id == request_ids[2])
            )
            assert transition_item is not None
            assert transition_item.type == ReviewType.POLICY_BLOCK.value
            assert transition_item.reason_codes == ["BUFFER_BREACH", "BALANCE_TOO_LOW"]
            assert transition_item.completed_steps == [
                {"stepId": "refill-1", "status": "Confirmed"}
            ]
            assert transition_item.plan_id is not None
            assert transition_item.source_version == result.version
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DomainEvent)
                    .where(DomainEvent.entity_id == transition_item.id)
                )
                == 1
            )

        with pytest.raises(ReviewForbidden):
            await repository.act(
                organization_id=org_id,
                item_id=first_id,
                actor_id=user_id,
                roles=("Operator",),
                action=ReviewAction.CANCEL,
                note=None,
                expected_version=1,
            )
        with pytest.raises(StaleReviewItem):
            await repository.act(
                organization_id=org_id,
                item_id=first_id,
                actor_id=user_id,
                roles=("Owner",),
                action=ReviewAction.CANCEL,
                note=None,
                expected_version=2,
            )

        async with sessions() as session, session.begin():
            request = await session.get(PaymentRequest, request_ids[0])
            assert request is not None
            request.invoice_no = "REVIEW-0-EDITED"
            await session.flush()
        with pytest.raises(StaleReviewItem):
            await repository.act(
                organization_id=org_id,
                item_id=first_id,
                actor_id=user_id,
                roles=("Owner",),
                action=ReviewAction.CANCEL,
                note=None,
                expected_version=1,
            )

        async with sessions() as session, session.begin():
            second, created = await open_review_item(
                session,
                organization_id=org_id,
                treasury_id=treasury_id,
                request_id=request_ids[1],
                request_version=1,
                item_type=ReviewType.INFRA,
                primary_code="RPC_UNAVAILABLE",
                sla_due_at=datetime.now(UTC) - timedelta(minutes=1),
            )
            assert created is True
            second_id = second.id
        assert await repository.escalate_overdue(organization_id=org_id) == 1
        escalated = await repository.get_item(
            organization_id=org_id, item_id=second_id, roles=("Owner",)
        )
        assert escalated is not None
        assert escalated.assigned_role == "Owner"
        assert escalated.version == 2

        resolved = await repository.act(
            organization_id=org_id,
            item_id=second_id,
            actor_id=user_id,
            roles=("Owner",),
            action=ReviewAction.RETRY,
            note="RPC recovered",
            expected_version=2,
        )
        assert resolved.status == ReviewStatus.RESOLVED.value
        assert resolved.resolution == ReviewAction.RETRY.value
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for review queue PostgreSQL integration tests",
)
def test_postgres_review_queue_is_idempotent_role_routed_and_versioned() -> None:
    asyncio.run(_integration_review_queue(os.environ["TP_TEST_DATABASE_URL"]))
