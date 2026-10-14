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
from sqlalchemy.exc import IntegrityError

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.mandate.models import MandateVersion
from treasurypilot_api.recovery.models import ReviewItem
from treasurypilot_api.recovery.review_queue import (
    ReviewType,
    create_for_mandate_discrepancy,
    create_for_outcome,
    escalate_overdue,
    route_for,
)
from treasurypilot_api.recovery.routes import (
    ReviewActionRequest,
    _allowed_actions,
    _view,
    act_on_review_item,
    get_review_item,
    list_review_items,
)

API_ROOT = Path(__file__).parents[1]
USER_ID = uuid.UUID("00000000-0000-7000-8000-000000000001")
ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
REQUEST_ID = uuid.UUID("00000000-0000-7000-8000-000000000070")
MANDATE_VERSION_ID = uuid.UUID("00000000-0000-7000-8000-000000000071")


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


def test_mandate_discrepancy_is_owner_finance_ack_only() -> None:
    now = datetime(2026, 10, 14, 10, tzinfo=UTC)
    version_id = uuid.uuid4()
    item = SimpleNamespace(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        treasury_id=uuid.uuid4(),
        request_id=None,
        request_version=None,
        mandate_version_id=version_id,
        plan_id=None,
        type=ReviewType.DISCREPANCY.value,
        primary_code="MANDATE_READBACK_MISMATCH",
        reason_codes=["CONFIG_HASH_MISMATCH"],
        completed_steps=[],
        assigned_roles=[OrganizationRole.OWNER.value, OrganizationRole.FINANCE.value],
        status="Open",
        sla_due_at=now + timedelta(hours=48),
        evidence={},
        resolved_by=None,
        resolved_at=None,
        resolution=None,
        note=None,
        version=1,
    )
    finance = SimpleNamespace(
        organization_id=ORG_ID,
        user_id=USER_ID,
        roles=frozenset({OrganizationRole.FINANCE.value}),
    )

    assert route_for(ReviewType.DISCREPANCY, item.primary_code).roles == (
        OrganizationRole.FINANCE,
        OrganizationRole.OWNER,
    )
    assert _allowed_actions(item, finance) == ["ACKNOWLEDGE"]
    view = _view(item, finance)
    assert view["requestId"] is None
    assert view["requestVersion"] is None
    assert view["mandateVersionId"] == str(version_id)
    assert view["allowedActions"] == ["ACKNOWLEDGE"]


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
            await connection.execute(
                text(
                    "INSERT INTO mandate_versions (id, org_id, treasury_id, version, status, config, config_hash, valid_from, expires_at, created_by) "
                    "VALUES (:id, :org, '00000000-0000-7000-8000-000000000040', 1, 'Discrepancy', '{}', decode(repeat('ab', 32), 'hex'), "
                    "'2026-10-01T00:00:00+00:00', '2027-10-01T00:00:00+00:00', :creator)"
                ),
                {"id": MANDATE_VERSION_ID, "org": ORG_ID, "creator": USER_ID},
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
        finance = SimpleNamespace(
            organization_id=ORG_ID,
            user_id=USER_ID,
            roles=frozenset({OrganizationRole.FINANCE.value}),
        )
        with pytest.raises(AuthFailure, match="REVIEW_ITEM_NOT_FOUND"):
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
            # Escalated Owner can act, not only view (spec 8.3).
            assert _allowed_actions(uncertain, owner) == []
            uncertain.evidence_resolved = True
            assert _allowed_actions(uncertain, owner) == ["ACKNOWLEDGE"]
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

        async with sessions() as session, session.begin():
            payment = await session.scalar(
                select(PaymentRequest).where(PaymentRequest.id == REQUEST_ID)
            )
            assert payment is not None
            # A producer re-run for the newer request version refreshes the open item.
            refreshed = await create_for_outcome(
                session,
                request=payment,
                outcome=ReviewType.UNCERTAIN_TX,
                primary_code="TX_UNKNOWN",
                now=now,
            )
            assert refreshed is not None and refreshed.id == uncertain_id
            assert refreshed.request_version == payment.version
            refreshed_version = refreshed.version
            fee = await create_for_outcome(
                session,
                request=payment,
                outcome=ReviewType.FEE_APPROVAL,
                primary_code="FEE_HIGH",
                last_safe_execution_at=now + timedelta(days=1),
                now=now,
            )
            assert fee is not None
            fee_id = fee.id
        listed = await list_review_items(ORG_ID, request, None, None, None, operator)
        assert {i["id"] for i in listed["items"]} == {str(uncertain_id), str(fee_id)}
        acted = await act_on_review_item(
            ORG_ID,
            uncertain_id,
            ReviewActionRequest(action="ACKNOWLEDGE", version=refreshed_version),
            request,
            Response(),
            operator,
        )
        assert acted["item"]["status"] == "Resolved"
        deferred = await act_on_review_item(
            ORG_ID,
            fee_id,
            ReviewActionRequest(action="DEFER", note="waiting", version=1),
            request,
            Response(),
            operator,
        )
        again = await act_on_review_item(
            ORG_ID,
            fee_id,
            ReviewActionRequest(action="DEFER", version=deferred["item"]["version"]),
            request,
            Response(),
            operator,
        )
        assert again["item"]["note"] == "waiting"

        async with sessions() as session, session.begin():
            mandate_version = await session.scalar(
                select(MandateVersion).where(MandateVersion.id == MANDATE_VERSION_ID)
            )
            assert mandate_version is not None
            discrepancy = await create_for_mandate_discrepancy(
                session,
                mandate_version=mandate_version,
                primary_code="MANDATE_READBACK_MISMATCH",
                reason_codes=("CONFIG_HASH_MISMATCH",),
                expected={"configHash": "expected-hash"},
                actual={"configHash": "actual-hash"},
                now=now,
            )
            repeated = await create_for_mandate_discrepancy(
                session,
                mandate_version=mandate_version,
                primary_code="MANDATE_READBACK_MISMATCH",
                reason_codes=("CONFIG_HASH_MISMATCH",),
                expected={"configHash": "expected-hash"},
                actual={"configHash": "actual-hash"},
                now=now,
            )
            assert repeated.id == discrepancy.id
            assert discrepancy.request_id is None
            assert discrepancy.request_version is None
            assert discrepancy.mandate_version_id == MANDATE_VERSION_ID
            assert set(discrepancy.assigned_roles) == {
                OrganizationRole.OWNER.value,
                OrganizationRole.FINANCE.value,
            }
            assert discrepancy.sla_due_at == now + timedelta(hours=48)
            discrepancy_id = discrepancy.id

        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ReviewItem)
                    .where(ReviewItem.mandate_version_id == MANDATE_VERSION_ID)
                )
                == 1
            )
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(
                        ReviewItem(
                            org_id=ORG_ID,
                            treasury_id=uuid.UUID("00000000-0000-7000-8000-000000000040"),
                            request_id=REQUEST_ID,
                            request_version=1,
                            mandate_version_id=MANDATE_VERSION_ID,
                            type=ReviewType.DISCREPANCY.value,
                            primary_code="INVALID_BOTH_SUBJECTS",
                            reason_codes=[],
                            completed_steps=[],
                            assigned_roles=[OrganizationRole.OWNER.value],
                            status="Open",
                            sla_due_at=now + timedelta(hours=48),
                        )
                    )
                    await session.flush()

        listed_discrepancies = await list_review_items(
            ORG_ID, request, None, ReviewType.DISCREPANCY, None, finance
        )
        discrepancy_view = next(
            item for item in listed_discrepancies["items"] if item["id"] == str(discrepancy_id)
        )
        assert discrepancy_view["requestId"] is None
        assert discrepancy_view["requestVersion"] is None
        assert discrepancy_view["mandateVersionId"] == str(MANDATE_VERSION_ID)
        assert discrepancy_view["allowedActions"] == ["ACKNOWLEDGE"]

        detail = await get_review_item(ORG_ID, discrepancy_id, request, finance)
        assert detail["request"] is None
        assert detail["mandateVersion"] == {
            "id": str(MANDATE_VERSION_ID),
            "version": 1,
            "status": "Discrepancy",
        }
        assert detail["item"]["requestId"] is None
        assert detail["item"]["mandateVersionId"] == str(MANDATE_VERSION_ID)
        assert detail["evidence"] == {
            "resolved": False,
            "expected": {"configHash": "expected-hash"},
            "actual": {"configHash": "actual-hash"},
        }

        with pytest.raises(AuthFailure, match="ACTION_NOT_ALLOWED"):
            await act_on_review_item(
                ORG_ID,
                discrepancy_id,
                ReviewActionRequest(action="MARK_MATCHED", version=1),
                request,
                Response(),
                owner,
            )
        acknowledged = await act_on_review_item(
            ORG_ID,
            discrepancy_id,
            ReviewActionRequest(action="ACKNOWLEDGE", version=1),
            request,
            Response(),
            finance,
        )
        assert acknowledged["item"]["status"] == "Resolved"
        assert acknowledged["item"]["resolution"] == "ACKNOWLEDGE"

        async with sessions() as session, session.begin():
            await session.execute(
                text("DELETE FROM review_items WHERE mandate_version_id = :id"),
                {"id": MANDATE_VERSION_ID},
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
