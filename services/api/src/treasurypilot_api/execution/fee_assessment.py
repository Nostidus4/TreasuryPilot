"""Apply an accepted treasury fee policy before a plan is attested (EXE-012)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.execution.models import GasLedger
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.mandate.models import TreasuryFeePolicy
from treasurypilot_api.recovery.models import ReviewItem
from treasurypilot_api.recovery.review_queue import ReviewType, create_for_outcome
from treasurypilot_api.treasury.models import Treasury
from treasurypilot_core.domain.fee_policy import FeeAssessment, FeeDecision, assess_fee


class FeePolicyUnavailable(ValueError):
    """The treasury cannot execute because the Owner has not accepted a fee policy."""


@dataclass(frozen=True, slots=True)
class PlanFeeAssessment:
    assessment: FeeAssessment
    review_item_id: uuid.UUID | None


async def assess_plan_fee(
    session: AsyncSession,
    *,
    request: PaymentRequest,
    plan_id: uuid.UUID,
    estimated_fee_wei: int,
    last_safe_execution_at: datetime,
    now: datetime | None = None,
) -> PlanFeeAssessment:
    """Evaluate actual gas estimate against accepted thresholds and create last-day review.

    Callers hold the treasury row lock while computing the plan (M10's single-flight
    guarantee); this function re-locks it defensively before reading policy and spend.
    The daily counter is the gas ledger total attributed to the mined block's UTC day.
    """

    current = now or datetime.now(UTC)
    current = current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)
    treasury = await session.scalar(
        select(Treasury)
        .where(Treasury.id == request.treasury_id, Treasury.org_id == request.org_id)
        .with_for_update()
    )
    if treasury is None:
        raise FeePolicyUnavailable("treasury not found")
    policy = await session.scalar(
        select(TreasuryFeePolicy).where(
            TreasuryFeePolicy.treasury_id == request.treasury_id,
            TreasuryFeePolicy.org_id == request.org_id,
            TreasuryFeePolicy.accepted_at.is_not(None),
            TreasuryFeePolicy.superseded_at.is_(None),
        )
    )
    if policy is None:
        raise FeePolicyUnavailable("Owner has not accepted a fee policy")
    spent = await session.scalar(
        select(func.coalesce(func.sum(GasLedger.fee_wei), 0)).where(
            GasLedger.treasury_id == request.treasury_id,
            GasLedger.day == current.date(),
            GasLedger.payer == "EXECUTOR",
        )
    )
    result = assess_fee(
        estimated_fee_wei=estimated_fee_wei,
        per_plan_threshold_wei=policy.per_plan_threshold_wei,
        spent_today_wei=int(spent or 0),
        daily_budget_wei=policy.daily_budget_wei,
        last_safe_execution_at=last_safe_execution_at,
        now=current,
    )
    item: ReviewItem | None = None
    if result.decision is FeeDecision.AWAITING_FEE_ACCEPTANCE:
        item = await create_for_outcome(
            session,
            request=request,
            outcome=ReviewType.FEE_APPROVAL,
            primary_code=result.reason_code or "FEE_APPROVAL_REQUIRED",
            reason_codes=(result.reason_code or "FEE_APPROVAL_REQUIRED",),
            plan_id=plan_id,
            fee_estimate_wei=estimated_fee_wei,
            last_safe_execution_at=last_safe_execution_at,
            now=current,
        )
    return PlanFeeAssessment(result, item.id if item is not None else None)
