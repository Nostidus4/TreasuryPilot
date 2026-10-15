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
from treasurypilot_api.execution.fee_assessment import assess_plan_fee
from treasurypilot_api.identity.auth import AuthFailure, AuthService
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.mandate.fees import (
    FeePolicyAcceptRequest,
    PlanFeeActionRequest,
    ReferencePriceRequest,
    accept_fee_policy,
    accept_plan_fee,
    defer_plan_fee,
    get_fee_policy,
    set_fee_reference_price,
)
from treasurypilot_api.mandate.models import (
    FeeAcceptance,
    FeePreset,
    MandateVersion,
    TreasuryFeePolicy,
)
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
    ReviewItemView,
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


class _FeeHistory:
    async def call(self, chain_id: int, method: str, params: list[object]) -> dict[str, object]:
        return {"baseFeePerGas": ["0x64"], "reward": [["0x1", "0x2", "0x3"]]}


class _StepUpService(AuthService):
    """Stands in for the auth service: step-up passes only once ``fresh`` is set."""

    def __init__(self) -> None:  # no storage needed
        self.fresh = False

    def require_step_up(self, access: object) -> None:
        if not self.fresh:
            raise AuthFailure(
                status=403, code="STEP_UP_REQUIRED", title="Step up", detail="Step up."
            )


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
        fee_estimate_wei=None,
        type=ReviewType.DISCREPANCY.value,
        primary_code="MANDATE_READBACK_MISMATCH",
        reason_codes=["CONFIG_HASH_MISMATCH"],
        completed_steps=[],
        assigned_roles=[OrganizationRole.OWNER.value, OrganizationRole.FINANCE.value],
        status="Open",
        sla_due_at=now + timedelta(hours=48),
        created_at=now,
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
    # The documented response model is exactly the shape the view returns.
    parsed = ReviewItemView.model_validate(view)
    assert set(parsed.model_dump(by_alias=True)) == set(view)
    assert parsed.assigned_roles == [OrganizationRole.OWNER, OrganizationRole.FINANCE]
    assert parsed.created_at == now.isoformat()


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

        step_up = _StepUpService()

        app = FastAPI()
        app.state.review_sessions = sessions
        app.state.auth_service = step_up
        request = Request({"type": "http", "app": app, "method": "POST", "path": "/"})
        owner = SimpleNamespace(
            organization_id=ORG_ID,
            user_id=USER_ID,
            roles=frozenset({OrganizationRole.OWNER.value}),
        )
        operator = SimpleNamespace(
            organization_id=ORG_ID,
            user_id=USER_ID,
            access=SimpleNamespace(),
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
            fee_plan_id = uuid.uuid4()
            fee = await create_for_outcome(
                session,
                request=payment,
                outcome=ReviewType.FEE_APPROVAL,
                primary_code="FEE_HIGH",
                plan_id=fee_plan_id,
                fee_estimate_wei=123_000_000_000_000,
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
        # Re-assessing the same request version refreshes the open item's estimate.
        async with sessions() as session, session.begin():
            payment = await session.scalar(
                select(PaymentRequest).where(PaymentRequest.id == REQUEST_ID)
            )
            assert payment is not None
            refreshed_fee = await create_for_outcome(
                session,
                request=payment,
                outcome=ReviewType.FEE_APPROVAL,
                primary_code="FEE_HIGH",
                plan_id=fee_plan_id,
                fee_estimate_wei=150_000_000_000_000,
                last_safe_execution_at=now + timedelta(days=1),
                now=now,
            )
            assert refreshed_fee is not None and refreshed_fee.id == fee_id
            assert refreshed_fee.fee_estimate_wei == 150_000_000_000_000
        fee_version = (await get_review_item(ORG_ID, fee_id, request, operator))["item"]["version"]
        assert fee_version == again["item"]["version"] + 1
        with pytest.raises(AuthFailure, match="STEP_UP_REQUIRED"):
            await act_on_review_item(
                ORG_ID,
                fee_id,
                ReviewActionRequest(action="ACCEPT_FEE", version=fee_version),
                request,
                Response(),
                operator,
            )
        step_up.fresh = True
        accepted = await act_on_review_item(
            ORG_ID,
            fee_id,
            ReviewActionRequest(action="ACCEPT_FEE", version=fee_version),
            request,
            Response(),
            operator,
        )
        assert accepted["item"]["note"] == "waiting"
        assert accepted["item"]["status"] == "Resolved"
        assert accepted["item"]["resolution"] == "ACCEPT_FEE"
        async with sessions() as session:
            fee_acceptance = await session.scalar(
                select(FeeAcceptance).where(FeeAcceptance.plan_id == fee_plan_id)
            )
            assert fee_acceptance is not None
            assert fee_acceptance.estimated_fee_wei == 150_000_000_000_000
            assert fee_acceptance.accepted_cap_wei == 150_000_000_000_000
            held_events = await session.scalar(
                text(
                    "SELECT count(*) FROM domain_events WHERE type = 'ExecutionCycleRequested' "
                    "AND entity_type = 'plan' AND entity_id = :p"
                ),
                {"p": fee_plan_id},
            )
            assert held_events == 1

        # An accepted plan proceeds under its cap without a new review item (and fails over it).
        async with sessions() as session, session.begin():
            session.add(
                TreasuryFeePolicy(
                    org_id=ORG_ID,
                    treasury_id=uuid.UUID("00000000-0000-7000-8000-000000000040"),
                    preset=FeePreset.NORMAL,
                    max_fee_multiplier_bps=20_000,
                    tip_percentile=50,
                    resend_after_s=60,
                    bump_bps=1_250,
                    per_plan_threshold_wei=1,
                    daily_budget_wei=1,
                    reference_eth_price=3_000_000_000,
                    accepted_by=USER_ID,
                    accepted_at=now,
                    version=1,
                )
            )
            payment = await session.scalar(
                select(PaymentRequest).where(PaymentRequest.id == REQUEST_ID)
            )
            assert payment is not None
            safe_at = now - timedelta(hours=1)
            held = await assess_plan_fee(
                session,
                request=payment,
                plan_id=fee_plan_id,
                estimated_fee_wei=150_000_000_000_000,
                last_safe_execution_at=safe_at,
                now=now,
            )
            assert held.assessment.decision == "PROCEED" and held.review_item_id is None
            with pytest.raises(ValueError, match="FEE_CAP_EXCEEDED"):
                await assess_plan_fee(
                    session,
                    request=payment,
                    plan_id=fee_plan_id,
                    estimated_fee_wei=150_000_000_000_001,
                    last_safe_execution_at=safe_at,
                    now=now,
                )

        # Fee-policy lifecycle: Owner-only proposals, stale refresh, preset limits, shared plan fee
        # actions.
        app.state.request_sessions = sessions
        app.state.fee_history_provider = _FeeHistory()
        treasury_id = uuid.UUID("00000000-0000-7000-8000-000000000040")

        async def pending_ids() -> list[uuid.UUID]:
            async with sessions() as session:
                return list(
                    await session.scalars(
                        select(TreasuryFeePolicy.id).where(
                            TreasuryFeePolicy.treasury_id == treasury_id,
                            TreasuryFeePolicy.accepted_at.is_(None),
                        )
                    )
                )

        assert (await get_fee_policy(ORG_ID, treasury_id, request, finance))["proposal"] is None
        assert await pending_ids() == []
        first_proposal = (await get_fee_policy(ORG_ID, treasury_id, request, owner))["proposal"]
        assert first_proposal is not None
        assert await pending_ids() == [uuid.UUID(first_proposal["id"])]
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE treasury_fee_policies SET proposed_at = now() - interval '2 hours' "
                    "WHERE accepted_at IS NULL"
                )
            )
        assert (await get_fee_policy(ORG_ID, treasury_id, request, finance))["proposal"] is None
        proposal = (await get_fee_policy(ORG_ID, treasury_id, request, owner))["proposal"]
        assert proposal is not None and proposal["id"] != first_proposal["id"]
        assert await pending_ids() == [uuid.UUID(proposal["id"])]

        # The reference price is edited on the active row; accepting carries it to the new row.
        priced = await set_fee_reference_price(
            ORG_ID,
            treasury_id,
            ReferencePriceRequest(referenceEthPrice="5000000000"),
            request,
            owner,
        )
        assert priced["feePolicy"]["referenceEthPrice"] == "5000000000"
        accepted_policy = (
            await accept_fee_policy(
                ORG_ID,
                treasury_id,
                FeePolicyAcceptRequest(proposalId=uuid.UUID(proposal["id"]), preset="FAST"),
                request,
                owner,
            )
        )["active"]
        assert accepted_policy["preset"] == "FAST"
        assert accepted_policy["referenceEthPrice"] == "5000000000"
        # No plan history: the baseline is 21,000 gas at the FAST max fee (100 * 3 + p75 tip 3).
        assert accepted_policy["perPlanThresholdWei"] == str(3 * 21_000 * 303)

        async def cycle_events(entity_type: str) -> int:
            async with sessions() as session:
                return int(
                    await session.scalar(
                        text(
                            "SELECT count(*) FROM domain_events WHERE "
                            "type = 'ExecutionCycleRequested' AND entity_type = :t"
                        ),
                        {"t": entity_type},
                    )
                    or 0
                )

        # Fee acceptance enqueues an execution cycle (EXE-003 hook).
        assert await cycle_events("fee_policy") == 1

        # Held-plan actions share one implementation with the review queue.
        async with sessions() as session, session.begin():
            payment = await session.scalar(
                select(PaymentRequest).where(PaymentRequest.id == REQUEST_ID)
            )
            assert payment is not None
            second_plan_id = uuid.uuid4()
            await create_for_outcome(
                session,
                request=payment,
                outcome=ReviewType.FEE_APPROVAL,
                primary_code="FEE_HIGH",
                plan_id=second_plan_id,
                fee_estimate_wei=7,
                last_safe_execution_at=now - timedelta(hours=1),
                now=now,
            )
        deferred_plan = await defer_plan_fee(
            ORG_ID, second_plan_id, PlanFeeActionRequest(reason="later"), request, operator
        )
        assert deferred_plan["status"] == "AwaitingFeeAcceptance"
        await defer_plan_fee(ORG_ID, second_plan_id, PlanFeeActionRequest(), request, operator)
        accepted_plan = await accept_plan_fee(
            ORG_ID, second_plan_id, PlanFeeActionRequest(), request, operator
        )
        assert accepted_plan["acceptedCapWei"] == "7"
        history = (await get_fee_policy(ORG_ID, treasury_id, request, finance))["history"]
        assert history[0]["kind"] == "PLAN_FEE" and history[0]["acceptedCapWei"] == "7"
        assert [e["at"] for e in history] == sorted((e["at"] for e in history), reverse=True)
        assert next(e for e in history if e["kind"] == "POLICY")["preset"] == "FAST"
        async with sessions() as session:
            fee_item = await session.scalar(
                select(ReviewItem).where(ReviewItem.plan_id == second_plan_id)
            )
            assert fee_item is not None
            assert (fee_item.status, fee_item.resolution, fee_item.note) == (
                "Resolved",
                "ACCEPT_FEE",
                "later",
            )
        with pytest.raises(AuthFailure, match="FEE_REVIEW_NOT_FOUND"):
            await accept_plan_fee(ORG_ID, second_plan_id, PlanFeeActionRequest(), request, operator)

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

        # RETRY/CANCEL on a PartiallyCompleted plan's stop is handed to the worker, which
        # resolves the item itself; without a queue the action fails closed.
        plan_id = uuid.UUID("00000000-0000-7000-8000-0000000000a1")
        async with sessions() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO plans (id, org_id, treasury_id, request_id, status) VALUES "
                    "(:p, :org, '00000000-0000-7000-8000-000000000040', :r, 'PartiallyCompleted')"
                ),
                {"p": plan_id, "org": ORG_ID, "r": REQUEST_ID},
            )
            payment = await session.scalar(
                select(PaymentRequest).where(PaymentRequest.id == REQUEST_ID)
            )
            assert payment is not None
            blocked = await create_for_outcome(
                session,
                request=payment,
                outcome=ReviewType.INFRA,
                primary_code="RETRY_EXHAUSTED",
                now=now,
            )
            assert blocked is not None
            blocked_id = blocked.id
            policy = await create_for_outcome(
                session,
                request=payment,
                outcome=ReviewType.POLICY_BLOCK,
                primary_code="SOURCE_BUFFER_BREACH",
                now=now,
            )
            assert policy is not None
            policy_id = policy.id
        with pytest.raises(AuthFailure, match="RECOVERY_UNAVAILABLE"):
            await act_on_review_item(
                ORG_ID,
                blocked_id,
                ReviewActionRequest(action="RETRY", version=1),
                request,
                Response(),
                operator,
            )
        queued: list[tuple[str, uuid.UUID, uuid.UUID]] = []

        class _Queue:
            def enqueue(self, action: str, request_id: uuid.UUID, actor_id: uuid.UUID) -> None:
                queued.append((action, request_id, actor_id))

        app.state.partial_recovery_queue = _Queue()
        result = await act_on_review_item(
            ORG_ID,
            blocked_id,
            ReviewActionRequest(action="RETRY", version=1),
            request,
            Response(),
            operator,
        )
        assert queued == [("RETRY", REQUEST_ID, USER_ID)]
        assert result["item"]["status"] == "Open"
        await act_on_review_item(
            ORG_ID,
            policy_id,
            ReviewActionRequest(action="CANCEL", version=1),
            request,
            Response(),
            owner,
        )
        assert queued[-1] == ("CANCEL", REQUEST_ID, USER_ID)
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
