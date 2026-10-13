"""Deterministic scoring and numeric explanations for proposed payment plans."""

from __future__ import annotations

from collections.abc import Sequence

from treasurypilot_core.domain import (
    ApprovedRequest,
    BindingConstraintDetail,
    ExceptionValue,
    PolicyView,
    Schedule,
    ScheduledItem,
    Snapshot,
)
from treasurypilot_core.engine.liquidity import (
    refill_bound,
    source_capacity,
)
from treasurypilot_core.engine.payment_terms import pay_amount, request_value
from treasurypilot_core.engine.scheduler import (
    HORIZON_DAYS,
    _deadline_feasible,
    _needs_exception,
    _ordered_requests,
    _SimulationState,
    _try_schedule_request,
)
from treasurypilot_core.money import BaseUnits

type Plan = Schedule | Sequence[ScheduledItem]
type PlanScore = tuple[int, int, int, int]

_ZERO = BaseUnits(0)


def _plan_items(plan: Plan) -> tuple[ScheduledItem, ...]:
    return tuple(plan.items if isinstance(plan, Schedule) else plan)


def _validated_items(
    plan: Plan,
    requests: Sequence[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
) -> tuple[int, dict[str, ScheduledItem]]:
    ordered = _ordered_requests(requests, snapshot)
    by_id = {request.id: request for request in ordered}
    state = _SimulationState(dict(snapshot.operational), snapshot.source)
    items = sorted(enumerate(_plan_items(plan)), key=lambda indexed: (indexed[1].day, indexed[0]))
    valid: dict[str, ScheduledItem] = {}
    violations = 0
    current_day: int | None = None
    seen: set[str] = set()

    for _index, item in items:
        request = by_id.get(item.request_id)
        if request is None or item.request_id in seen:
            violations += 1
            continue
        seen.add(item.request_id)
        if item.day < snapshot.day or item.day >= snapshot.day + HORIZON_DAYS:
            violations += 1
            continue
        if current_day != item.day:
            state.start_day(item.day, snapshot)
            current_day = item.day

        accepted_state: _SimulationState | None = None
        for minimal_refill in (False, True):
            trial = state.copy()
            expected, _reason = _try_schedule_request(
                request,
                item.day,
                snapshot,
                policy,
                trial,
                minimal_refill=minimal_refill,
            )
            if expected is not None and expected.refill == item.refill:
                accepted_state = trial
                break
        if accepted_state is None:
            violations += 1
            continue

        state = accepted_state
        valid[item.request_id] = item

    return violations, valid


def score(
    plan: Plan,
    requests: Sequence[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
) -> PlanScore:
    """Return a deterministic lexicographic score for any proposed plan.

    Invalid or duplicate payments add one violation each. Values are recomputed from
    confirmed payment terms; a candidate cannot improve its score by supplying a made-up
    value in ``ScheduledItem``.
    """

    ordered = _ordered_requests(requests, snapshot)
    request_by_id = {request.id: request for request in ordered}
    violations, valid = _validated_items(plan, ordered, snapshot, policy)
    missed_deadlines = sum(
        1
        for request in ordered
        if _deadline_feasible(request, snapshot, policy)
        and (
            request.id not in valid
            or valid[request.id].day > request.terms.net_due_day
        )
    )
    total_value = sum(
        request_value(
            request_by_id[request_id],
            item.day,
            supply_rate_bps=snapshot.supply_rate_bps,
        )
        for request_id, item in valid.items()
    )
    transaction_count = sum(1 + int(item.refill > 0) for item in valid.values())
    return violations, missed_deadlines, -total_value, transaction_count


def compare_plans(
    left: Plan,
    right: Plan,
    requests: Sequence[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
) -> int:
    """Compare two plans using the shared score: -1 left wins, 1 right wins, else 0."""

    left_score = score(left, requests, snapshot, policy)
    right_score = score(right, requests, snapshot, policy)
    return (left_score > right_score) - (left_score < right_score)


def binding_constraints(
    plan: Plan,
    requests: Sequence[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
) -> tuple[BindingConstraintDetail, ...]:
    """Report plan constraints reached or exceeded, with the observed and allowed values."""

    ordered = _ordered_requests(requests, snapshot)
    by_id = {request.id: request for request in ordered}
    state = _SimulationState(dict(snapshot.operational), snapshot.source)
    items = sorted(enumerate(_plan_items(plan)), key=lambda indexed: (indexed[1].day, indexed[0]))
    details: list[BindingConstraintDetail] = []
    valid_ids: set[str] = set()
    current_day: int | None = None
    seen: set[str] = set()

    for _index, item in items:
        request = by_id.get(item.request_id)
        if request is None or item.request_id in seen:
            continue
        seen.add(item.request_id)
        if item.day < snapshot.day or item.day >= snapshot.day + HORIZON_DAYS:
            continue
        if current_day != item.day:
            state.start_day(item.day, snapshot)
            current_day = item.day

        amount = int(pay_amount(request, item.day))
        active_day = snapshot.payee_active_day.get(request.payee)
        if active_day is not None and item.day < active_day:
            details.append(
                BindingConstraintDetail(
                    name="COOLING", request_id=request.id, day=item.day,
                    used=item.day, limit=active_day,
                )
            )
        if item.day > request.terms.net_due_day:
            details.append(
                BindingConstraintDetail(
                    name="DEADLINE", request_id=request.id, day=item.day,
                    used=item.day, limit=request.terms.net_due_day,
                )
            )

        pay_used = state.pay_used + amount
        if pay_used >= int(policy.pay.daily):
            details.append(
                BindingConstraintDetail(
                    name="PAY_DAILY_CAP", request_id=request.id, day=item.day,
                    used=pay_used, limit=int(policy.pay.daily),
                )
            )

        wallet = state.operational[request.paying_wallet]
        bound = int(refill_bound(wallet, BaseUnits(amount)))
        refill = int(item.refill)
        if refill > 0 and refill >= bound:
            details.append(
                BindingConstraintDetail(
                    name="REFILL_BOUND", request_id=request.id, day=item.day,
                    used=refill, limit=bound,
                )
            )
        source_available = int(source_capacity(state.source, _ZERO))
        if refill > 0 and refill >= source_available:
            details.append(
                BindingConstraintDetail(
                    name="SOURCE_CAPACITY", request_id=request.id, day=item.day,
                    used=refill, limit=source_available,
                )
            )
        refill_used = state.refill_used + refill
        if refill > 0 and refill_used >= int(policy.refill.daily):
            details.append(
                BindingConstraintDetail(
                    name="REFILL_DAILY_CAP", request_id=request.id, day=item.day,
                    used=refill_used, limit=int(policy.refill.daily),
                )
            )
        balance_after = int(wallet.balance) + refill - amount
        if balance_after <= int(wallet.buffer):
            details.append(
                BindingConstraintDetail(
                    name="BUFFER", request_id=request.id, day=item.day,
                    used=balance_after, limit=int(wallet.buffer),
                )
            )

        accepted_state: _SimulationState | None = None
        for minimal_refill in (False, True):
            trial = state.copy()
            expected, _reason = _try_schedule_request(
                request,
                item.day,
                snapshot,
                policy,
                trial,
                minimal_refill=minimal_refill,
            )
            if expected is not None and expected.refill == item.refill:
                accepted_state = trial
                break
        if accepted_state is not None:
            state = accepted_state
            valid_ids.add(item.request_id)

    # Keep repeated explanations deterministic while retaining separate requests that bind
    # the same daily constraint.
    return tuple(details)


def exception_values(
    requests: Sequence[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
) -> tuple[ExceptionValue, ...]:
    """Return potential value for requests blocked by the per-request cap.

    The valuation uses the first day on which the payee is active and the request can be
    planned, matching the scheduler's M07-D9 report.
    """

    ordered = _ordered_requests(requests, snapshot)
    values: list[ExceptionValue] = []
    for request in ordered:
        active_day = snapshot.payee_active_day.get(request.payee)
        if active_day is None or request.exception_granted:
            continue
        first_day = max(snapshot.day, active_day)
        if not _needs_exception(request, first_day, policy):
            continue
        granted = request.model_copy(update={"exception_granted": True})
        values.append(
            ExceptionValue(
                request_id=request.id,
                value=request_value(
                    granted,
                    first_day,
                    supply_rate_bps=snapshot.supply_rate_bps,
                ),
            )
        )
    return tuple(values)
