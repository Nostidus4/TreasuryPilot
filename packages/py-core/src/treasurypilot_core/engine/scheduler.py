"""Deterministic baseline scheduler using earliest-due-first ordering."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from treasurypilot_core.domain import (
    ApprovedRequest,
    Infeasible,
    PolicyView,
    Schedule,
    ScheduledItem,
    Snapshot,
    WalletState,
)
from treasurypilot_core.engine.liquidity import decide_refill
from treasurypilot_core.engine.payment_terms import pay_amount, request_value
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy.reason_codes import PolicyReasonCode

_ZERO = BaseUnits(0)
# M07-D3: the rolling horizon always spans 30 UTC days, so a request that cannot be paid
# by its due day (cooling, caps, source) is still scheduled late rather than dropped.
HORIZON_DAYS = 30
# M07-D9: reported by the scheduler for requests above the per-request cap.
NEEDS_EXCEPTION = "NEEDS_EXCEPTION"
ORACLE_NOT_SELECTED = "ORACLE_NOT_SELECTED"
ORACLE_MAX_REQUESTS = 8
ORACLE_MAX_HORIZON_DAYS = 5

# Which constraint to show in the "Why" panel for each blocking reason.
_BINDING = {
    NEEDS_EXCEPTION: "PAY_PER_REQUEST_CAP",
    PolicyReasonCode.PAYEE_UNKNOWN: "PAYEE_UNKNOWN",
    PolicyReasonCode.PAYEE_COOLING: "PAYEE_COOLING",
    PolicyReasonCode.OVER_DAILY_LIMIT: "PAY_DAILY_CAP",
    PolicyReasonCode.OVER_REFILL_DAILY: "REFILL_DAILY_CAP",
    PolicyReasonCode.OVER_REFILL_PER_REQUEST: "REFILL_PER_REQUEST_CAP",
    PolicyReasonCode.REFILL_BOUND: "REFILL_BOUND",
    PolicyReasonCode.SOURCE_INSUFFICIENT: "SOURCE_CAPACITY",
    PolicyReasonCode.WRONG_REFILL_TARGET: "WRONG_REFILL_TARGET",
}


@dataclass(slots=True)
class _SimulationState:
    """Mutable balances and daily counters used by both schedule solvers."""

    operational: dict[str, WalletState]
    source: WalletState
    pay_used: int = 0
    refill_used: int = 0

    def copy(self) -> _SimulationState:
        return _SimulationState(
            dict(self.operational), self.source, self.pay_used, self.refill_used
        )

    def start_day(self, day: int, snapshot: Snapshot) -> None:
        self.pay_used = int(snapshot.used_today["pay"]) if day == snapshot.day else 0
        self.refill_used = int(snapshot.used_today["refill"]) if day == snapshot.day else 0


def _ordered_requests(
    requests: Sequence[ApprovedRequest], snapshot: Snapshot
) -> list[ApprovedRequest]:
    ordered = sorted(
        requests,
        key=lambda request: (request.terms.net_due_day, request.approved_seq, request.id),
    )
    if len({request.id for request in ordered}) != len(ordered):
        raise ValueError("request ids must be unique")
    for request in ordered:
        if request.paying_wallet not in snapshot.operational:
            raise ValueError(f"no operational wallet for request {request.id!r}")
    return ordered


def _try_schedule_request(
    request: ApprovedRequest,
    day: int,
    snapshot: Snapshot,
    policy: PolicyView,
    state: _SimulationState,
) -> tuple[ScheduledItem | None, str | None]:
    """Check one payment with the exact rules and state transitions used by EDF."""

    active_day = snapshot.payee_active_day.get(request.payee)
    if active_day is None:
        return None, PolicyReasonCode.PAYEE_UNKNOWN
    if _needs_exception(request, day, policy):
        return None, NEEDS_EXCEPTION
    if day < active_day:
        return None, PolicyReasonCode.PAYEE_COOLING

    amount = pay_amount(request, day)
    if state.pay_used + int(amount) > int(policy.pay.daily):
        return None, PolicyReasonCode.OVER_DAILY_LIMIT

    wallet = state.operational[request.paying_wallet]
    refill_request = request.model_copy(
        update={"amount": amount, "early_amount": None, "early_pay_by": None}
    )
    refill = decide_refill(
        refill_request,
        wallet,
        state.source,
        policy,
        BaseUnits(state.refill_used),
        _ZERO,
        source_protected=_ZERO,
    )
    if refill.kind == "stop":
        return None, refill.reason

    refill_amount = int(refill.amount)
    wallet_balance = int(wallet.balance) + refill_amount - int(amount)
    # decide_refill guarantees the buffer when it does not stop.
    assert wallet_balance >= int(wallet.buffer)
    state.operational[request.paying_wallet] = wallet.model_copy(
        update={"balance": BaseUnits(wallet_balance)}
    )
    if refill_amount:
        state.source = state.source.model_copy(
            update={"balance": BaseUnits(int(state.source.balance) - refill_amount)}
        )
    state.pay_used += int(amount)
    state.refill_used += refill_amount
    return (
        ScheduledItem(
            request_id=request.id,
            day=day,
            refill=BaseUnits(refill_amount),
            value=request_value(request, day, supply_rate_bps=snapshot.supply_rate_bps),
        ),
        None,
    )


def _schedule_objective(
    ordered: Sequence[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
    items: Sequence[ScheduledItem],
) -> tuple[int, int, int, int]:
    """Shared BR-052 score for EDF and the exhaustive oracle."""

    scheduled_by_id = {item.request_id: item for item in items}
    missed_deadlines = sum(
        1
        for request in ordered
        if _deadline_feasible(request, snapshot, policy)
        and (
            request.id not in scheduled_by_id
            or scheduled_by_id[request.id].day > request.terms.net_due_day
        )
    )
    total_value = sum(item.value for item in items)
    transaction_count = sum(1 + int(item.refill > 0) for item in items)
    return (0, missed_deadlines, -total_value, transaction_count)


def _needs_exception(request: ApprovedRequest, day: int, policy: PolicyView) -> bool:
    # Checked against the amount actually paid that day: an early amount can fit
    # under the cap while the standard amount does not.
    return pay_amount(request, day) > policy.pay.per_request and not request.exception_granted


def _deadline_feasible(request: ApprovedRequest, snapshot: Snapshot, policy: PolicyView) -> bool:
    """Whether any solver could have paid ``request`` by its due day (objective term 2)."""

    due = request.terms.net_due_day
    active_day = snapshot.payee_active_day.get(request.payee)
    return (
        active_day is not None
        and due >= max(snapshot.day, active_day)
        and not _needs_exception(request, due, policy)
    )


def schedule_edf(
    requests: Sequence[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
) -> Schedule:
    """Build the rolling-horizon B1 schedule in due-day and approval order (section 8.3).

    Requests that do not fit today remain eligible on following days. The
    scheduler carries wallet balances, source drawdown, and daily usage forward
    so a later payment cannot spend the same funds twice. Ties on
    ``(net_due_day, approved_seq)`` are broken by request id, so identical inputs
    always give the same schedule (M07-D7).
    """

    ordered = _ordered_requests(requests, snapshot)
    if not ordered:
        return Schedule(
            items=(),
            infeasible=(),
            objective=(0, 0, 0, 0),
            binding=(),
            solver="EDF",
            status="OPTIMAL",
        )
    horizon_end = snapshot.day + HORIZON_DAYS - 1
    state = _SimulationState(dict(snapshot.operational), snapshot.source)
    scheduled: list[ScheduledItem] = []
    blocked_reason: dict[str, str] = {}
    binding: set[str] = set()

    def block(request: ApprovedRequest, reason: str, *, overrides: bool = False) -> None:
        # The first blocker is reported, except for permanent ones that explain the outcome.
        if overrides:
            blocked_reason[request.id] = reason
        else:
            blocked_reason.setdefault(request.id, reason)
        binding.add(_BINDING[reason])

    remaining: list[ApprovedRequest] = []
    for request in ordered:
        # A payee missing from the snapshot was never read: never assume it is active.
        if request.payee not in snapshot.payee_active_day:
            block(request, PolicyReasonCode.PAYEE_UNKNOWN, overrides=True)
        else:
            remaining.append(request)

    for day in range(snapshot.day, horizon_end + 1):
        state.start_day(day, snapshot)
        next_remaining: list[ApprovedRequest] = []

        for request in remaining:
            item, reason = _try_schedule_request(request, day, snapshot, policy, state)
            if item is not None:
                scheduled.append(item)
                continue

            assert reason is not None
            if reason in (NEEDS_EXCEPTION, PolicyReasonCode.PAYEE_UNKNOWN):
                # These permanent blockers cannot improve on a later day.
                block(request, reason, overrides=True)
                continue
            block(request, reason)
            next_remaining.append(request)

        remaining = next_remaining
        if not remaining:
            break

    scheduled_by_id = {item.request_id: item for item in scheduled}
    infeasible: list[Infeasible] = []
    for request in ordered:
        if request.id in scheduled_by_id:
            continue
        reason = blocked_reason[request.id]
        if reason == NEEDS_EXCEPTION:
            first_day = max(snapshot.day, snapshot.payee_active_day.get(request.payee, 0))
            potential_value = request_value(
                request, first_day, supply_rate_bps=snapshot.supply_rate_bps
            )
            detail = (
                "Approved request exceeds the per-request pay cap; Owner exception required. "
                f"Potential value if granted: {potential_value}."
            )
        else:
            detail = (
                f"No feasible payment day in the {HORIZON_DAYS}-day horizon; "
                f"first blocker: {reason}."
            )
        infeasible.append(Infeasible(request_id=request.id, reason=reason, detail=detail))

    return Schedule(
        items=tuple(scheduled),
        infeasible=tuple(infeasible),
        objective=_schedule_objective(ordered, snapshot, policy, scheduled),
        binding=tuple(sorted(binding)),
        solver="EDF",
        status="FEASIBLE",
    )


def schedule_oracle(
    requests: Sequence[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
) -> Schedule:
    """Return the exhaustive BR-052 optimum for a small test/benchmark instance.

    The search tries every assignment of each request to a day in the instance
    horizon or to the unscheduled set. The horizon ends on the latest due day,
    and is capped at five days. Same-day payments use the same EDF ordering and
    shared feasibility transition, so the oracle cannot accept a plan EDF rejects.
    """

    ordered = _ordered_requests(requests, snapshot)
    if len(ordered) > ORACLE_MAX_REQUESTS:
        raise ValueError(f"oracle supports at most {ORACLE_MAX_REQUESTS} requests")
    if not ordered:
        return Schedule(
            items=(),
            infeasible=(),
            objective=(0, 0, 0, 0),
            binding=(),
            solver="ORACLE",
            status="OPTIMAL",
        )

    horizon_days = max(
        1,
        max(request.terms.net_due_day - snapshot.day + 1 for request in ordered),
    )
    if horizon_days > ORACLE_MAX_HORIZON_DAYS:
        raise ValueError(f"oracle supports a horizon of at most {ORACLE_MAX_HORIZON_DAYS} days")

    remaining = tuple(request for request in ordered if request.payee in snapshot.payee_active_day)
    base_state = _SimulationState(dict(snapshot.operational), snapshot.source)
    priority_order = sorted(ordered, key=lambda request: (request.approved_seq, request.id))
    best_objective: tuple[int, int, int, int] | None = None
    best_tie_break: tuple[int, ...] | None = None
    best_items: tuple[ScheduledItem, ...] = ()

    def consider(items: tuple[ScheduledItem, ...]) -> None:
        nonlocal best_objective, best_tie_break, best_items
        objective = _schedule_objective(ordered, snapshot, policy, items)
        days_by_id = {item.request_id: item.day for item in items}
        # Lower day wins; a scheduled request wins a score tie against an omitted one.
        tie_break = tuple(
            days_by_id.get(request.id, snapshot.day + horizon_days) for request in priority_order
        )
        if best_objective is None or (objective, tie_break) < (best_objective, best_tie_break):
            best_objective = objective
            best_tie_break = tie_break
            best_items = items

    def search_day(
        day_offset: int,
        day_remaining: tuple[ApprovedRequest, ...],
        state: _SimulationState,
        items: tuple[ScheduledItem, ...],
    ) -> None:
        if day_offset == horizon_days:
            consider(items)
            return

        day = snapshot.day + day_offset
        for mask in range(1 << len(day_remaining)):
            branch_state = state.copy()
            branch_state.start_day(day, snapshot)
            scheduled_today: list[ScheduledItem] = []
            next_remaining: list[ApprovedRequest] = []
            feasible = True
            for index, request in enumerate(day_remaining):
                if mask & (1 << index):
                    item, _reason = _try_schedule_request(
                        request, day, snapshot, policy, branch_state
                    )
                    if item is None:
                        feasible = False
                        break
                    scheduled_today.append(item)
                else:
                    next_remaining.append(request)
            if feasible:
                search_day(
                    day_offset + 1,
                    tuple(next_remaining),
                    branch_state,
                    items + tuple(scheduled_today),
                )

    search_day(0, remaining, base_state, ())
    assert best_objective is not None

    scheduled_ids = {item.request_id for item in best_items}
    edf = schedule_edf(ordered, snapshot, policy)
    edf_infeasible = {item.request_id: item for item in edf.infeasible}
    infeasible: list[Infeasible] = []
    binding: set[str] = set()
    for request in ordered:
        if request.id in scheduled_ids:
            continue
        known_block = edf_infeasible.get(request.id)
        if known_block is None:
            infeasible.append(
                Infeasible(
                    request_id=request.id,
                    reason=ORACLE_NOT_SELECTED,
                    detail="Omitted because it does not improve the oracle's lexicographic objective.",
                )
            )
            continue
        infeasible.append(known_block)
        if known_block.reason in _BINDING:
            binding.add(_BINDING[known_block.reason])

    return Schedule(
        items=best_items,
        infeasible=tuple(infeasible),
        objective=best_objective,
        binding=tuple(sorted(binding)),
        solver="ORACLE",
        status="OPTIMAL",
    )
