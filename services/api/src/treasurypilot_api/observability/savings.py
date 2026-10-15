"""Savings report versus baseline B1 (OBS-005). Definitions: docs/modules/observability/README.md."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.execution.models import GasLedger, Operation, Transaction
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.invoices.models import PaymentRequest, RequestStatusEvent
from treasurypilot_api.invoices.requests import confirmed_payment_terms
from treasurypilot_api.mandate.models import TreasuryFeePolicy, Vendor
from treasurypilot_api.observability.metrics import _utc
from treasurypilot_core.domain import (
    ApprovedRequest,
    Limits,
    PolicyView,
    Snapshot,
    WalletState,
    fee_in_asset_base_units,
)
from treasurypilot_core.engine import request_value, schedule_edf
from treasurypilot_core.money import BaseUnits

METHODOLOGY = (
    "Baseline B1 re-runs the earliest-deadline-first scheduler on the same requests and the "
    "planning-day snapshot of each executed batch. For every request, value is the engine's "
    "request_value: the early-payment discount captured, minus the gas fee of an early payment "
    "(FEE-2) and the supply interest forgone, minus late fees. Cost is the invoice amount minus "
    "value. Savings = B1 cost - actual cost, so negative savings are reported as negative. "
    "Requests B1 could not schedule within its horizon are not compared. All amounts are "
    "integer asset base units."
)
_BIG = BaseUnits(10**30)
_WALLET = "w"
_PAYEE = "p"


@dataclass(frozen=True, slots=True)
class SavingsRequest:
    request: ApprovedRequest
    invoice_number: str
    vendor_name: str
    paid_day: int
    fee_in_asset: int  # gas paid for this request, in asset base units


@dataclass(frozen=True, slots=True)
class SavingsBatch:
    snapshot: Snapshot
    policy: PolicyView
    requests: Sequence[SavingsRequest]


class SavingsTotals(ApiModel):
    baseline: str
    actual: str
    saved: str


class SavingsRow(SavingsTotals):
    request_id: str
    invoice_number: str
    vendor_name: str


class SavingsMetrics(ApiModel):
    totals: SavingsTotals
    per_request: list[SavingsRow]
    methodology: str


def compute_savings(batches: Sequence[SavingsBatch]) -> SavingsMetrics:
    rows: list[SavingsRow] = []
    for batch in batches:
        b1_day = {
            i.request_id: i.day
            for i in schedule_edf(
                [r.request for r in batch.requests], batch.snapshot, batch.policy
            ).items
        }
        for r in batch.requests:
            if r.request.id not in b1_day:
                continue
            fee = BaseUnits(r.fee_in_asset)
            amount = int(r.request.amount)
            # Same fee on both sides: only an early payment bears it (request_value).
            b1 = amount - request_value(r.request, b1_day[r.request.id], fee_in_asset=fee)
            actual = amount - request_value(r.request, r.paid_day, fee_in_asset=fee)
            rows.append(
                SavingsRow(
                    request_id=r.request.id,
                    invoice_number=r.invoice_number,
                    vendor_name=r.vendor_name,
                    baseline=str(b1),
                    actual=str(actual),
                    saved=str(b1 - actual),
                )
            )
    return SavingsMetrics(
        totals=SavingsTotals(
            baseline=str(sum(int(x.baseline) for x in rows)),
            actual=str(sum(int(x.actual) for x in rows)),
            saved=str(sum(int(x.saved) for x in rows)),
        ),
        per_request=rows,
        methodology=METHODOLOGY,
    )


def _day(at: datetime) -> int:
    return int(at.timestamp()) // 86_400


def _snapshot(day: int) -> Snapshot:
    # shortcut: no planner snapshot is persisted yet, so B1 runs on an unconstrained one
    # (no caps, ample liquidity, payee active); replace with the stored snapshot when it lands.
    wallet = WalletState(address=_WALLET, balance=_BIG, buffer=BaseUnits(0), target=BaseUnits(0))
    source = wallet.model_copy(update={"address": "src"})
    return Snapshot(
        day=day,
        source=source,
        operational={_WALLET: wallet},
        used_today={"pay": BaseUnits(0), "refill": BaseUnits(0)},
        payee_active_day={_PAYEE: 0},
        safe_usdc=_BIG,
        a_usdc=BaseUnits(0),
        pool_available=BaseUnits(0),
        supply_rate_bps=0,
        borrow_rate_bps=0,
        debt=BaseUnits(0),
    )


_POLICY = PolicyView(
    pay=Limits(per_request=_BIG, daily=_BIG),
    refill=Limits(per_request=_BIG, daily=_BIG),
    cooling_seconds=0,
)


async def load_savings_batches(
    session: AsyncSession, org_id: uuid.UUID, start: datetime, end: datetime
) -> list[SavingsBatch]:
    paid = (
        select(RequestStatusEvent.request_id)
        .where(RequestStatusEvent.to_status == "Paid", RequestStatusEvent.at.between(start, end))
        .distinct()
    )
    rows = (
        await session.execute(
            select(PaymentRequest, Vendor.name)
            .join(Vendor, Vendor.id == PaymentRequest.vendor_id)
            .where(PaymentRequest.org_id == org_id, PaymentRequest.id.in_(paid))
            .order_by(PaymentRequest.id)
        )
    ).all()
    ids = [req.id for req, _ in rows]
    first: dict[tuple[uuid.UUID, str], datetime] = {}
    for rid, to, at in await session.execute(
        select(RequestStatusEvent.request_id, RequestStatusEvent.to_status, RequestStatusEvent.at)
        .where(
            RequestStatusEvent.request_id.in_(ids),
            RequestStatusEvent.to_status.in_(("Scheduled", "Paid")),
        )
        .order_by(RequestStatusEvent.at.desc())  # earliest wins
    ):
        first[rid, to] = _utc(at)
    fees: dict[uuid.UUID, int] = defaultdict(int)
    for rid, fee in await session.execute(
        select(Operation.request_id, func.sum(GasLedger.fee_wei))
        .join(Transaction, Transaction.operation_id == Operation.id)
        .join(GasLedger, GasLedger.transaction_id == Transaction.id)
        .where(Operation.request_id.in_(ids))
        .group_by(Operation.request_id)
    ):
        fees[rid] = int(fee)
    prices = {
        treasury: price
        for treasury, price in await session.execute(
            select(TreasuryFeePolicy.treasury_id, TreasuryFeePolicy.reference_eth_price).where(
                TreasuryFeePolicy.org_id == org_id,
                TreasuryFeePolicy.accepted_at.is_not(None),
                TreasuryFeePolicy.superseded_at.is_(None),
            )
        )
    }

    by_day: dict[int, list[SavingsRequest]] = defaultdict(list)
    for req, vendor in rows:
        terms = confirmed_payment_terms(req)
        scheduled, paid_at = first.get((req.id, "Scheduled")), first[req.id, "Paid"]
        if terms is None or req.amount is None or scheduled is None:
            continue
        price = prices.get(req.treasury_id)
        # shortcut: no stored ETH price means the early-payment fee is not converted (0).
        fee = fee_in_asset_base_units(fees[req.id], int(price)) if price else 0
        approved = ApprovedRequest(
            id=str(req.id),
            paying_wallet=_WALLET,
            payee=_PAYEE,
            amount=BaseUnits(int(req.amount)),
            approved_seq=0,
            terms=terms,
        )
        by_day[_day(scheduled)].append(
            SavingsRequest(approved, req.invoice_no or "", vendor, _day(paid_at), fee)
        )
    return [SavingsBatch(_snapshot(d), _POLICY, rs) for d, rs in sorted(by_day.items())]


router = APIRouter(prefix="/v1", tags=["metrics"])


@router.get(
    "/orgs/{organization_id}/metrics/savings",
    response_model=SavingsMetrics,
    openapi_extra={"x-organization-scoped": True},
)
async def get_savings_metrics(
    organization_id: uuid.UUID,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(require_role(OrganizationRole.OWNER, OrganizationRole.FINANCE)),
    ],
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> SavingsMetrics:
    if member.organization_id != organization_id:
        raise AuthFailure(
            status=404, code="NOT_FOUND", title="Not found", detail="Organization not found."
        )
    factory = getattr(request.app.state, "request_sessions", None)
    if factory is None:
        raise AuthFailure(
            status=503,
            code="METRICS_UNAVAILABLE",
            title="Metrics unavailable",
            detail="Metrics storage is not configured.",
        )
    end = _utc(end or datetime.now(UTC))
    start = _utc(start or end - timedelta(days=30))
    if start > end or (end - start).days > 366:
        raise AuthFailure(
            status=422, code="INVALID_PERIOD", title="Invalid period", detail="Bad from/to range."
        )
    sessions = cast(async_sessionmaker[AsyncSession], factory)
    async with sessions() as session:
        batches = await load_savings_batches(session, organization_id, start, end)
    return compute_savings(batches)
