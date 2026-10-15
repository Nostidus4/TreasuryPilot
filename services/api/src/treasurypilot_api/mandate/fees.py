"""Fee proposal, Owner acceptance, and held-plan fee decisions (FEE-1 … FEE-3)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Protocol, cast

from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.execution.models import GasLedger, Operation, Transaction
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.identity.rbac import MemberAccess, require_member, require_role
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.mandate.models import FeeAcceptance, FeePreset, TreasuryFeePolicy
from treasurypilot_api.treasury.models import Treasury
from treasurypilot_core.domain.fee_policy import (
    PRESETS,
    propose_fee_policy,
)
from treasurypilot_core.domain.fee_policy import (
    FeePreset as DomainFeePreset,
)

router = APIRouter(prefix="/v1/orgs/{organization_id}", tags=["fees"])


class FeeHistoryProvider(Protocol):
    async def call(self, chain_id: int, method: str, params: list[object]) -> Any: ...


class FeePolicyAcceptRequest(ApiModel):
    proposal_id: uuid.UUID
    preset: FeePreset | None = None


class ReferencePriceRequest(ApiModel):
    # Asset base units per ETH. Keep this a decimal string to avoid JS number rounding.
    reference_eth_price: str = Field(
        alias="referenceEthPrice", pattern=r"^[1-9][0-9]*$", max_length=78
    )


class PlanFeeActionRequest(ApiModel):
    reason: str | None = Field(default=None, max_length=4_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason must not be blank")
        return normalized


def _failure(status: int, code: str, detail: str) -> AuthFailure:
    return AuthFailure(
        status=status, code=code, title=code.replace("_", " ").title(), detail=detail
    )


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions = getattr(request.app.state, "request_sessions", None)
    if sessions is None:
        raise _failure(503, "FEE_POLICY_UNAVAILABLE", "Fee policy storage is not configured.")
    return cast(async_sessionmaker[AsyncSession], sessions)


def _history_provider(request: Request) -> FeeHistoryProvider:
    provider = getattr(request.app.state, "fee_history_provider", None)
    if provider is None:
        raise _failure(503, "FEE_HISTORY_UNAVAILABLE", "Chain fee history is not configured.")
    return cast(FeeHistoryProvider, provider)


def _wei(value: int | None) -> str | None:
    return str(value) if value is not None else None


def _policy_view(policy: TreasuryFeePolicy | None) -> dict[str, object] | None:
    if policy is None:
        return None
    return {
        "id": str(policy.id),
        "version": policy.version,
        "preset": policy.preset.value,
        "maxFeeMultiplierBps": policy.max_fee_multiplier_bps,
        "tipPercentile": policy.tip_percentile,
        "resendAfterS": policy.resend_after_s,
        "bumpBps": policy.bump_bps,
        "perPlanThresholdWei": str(policy.per_plan_threshold_wei),
        "dailyBudgetWei": str(policy.daily_budget_wei),
        "referenceEthPrice": _wei(policy.reference_eth_price),
        "referenceEthPriceUpdatedAt": (
            policy.updated_at.isoformat() if policy.reference_eth_price is not None else None
        ),
        "acceptedAt": policy.accepted_at.isoformat() if policy.accepted_at else None,
    }


def _proposal_view(policy: TreasuryFeePolicy | None) -> dict[str, object] | None:
    if policy is None:
        return None
    return {
        **(_policy_view(policy) or {}),
        "proposedAt": policy.proposed_at.isoformat(),
        "basis": {
            "avgPlanFee7dWei": str(policy.avg_plan_fee_7d_wei),
            "p90PlanFee7dWei": str(policy.p90_plan_fee_7d_wei),
            "plansPerDay7d": float(policy.plans_per_day_7d),
        },
    }


async def _daily_spend(session: AsyncSession, treasury_id: uuid.UUID, day: date) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(GasLedger.fee_wei), 0)).where(
            GasLedger.treasury_id == treasury_id,
            GasLedger.day == day,
            GasLedger.payer == "EXECUTOR",
        )
    )
    return int(total or 0)


async def _last_week_plan_fees(
    session: AsyncSession, treasury_id: uuid.UUID, today: date
) -> list[int]:
    # Plans are one-per-request in M10 §4. Until the durable plans table lands,
    # aggregate confirmed executor gas by request through the outbox rows.
    statement = (
        select(Operation.request_id, func.sum(GasLedger.fee_wei))
        .join(Transaction, Transaction.operation_id == Operation.id)
        .join(GasLedger, GasLedger.transaction_id == Transaction.id)
        .where(
            Operation.treasury_id == treasury_id,
            GasLedger.treasury_id == treasury_id,
            GasLedger.payer == "EXECUTOR",
            GasLedger.day >= today - timedelta(days=6),
            Transaction.status.in_(("Confirmed", "Reverted")),
        )
        .group_by(Operation.request_id)
    )
    return [int(fee or 0) for _, fee in (await session.execute(statement)).all()]


async def _rpc_fee_history(request: Request, *, chain_id: int) -> tuple[int, list[int]]:
    try:
        raw = await _history_provider(request).call(
            chain_id, "eth_feeHistory", ["0x14", "latest", [25, 50, 75]]
        )
        if not isinstance(raw, dict):
            raise ValueError("feeHistory response must be an object")
        base_fees_raw = raw["baseFeePerGas"]
        rewards_raw = raw["reward"]
        if not isinstance(base_fees_raw, list) or not base_fees_raw:
            raise ValueError("feeHistory has no base fees")
        if not isinstance(rewards_raw, list):
            raise ValueError("feeHistory rewards are missing")

        def parse(value: object) -> int:
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                return int(value, 16) if value.startswith("0x") else int(value)
            raise ValueError("feeHistory contains an invalid integer")

        base_fee = parse(base_fees_raw[-1])
        tips = [parse(item) for block in rewards_raw if isinstance(block, list) for item in block]
        return base_fee, tips
    except Exception:
        # Provider errors may contain credential-bearing URLs. Do not expose them in a response.
        raise _failure(
            503,
            "FEE_HISTORY_UNAVAILABLE",
            "The chain RPC could not provide fee history.",
        ) from None


async def _view_for_treasury(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
) -> tuple[TreasuryFeePolicy | None, TreasuryFeePolicy | None, int] | None:
    treasury = await session.scalar(
        select(Treasury).where(Treasury.id == treasury_id, Treasury.org_id == organization_id)
    )
    if treasury is None:
        return None
    active = await session.scalar(
        select(TreasuryFeePolicy).where(
            TreasuryFeePolicy.treasury_id == treasury_id,
            TreasuryFeePolicy.accepted_at.is_not(None),
            TreasuryFeePolicy.superseded_at.is_(None),
        )
    )
    pending = await session.scalar(
        select(TreasuryFeePolicy).where(
            TreasuryFeePolicy.treasury_id == treasury_id,
            TreasuryFeePolicy.accepted_at.is_(None),
            TreasuryFeePolicy.superseded_at.is_(None),
        )
    )
    return active, pending, treasury.chain_id


@router.get("/treasuries/{treasury_id}/fee-policy", openapi_extra={"x-organization-scoped": True})
async def get_fee_policy(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> dict[str, object]:
    today = datetime.now(UTC).date()
    sessions = _sessions(request)
    async with sessions() as session:
        state = await _view_for_treasury(
            session,
            organization_id=member.organization_id,
            treasury_id=treasury_id,
        )
        if state is None:
            raise _failure(404, "TREASURY_NOT_FOUND", "The treasury is unavailable.")
        active, pending, chain_id = state
        plan_fees = (
            await _last_week_plan_fees(session, treasury_id, today) if pending is None else []
        )

    if pending is None:
        base_fee, tips = await _rpc_fee_history(request, chain_id=chain_id)
        proposal = propose_fee_policy(
            plan_fees_wei=plan_fees,
            plans_last_7d=len(plan_fees),
            base_fee_per_gas_wei=base_fee,
            priority_fees_wei=tips,
            preset=DomainFeePreset.NORMAL,
        )
        async with sessions() as session, session.begin():
            treasury = await session.scalar(
                select(Treasury)
                .where(Treasury.id == treasury_id, Treasury.org_id == member.organization_id)
                .with_for_update()
            )
            if treasury is None:
                raise _failure(404, "TREASURY_NOT_FOUND", "The treasury is unavailable.")
            pending = await session.scalar(
                select(TreasuryFeePolicy)
                .where(
                    TreasuryFeePolicy.treasury_id == treasury_id,
                    TreasuryFeePolicy.accepted_at.is_(None),
                    TreasuryFeePolicy.superseded_at.is_(None),
                )
                .with_for_update()
            )
            if pending is None:
                active = await session.scalar(
                    select(TreasuryFeePolicy)
                    .where(
                        TreasuryFeePolicy.treasury_id == treasury_id,
                        TreasuryFeePolicy.accepted_at.is_not(None),
                        TreasuryFeePolicy.superseded_at.is_(None),
                    )
                    .with_for_update()
                )
                version = await session.scalar(
                    select(func.max(TreasuryFeePolicy.version)).where(
                        TreasuryFeePolicy.treasury_id == treasury_id
                    )
                )
                config = PRESETS[DomainFeePreset.NORMAL]
                pending = TreasuryFeePolicy(
                    id=uuid7(),
                    org_id=member.organization_id,
                    treasury_id=treasury_id,
                    preset=FeePreset.NORMAL,
                    max_fee_multiplier_bps=config.max_fee_multiplier_bps,
                    tip_percentile=config.tip_percentile,
                    resend_after_s=config.resend_after_s,
                    bump_bps=config.bump_bps,
                    per_plan_threshold_wei=proposal.per_plan_threshold_wei,
                    daily_budget_wei=proposal.daily_budget_wei,
                    reference_eth_price=(active.reference_eth_price if active else None),
                    avg_plan_fee_7d_wei=proposal.avg_plan_fee_7d_wei,
                    p90_plan_fee_7d_wei=proposal.p90_plan_fee_7d_wei,
                    plans_per_day_7d=proposal.plans_per_day_7d,
                    accepted_by=None,
                    accepted_at=None,
                    version=int(version or 0) + 1,
                )
                session.add(pending)
                await session.flush()
            active = await session.scalar(
                select(TreasuryFeePolicy).where(
                    TreasuryFeePolicy.treasury_id == treasury_id,
                    TreasuryFeePolicy.accepted_at.is_not(None),
                    TreasuryFeePolicy.superseded_at.is_(None),
                )
            )

    async with sessions() as session:
        spent = await _daily_spend(session, treasury_id, today)
        current = await _view_for_treasury(
            session,
            organization_id=member.organization_id,
            treasury_id=treasury_id,
        )
    if current is None:
        raise _failure(404, "TREASURY_NOT_FOUND", "The treasury is unavailable.")
    active, pending, _ = current
    return {
        "active": _policy_view(active),
        "proposal": _proposal_view(pending),
        "spentTodayWei": str(spent),
        "day": today.isoformat(),
    }


@router.post(
    "/treasuries/{treasury_id}/fee-policy/accept",
    openapi_extra={"x-organization-scoped": True},
)
async def accept_fee_policy(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payload: FeePolicyAcceptRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_role(OrganizationRole.OWNER, step_up=True))],
) -> dict[str, object]:
    now = datetime.now(UTC)
    async with _sessions(request)() as session, session.begin():
        treasury = await session.scalar(
            select(Treasury)
            .where(Treasury.id == treasury_id, Treasury.org_id == member.organization_id)
            .with_for_update()
        )
        if treasury is None:
            raise _failure(404, "TREASURY_NOT_FOUND", "The treasury is unavailable.")
        proposal = await session.scalar(
            select(TreasuryFeePolicy)
            .where(
                TreasuryFeePolicy.id == payload.proposal_id,
                TreasuryFeePolicy.treasury_id == treasury_id,
                TreasuryFeePolicy.org_id == member.organization_id,
                TreasuryFeePolicy.accepted_at.is_(None),
                TreasuryFeePolicy.superseded_at.is_(None),
            )
            .with_for_update()
        )
        if proposal is None:
            raise _failure(409, "FEE_PROPOSAL_STALE", "Reload the current fee proposal.")
        active = await session.scalar(
            select(TreasuryFeePolicy)
            .where(
                TreasuryFeePolicy.treasury_id == treasury_id,
                TreasuryFeePolicy.accepted_at.is_not(None),
                TreasuryFeePolicy.superseded_at.is_(None),
            )
            .with_for_update()
        )
        if active is not None:
            active.superseded_at = now
            active.updated_at = now
            active.updated_by = member.user_id
        selected = (
            DomainFeePreset(payload.preset.value) if payload.preset else DomainFeePreset.NORMAL
        )
        config = PRESETS[selected]
        proposal.preset = FeePreset(selected.value)
        proposal.max_fee_multiplier_bps = config.max_fee_multiplier_bps
        proposal.tip_percentile = config.tip_percentile
        proposal.resend_after_s = config.resend_after_s
        proposal.bump_bps = config.bump_bps
        proposal.accepted_by = member.user_id
        proposal.accepted_at = now
        proposal.updated_by = member.user_id
        proposal.updated_at = now
        await session.flush()
        await session.refresh(proposal)
        active_view = _policy_view(proposal)
    return {"active": active_view}


@router.put(
    "/treasuries/{treasury_id}/fee-policy/reference-price",
    openapi_extra={"x-organization-scoped": True},
)
async def set_fee_reference_price(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    payload: ReferencePriceRequest,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_role(OrganizationRole.OWNER, step_up=True))],
) -> dict[str, object]:
    value = int(payload.reference_eth_price)
    now = datetime.now(UTC)
    async with _sessions(request)() as session, session.begin():
        treasury = await session.scalar(
            select(Treasury)
            .where(Treasury.id == treasury_id, Treasury.org_id == member.organization_id)
            .with_for_update()
        )
        if treasury is None:
            raise _failure(404, "TREASURY_NOT_FOUND", "The treasury is unavailable.")
        policy = await session.scalar(
            select(TreasuryFeePolicy)
            .where(
                TreasuryFeePolicy.treasury_id == treasury_id,
                TreasuryFeePolicy.accepted_at.is_not(None),
                TreasuryFeePolicy.superseded_at.is_(None),
            )
            .with_for_update()
        )
        if policy is None:
            policy = await session.scalar(
                select(TreasuryFeePolicy)
                .where(
                    TreasuryFeePolicy.treasury_id == treasury_id,
                    TreasuryFeePolicy.accepted_at.is_(None),
                    TreasuryFeePolicy.superseded_at.is_(None),
                )
                .with_for_update()
            )
        if policy is None:
            raise _failure(
                409,
                "FEE_PROPOSAL_REQUIRED",
                "Load a fee proposal before setting its reference price.",
            )
        policy.reference_eth_price = value
        policy.updated_by = member.user_id
        policy.updated_at = now
        await session.flush()
        await session.refresh(policy)
        result = _policy_view(policy)
    return {"feePolicy": result, "referenceEthPriceSource": "OWNER_LABELLED_SETTING"}


async def _act_on_fee_review(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    plan_id: uuid.UUID,
    user_id: uuid.UUID,
    roles: frozenset[str],
    action: str,
    reason: str | None,
) -> dict[str, object]:
    from treasurypilot_api.recovery.models import ReviewItem

    item = await session.scalar(
        select(ReviewItem)
        .where(
            ReviewItem.org_id == organization_id,
            ReviewItem.plan_id == plan_id,
            ReviewItem.type == "FEE_APPROVAL",
            ReviewItem.status == "Open",
        )
        .with_for_update()
    )
    if item is None or roles.isdisjoint(item.assigned_roles):
        raise _failure(404, "FEE_REVIEW_NOT_FOUND", "The held plan is unavailable.")
    if item.fee_estimate_wei is None:
        raise _failure(409, "FEE_REVIEW_INCOMPLETE", "The held plan is missing its fee estimate.")
    payment = await session.scalar(
        select(PaymentRequest).where(
            PaymentRequest.id == item.request_id,
            PaymentRequest.org_id == organization_id,
        )
    )
    if payment is None or payment.version != item.request_version:
        raise _failure(409, "FEE_REVIEW_STALE", "Reload the held plan before acting.")
    now = datetime.now(UTC)
    if action == "ACCEPT_FEE":
        existing = await session.scalar(
            select(FeeAcceptance).where(FeeAcceptance.plan_id == plan_id)
        )
        if existing is not None:
            raise _failure(
                409, "FEE_ALREADY_ACCEPTED", "This plan already has an accepted fee cap."
            )
        accepted = FeeAcceptance(
            id=uuid7(),
            org_id=organization_id,
            plan_id=plan_id,
            estimated_fee_wei=item.fee_estimate_wei,
            accepted_cap_wei=item.fee_estimate_wei,
            accepted_by=user_id,
            at=now,
            reason=reason,
        )
        session.add(accepted)
    item.note = reason
    if action == "ACCEPT_FEE":
        item.status = "Resolved"
        item.resolution = action
        item.resolved_by = user_id
        item.resolved_at = now
    await session.flush()
    await session.refresh(item)
    return {
        "planId": str(plan_id),
        "status": "FeeAccepted" if action == "ACCEPT_FEE" else "Deferred",
        "acceptedCapWei": str(item.fee_estimate_wei) if action == "ACCEPT_FEE" else None,
        "reviewItemId": str(item.id),
        "reviewItemVersion": item.version,
    }


_fee_action_roles = require_role(
    OrganizationRole.OWNER, OrganizationRole.FINANCE, OrganizationRole.OPERATOR
)


@router.post("/plans/{plan_id}/fee/accept", openapi_extra={"x-organization-scoped": True})
async def accept_plan_fee(
    organization_id: uuid.UUID,
    plan_id: uuid.UUID,
    payload: PlanFeeActionRequest,
    request: Request,
    member: MemberAccess = Depends(_fee_action_roles),  # noqa: B008
) -> dict[str, object]:
    async with _sessions(request)() as session, session.begin():
        return await _act_on_fee_review(
            session,
            organization_id=member.organization_id,
            plan_id=plan_id,
            user_id=member.user_id,
            roles=member.roles,
            action="ACCEPT_FEE",
            reason=payload.reason,
        )


@router.post("/plans/{plan_id}/fee/defer", openapi_extra={"x-organization-scoped": True})
async def defer_plan_fee(
    organization_id: uuid.UUID,
    plan_id: uuid.UUID,
    payload: PlanFeeActionRequest,
    request: Request,
    member: MemberAccess = Depends(_fee_action_roles),  # noqa: B008
) -> dict[str, object]:
    async with _sessions(request)() as session, session.begin():
        return await _act_on_fee_review(
            session,
            organization_id=member.organization_id,
            plan_id=plan_id,
            user_id=member.user_id,
            roles=member.roles,
            action="DEFER",
            reason=payload.reason,
        )
