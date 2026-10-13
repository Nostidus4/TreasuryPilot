from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request, Response
from sqlalchemy import func, select, text

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.recovery.models import ReviewItem
from treasurypilot_api.recovery.review_queue import (
    ReviewType,
    create_for_outcome,
    escalate_overdue,
    route_for,
)
from treasurypilot_api.recovery.routes import ReviewActionRequest, act_on_review_item

API_ROOT = Path(__file__).parents[1]
USER_ID = uuid.UUID("00000000-0000-7000-8000-000000000001")
ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
REQUEST_ID = uuid.UUID("00000000-0000-7000-8000-000000000070")


def test_route_table_and_sla() -> None:
    authority = route_for(ReviewType.NEEDS_AUTHORITY, "CAP_EXCEEDED")
    assert authority.roles == (OrganizationRole.OWNER,)
    assert authority.sla == timedelta(hours=24)
    assert route_for(ReviewType.UNCERTAIN_TX, "TX_UNKNOWN").sla == timedelta(hours=1)
    assert route_for(ReviewType.POLICY_BLOCK, "APPROVAL_INVALID").roles == (
        OrganizationRole.OPERATOR,
        OrganizationRole.APPROVER,
    )
    assert route_for(ReviewType.POLICY_BLOCK, "BUDGET_EXCEEDED").roles == (OrganizationRole.OWNER,)


async def _exercise_review_queue(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    now = datetime(2026, 10, 14, 10, tzinfo=UTC)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO users (id, email) VALUES (:id, 'review@example.test')"),
                {"id": USER_ID},
            )
            await connection.execute(
                text("INSERT INTO organizations (id, name) VALUES (:id, 'Review test')"),
                {"id": ORG_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) VALUES (11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', '[\"https://rpc\"]')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) VALUES ('00000000-0000-7000-8000-000000000030', 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES ('00000000-0000-7000-8000-000000000040', :org, 11155111, '00000000-0000-7000-8000-000000000030')"
                ),
                {"org": ORG_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES ('00000000-0000-7000-8000-000000000050', :org, 'Vendor', 'vendor')"
                ),
                {"org": ORG_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) VALUES ('00000000-0000-7000-8000-000000000060', '00000000-0000-7000-8000-000000000040', :org, '00000000-0000-7000-8000-000000000050', 'Main', decode(repeat('22', 20), 'hex'), 'Proposed')"
                ),
                {"org": ORG_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, invoice_no, issue_date, due_at, amount, asset_id) VALUES (:id, :org, '00000000-0000-7000-8000-000000000040', 11155111, '00000000-0000-7000-8000-000000000050', '00000000-0000-7000-8000-000000000060', 'INV-REVIEW', '2026-10-01', '2026-10-31', 1001, '00000000-0000-7000-8000-000000000030')"
                ),
                {"id": REQUEST_ID, "org": ORG_ID},
            )

        async with sessions() as session, session.begin():
            payment = await session.scalar(
                select(PaymentRequest).where(PaymentRequest.id == REQUEST_ID)
            )
            assert payment is not None
            assert (
                await create_for_outcome(
                    session, request=payment, outcome="ALLOW", primary_code="ALLOW", now=now
                )
                is None
            )
            first = await create_for_outcome(
                session,
                request=payment,
                outcome=ReviewType.NEEDS_AUTHORITY,
                primary_code="CAP_EXCEEDED",
                reason_codes=("CAP_EXCEEDED",),
                now=now,
            )
            second = await create_for_outcome(
                session,
                request=payment,
                outcome=ReviewType.NEEDS_AUTHORITY,
                primary_code="CAP_EXCEEDED",
                now=now,
            )
            assert first is not None and second is not None and first.id == second.id
            item_id = first.id
            assert first.sla_due_at == now + timedelta(hours=24)

        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(ReviewItem)) == 1

        app = FastAPI()
        app.state.review_sessions = sessions
        request = Request({"type": "http", "app": app, "method": "POST", "path": "/"})
        owner = SimpleNamespace(
            organization_id=ORG_ID,
            user_id=USER_ID,
            roles=frozenset({OrganizationRole.OWNER.value}),
        )
        operator = SimpleNamespace(
            organization_id=ORG_ID,
            user_id=USER_ID,
            roles=frozenset({OrganizationRole.OPERATOR.value}),
        )
        with pytest.raises(AuthFailure, match="NOT_ROUTED_ROLE"):
            await act_on_review_item(
                ORG_ID,
                item_id,
                ReviewActionRequest(action="CANCEL", version=1),
                request,
                Response(),
                operator,
            )
        with pytest.raises(AuthFailure, match="STALE_ITEM"):
            await act_on_review_item(
                ORG_ID,
                item_id,
                ReviewActionRequest(action="CANCEL", version=2),
                request,
                Response(),
                owner,
            )
        result = await act_on_review_item(
            ORG_ID,
            item_id,
            ReviewActionRequest(action="CANCEL", version=1),
            request,
            Response(),
            owner,
        )
        assert result["item"]["status"] == "Resolved"
        assert result["item"]["version"] == 2
        with pytest.raises(AuthFailure, match="STALE_ITEM"):
            await act_on_review_item(
                ORG_ID,
                item_id,
                ReviewActionRequest(action="CANCEL", version=1),
                request,
                Response(),
                owner,
            )

        async with sessions() as session, session.begin():
            payment = await session.scalar(
                select(PaymentRequest).where(PaymentRequest.id == REQUEST_ID)
            )
            assert payment is not None
            uncertain = await create_for_outcome(
                session,
                request=payment,
                outcome=ReviewType.UNCERTAIN_TX,
                primary_code="TX_UNKNOWN",
                now=now,
            )
            assert uncertain is not None
            assert await escalate_overdue(session, now=now + timedelta(hours=2)) == 1
            assert OrganizationRole.OWNER.value in uncertain.assigned_roles
            assert await escalate_overdue(session, now=now + timedelta(hours=2)) == 0
            uncertain_id = uncertain.id
            payment.version += 1
        with pytest.raises(AuthFailure, match="STALE_ITEM"):
            await act_on_review_item(
                ORG_ID,
                uncertain_id,
                ReviewActionRequest(action="ACKNOWLEDGE", version=1),
                request,
                Response(),
                operator,
            )
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL review queue test",
)
def test_postgres_review_queue_idempotency_routing_and_version() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise_review_queue(database_url))
    finally:
        command.downgrade(config, "base")
