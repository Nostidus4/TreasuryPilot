"""Operational metrics (OBS-004). Definitions: docs/modules/observability/README.md section 3."""

from __future__ import annotations

import math
import statistics
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.execution.models import GasLedger, Operation, OperationStatus, Transaction
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.invoices.models import PaymentRequest, RequestStatusEvent
from treasurypilot_api.recovery.models import ReviewItem
from treasurypilot_api.treasury.models import Treasury

_HUMAN_END = {"Rejected", "Cancelled"}
_BLOCK_REVIEW_TYPES = ("POLICY_BLOCK", "AI_REJECTED")


@dataclass(frozen=True, slots=True)
class Event:
    to: str
    at: datetime
    actor_type: str = "SYSTEM"
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RequestFacts:
    id: uuid.UUID
    due_at: date | None
    amount: int
    events: Sequence[Event]  # ordered by time


@dataclass(frozen=True, slots=True)
class TxFacts:
    kind: str
    submitted_at: datetime
    confirmed_at: datetime | None
    fee_wei: int  # gas ledger fee, 0 when none recorded
    revert_selector: str | None


@dataclass(slots=True)
class MetricInputs:
    start: datetime
    end: datetime
    requests: Sequence[RequestFacts]
    interventions: Counter[uuid.UUID] = field(default_factory=Counter)  # human review actions
    blocks: Sequence[str] = ()  # primary code of each policy BLOCK / AI rejection
    exceptions: int = 0
    unknown_operations: int = 0
    transactions: Sequence[TxFacts] = ()


class Latency(ApiModel):
    median_seconds: float
    p90_seconds: float
    count: int


class Fees(ApiModel):
    total_wei: str
    by_step_type: dict[str, str]


class SeriesPoint(ApiModel):
    date: str
    paid: int
    volume: str
    completed: int  # scheduled-cohort requests that ended Paid, by Paid day
    on_time: int  # paid on or before due date, by Paid day
    interventions: int  # human review actions on requests paid that day
    fees_wei: str  # fees of transactions submitted that day


class OperationsMetrics(ApiModel):
    # Fields the web page already renders.
    payments_count: int
    on_time_rate: float
    median_approval_minutes: float
    ai_plan_rate: float
    exceptions: int
    unknown_operations: int
    series: list[SeriesPoint]
    # OBS-004 definitions.
    completion_rate: float
    interventions_per_request: float
    tx_count: int
    fees: Fees
    latency_by_phase: dict[str, Latency | None]
    rejections_by_reason: dict[str, int]
    reverts_by_selector: dict[str, int]


class OperationsMetricsResponse(ApiModel):
    metrics: OperationsMetrics


def _utc(value: datetime) -> datetime:
    """Naive values are read as UTC so they compare with timestamptz columns."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def _first(events: Sequence[Event], to: str) -> datetime | None:
    return next((e.at for e in events if e.to == to), None)


def _latency(seconds: Iterable[float]) -> Latency | None:
    values = sorted(seconds)
    if not values:
        return None
    p90 = values[max(math.ceil(0.9 * len(values)) - 1, 0)]
    return Latency(median_seconds=statistics.median(values), p90_seconds=p90, count=len(values))


def _gaps(requests: Sequence[RequestFacts], src: str, dst: str) -> list[float]:
    out = []
    for r in requests:
        a, b = _first(r.events, src), _first(r.events, dst)
        if a and b and b >= a:
            out.append((b - a).total_seconds())
    return out


def compute_operations_metrics(data: MetricInputs) -> OperationsMetrics:
    def in_period(at: datetime | None) -> bool:
        return at is not None and data.start <= at.astimezone(UTC) <= data.end

    paid = [r for r in data.requests if in_period(_first(r.events, "Paid"))]
    paid_at = {r.id: cast(datetime, _first(r.events, "Paid")) for r in paid}

    # Completion: Scheduled in period; human rejection/cancellation excluded, policy blocks stay in.
    scheduled = [
        r
        for r in data.requests
        if in_period(_first(r.events, "Scheduled"))
        and not (r.events[-1].to in _HUMAN_END and r.events[-1].actor_type == "USER")
    ]
    completed = sum(1 for r in scheduled if r.events[-1].to == "Paid")

    # shortcut: Paid event time stands in for the PAY block time; use the block time once stored.
    on_time_ids = {
        r.id
        for r in paid
        if r.due_at is not None
        and paid_at[r.id] <= datetime.combine(r.due_at, time(23, 59, 59), tzinfo=UTC)
    }
    on_time = len(on_time_ids)
    completed_ids = {r.id for r in scheduled if r.events[-1].to == "Paid"}

    paid_ids = {r.id for r in paid}
    interventions = sum(n for rid, n in data.interventions.items() if rid in paid_ids)

    rejected = Counter(data.blocks)
    for r in data.requests:
        for e in r.events:
            if e.to == "Rejected" and in_period(e.at):
                rejected[e.reason or "REJECTED"] += 1

    txs = [t for t in data.transactions if in_period(t.submitted_at)]
    by_step: dict[str, int] = defaultdict(int)
    for t in txs:
        by_step[t.kind] += t.fee_wei
    confirmed = [
        (t.confirmed_at - t.submitted_at).total_seconds()
        for t in txs
        if t.confirmed_at and t.confirmed_at >= t.submitted_at
    ]

    days = (data.end.date() - data.start.date()).days + 1
    series = []
    for i in range(days):
        day = data.start.date() + timedelta(days=i)
        todays = [r for r in paid if paid_at[r.id].date() == day]
        today_ids = {r.id for r in todays}
        series.append(
            SeriesPoint(
                date=day.isoformat(),
                paid=len(todays),
                # shortcut: sums raw amounts across assets (USDC-only); group by asset when others land.
                volume=str(sum(r.amount for r in todays)),
                completed=len(today_ids & completed_ids),
                on_time=len(today_ids & on_time_ids),
                interventions=sum(n for rid, n in data.interventions.items() if rid in today_ids),
                fees_wei=str(
                    sum(t.fee_wei for t in txs if t.submitted_at.astimezone(UTC).date() == day)
                ),
            )
        )

    approval = _latency(_gaps(paid, "AwaitingApproval", "Approved"))
    return OperationsMetrics(
        payments_count=len(paid),
        on_time_rate=_ratio(on_time, len(paid)),
        median_approval_minutes=round(approval.median_seconds / 60, 2) if approval else 0.0,
        # No AI-plan provenance is stored yet; reported as 0 rather than guessed.
        ai_plan_rate=0.0,
        exceptions=data.exceptions,
        unknown_operations=data.unknown_operations,
        series=series,
        completion_rate=_ratio(completed, len(scheduled)),
        interventions_per_request=round(interventions / len(paid), 4) if paid else 0.0,
        tx_count=len(txs),
        fees=Fees(
            total_wei=str(sum(by_step.values())),
            by_step_type={k: str(v) for k, v in sorted(by_step.items())},
        ),
        # Phases without stored timestamps (attested, first submit, verified) are null.
        latency_by_phase={
            "approvalToScheduled": _latency(_gaps(data.requests, "Approved", "Scheduled")),
            "scheduledToAttested": None,
            "attestedToFirstSubmit": None,
            "submitToConfirmed": _latency(confirmed),
            "confirmedToVerified": None,
        },
        rejections_by_reason=dict(sorted(rejected.items())),
        reverts_by_selector=dict(Counter(t.revert_selector for t in txs if t.revert_selector)),
    )


async def load_inputs(
    session: AsyncSession,
    org_id: uuid.UUID,
    start: datetime,
    end: datetime,
    treasury_id: uuid.UUID | None,
) -> MetricInputs:
    scope = [PaymentRequest.org_id == org_id]
    if treasury_id is not None:
        scope.append(PaymentRequest.treasury_id == treasury_id)
    # Operations are scoped through their treasury, not their request: a liquidity operation
    # (SUPPLY / WITHDRAW) has no request, and its gas belongs to the same treasury (EXE-014).
    org_treasuries = select(Treasury.id).where(Treasury.org_id == org_id)
    op_scope: list[ColumnElement[bool]] = [Operation.treasury_id.in_(org_treasuries)]
    if treasury_id is not None:
        op_scope.append(Operation.treasury_id == treasury_id)
    touched = (
        select(RequestStatusEvent.request_id)
        .where(RequestStatusEvent.at.between(start, end))
        .distinct()
    )
    rows = (
        await session.execute(
            select(PaymentRequest, RequestStatusEvent)
            .join(RequestStatusEvent, RequestStatusEvent.request_id == PaymentRequest.id)
            .where(*scope, PaymentRequest.id.in_(touched))
            .order_by(RequestStatusEvent.at, RequestStatusEvent.id)
        )
    ).all()
    events: dict[uuid.UUID, list[Event]] = defaultdict(list)
    meta: dict[uuid.UUID, PaymentRequest] = {}
    for req, ev in rows:
        meta[req.id] = req
        events[req.id].append(Event(ev.to_status, ev.at, ev.actor_type, ev.reason))
    requests = [
        RequestFacts(rid, req.due_at, int(req.amount or 0), events[rid])
        for rid, req in meta.items()
    ]

    review_scope = [ReviewItem.org_id == org_id, ReviewItem.created_at.between(start, end)]
    if treasury_id is not None:
        review_scope.append(ReviewItem.treasury_id == treasury_id)
    review = (await session.scalars(select(ReviewItem).where(*review_scope))).all()

    # Resolved review items stand in for human actions (review actions, fee acceptances, grants).
    # Loaded by request, not by creation time: an item created before the period still counts.
    paid_ids = [
        r.id
        for r in requests
        if (p := _first(r.events, "Paid")) is not None and start <= p.astimezone(UTC) <= end
    ]
    acted: Sequence[uuid.UUID | None] = []
    if paid_ids:
        acted = (
            await session.scalars(
                select(ReviewItem.request_id).where(
                    ReviewItem.org_id == org_id,
                    ReviewItem.request_id.in_(paid_ids),
                    ReviewItem.resolved_by.is_not(None),
                )
            )
        ).all()
    interventions = Counter(i for i in acted if i is not None)

    ops = (
        await session.execute(
            select(Operation.kind, Transaction, GasLedger.fee_wei)
            .join(Transaction, Transaction.operation_id == Operation.id)
            .outerjoin(GasLedger, GasLedger.transaction_id == Transaction.id)
            .where(*op_scope, Transaction.submitted_at.between(start, end))
        )
    ).all()
    txs = [
        TxFacts(
            kind=kind.value,
            submitted_at=tx.submitted_at,
            confirmed_at=tx.confirmed_at,
            fee_wei=int(fee or 0),
            revert_selector=tx.revert_selector.hex() if tx.revert_selector else None,
        )
        for kind, tx, fee in ops
    ]
    unknown = await session.scalar(
        select(func.count())
        .select_from(Operation)
        .where(*op_scope, Operation.status == OperationStatus.UNKNOWN)
    )
    return MetricInputs(
        start=start,
        end=end,
        requests=requests,
        interventions=interventions,
        blocks=[i.primary_code for i in review if i.type in _BLOCK_REVIEW_TYPES],
        exceptions=sum(1 for i in review if i.type == "NEEDS_AUTHORITY"),
        unknown_operations=unknown or 0,
        transactions=txs,
    )


router = APIRouter(prefix="/v1", tags=["metrics"])


@router.get(
    "/orgs/{organization_id}/metrics/operations",
    response_model=OperationsMetricsResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def get_operations_metrics(
    organization_id: uuid.UUID,
    request: Request,
    member: Annotated[
        MemberAccess,
        Depends(
            require_role(
                OrganizationRole.OWNER,
                OrganizationRole.FINANCE,
                OrganizationRole.ORG_ADMIN,
                OrganizationRole.AUDITOR,
            )
        ),
    ],
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    treasury_id: Annotated[uuid.UUID | None, Query(alias="treasuryId")] = None,
) -> OperationsMetricsResponse:
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
        data = await load_inputs(session, organization_id, start, end, treasury_id)
    return OperationsMetricsResponse(metrics=compute_operations_metrics(data))
