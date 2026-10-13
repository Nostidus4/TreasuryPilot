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
from treasurypilot_core.engine.liquidity import decide_refill, shortage
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
    *,
    minimal_refill: bool = False,
) -> tuple[ScheduledItem | None, str | None]:
    """Check one payment with the exact rules and state transitions used by EDF.

    ``minimal_refill`` swaps a ``preferred`` refill (top up to the wallet target) for the
    ``shortage`` refill (just enough to pay), the other BR-032 outcome. EDF never sets it.
    Mutates ``state`` only when the payment is accepted. A payee missing from the snapshot
    is rejected here (``PAYEE_UNKNOWN``), so callers need not pre-filter.
    """

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
    if minimal_refill and refill.kind == "preferred":
        refill_amount = int(shortage(wallet, refill_request.amount, _ZERO))
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

    # A payee missing from the snapshot was never read: the helper rejects it as
    # PAYEE_UNKNOWN (permanent) rather than assuming it is active.
    remaining = list(ordered)

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


def _oracle_horizon_days(ordered: Sequence[ApprovedRequest], snapshot: Snapshot) -> int:
    """Days the oracle searches: through the latest due day or payee activation day."""

    last_day = snapshot.day
    for request in ordered:
        last_day = max(last_day, request.terms.net_due_day)
        active_day = snapshot.payee_active_day.get(request.payee)
        if active_day is not None:
            last_day = max(last_day, active_day)
    return last_day - snapshot.day + 1


type _OracleKey = tuple[int, int, tuple[int, ...], int, int, int]
type _OracleCost = tuple[int, int, int, int]
# A choice is (request index, minimal refill) to pay, or None to end the day.
type _OracleChoice = tuple[int, bool] | None


def schedule_oracle(
    requests: Sequence[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
) -> Schedule:
    """Return the BR-052 optimum of a small instance by exhaustive memoized search.

    The search covers every choice of payment day (or omission), every same-day payment
    order, and for each payment both BR-032 refill outcomes (``preferred`` top-up to
    target, or only the ``shortage``). Arbitrary refill amounts between those two, such as
    pre-funding a later request, are not searched, so a model that chooses refill amounts
    freely can in principle beat it; ``oracle_objective <= edf_objective`` always holds.

    The horizon runs through the latest due day or payee activation day (at most five
    days). A payment after that cannot improve the objective: it adds a transaction and
    cannot add discount value. Payment rules and state transitions are the helper shared
    with EDF. The search is a DP over ``(day, unpaid set, balances, daily usage)`` with
    additive costs, so shared prefixes are solved once.
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

    horizon_days = _oracle_horizon_days(ordered, snapshot)
    if horizon_days > ORACLE_MAX_HORIZON_DAYS:
        raise ValueError(f"oracle supports a horizon of at most {ORACLE_MAX_HORIZON_DAYS} days")

    count = len(ordered)
    deadline_feasible = [_deadline_feasible(request, snapshot, policy) for request in ordered]
    # Tie-break (lower day first, scheduled before omitted, by approval order) as an
    # additive base-(horizon+1) number so the whole objective stays additive.
    base = horizon_days + 1
    rank = {
        request.id: position
        for position, request in enumerate(
            sorted(ordered, key=lambda request: (request.approved_seq, request.id))
        )
    }
    weight = [base ** (count - 1 - rank[request.id]) for request in ordered]
    omitted_cost = [
        (int(deadline_feasible[index]), 0, 0, weight[index] * horizon_days)
        for index in range(count)
    ]
    wallet_names = sorted(snapshot.operational)

    def omitted_total(mask: int) -> _OracleCost:
        total = (0, 0, 0, 0)
        for index in range(count):
            if mask & (1 << index):
                total = _add(total, omitted_cost[index])
        return total

    def pay_options(
        index: int, day_offset: int, state: _SimulationState
    ) -> list[tuple[bool, ScheduledItem, _SimulationState]]:
        day = snapshot.day + day_offset
        options: list[tuple[bool, ScheduledItem, _SimulationState]] = []
        for minimal in (False, True):
            trial = state.copy()
            item, _reason = _try_schedule_request(
                ordered[index], day, snapshot, policy, trial, minimal_refill=minimal
            )
            if item is None:
                break
            if minimal and item.refill == options[0][1].refill:
                break
            options.append((minimal, item, trial))
        return options

    def item_cost(index: int, item: ScheduledItem, day_offset: int) -> _OracleCost:
        request = ordered[index]
        missed = int(deadline_feasible[index] and item.day > request.terms.net_due_day)
        return (
            missed,
            -item.value,
            1 + int(item.refill > 0),
            weight[index] * day_offset,
        )

    def next_day(state: _SimulationState, day_offset: int) -> _SimulationState:
        following = state.copy()
        following.start_day(snapshot.day + day_offset + 1, snapshot)
        return following

    max_amount = [max(request.amount, request.early_amount or _ZERO) for request in ordered]
    refill_ceiling = [
        int(request.amount) + int(snapshot.operational[request.paying_wallet].target)
        for request in ordered
    ]
    limits_cache: dict[int, tuple[tuple[int, ...], int, int, int]] = {}

    def mask_limits(mask: int) -> tuple[tuple[int, ...], int, int, int]:
        """Per-wallet balance, source, pay and refill amounts beyond which more is irrelevant."""

        cached = limits_cache.get(mask)
        if cached is None:
            members = [index for index in range(count) if mask & (1 << index)]
            wallets = tuple(
                sum(int(max_amount[i]) for i in members if ordered[i].paying_wallet == name)
                + int(snapshot.operational[name].target)
                + int(snapshot.operational[name].buffer)
                if any(ordered[i].paying_wallet == name for i in members)
                else 0
                for name in wallet_names
            )
            cached = (
                wallets,
                int(snapshot.source.buffer) + sum(refill_ceiling[i] for i in members),
                sum(int(max_amount[i]) for i in members),
                sum(refill_ceiling[i] for i in members),
            )
            limits_cache[mask] = cached
        return cached

    def state_key(day_offset: int, mask: int, state: _SimulationState) -> _OracleKey:
        """Canonical state: values that can no longer change any decision collapse together."""

        wallet_caps, source_cap, pay_need, refill_need = mask_limits(mask)
        pay_daily = int(policy.pay.daily)
        refill_daily = int(policy.refill.daily)
        return (
            day_offset,
            mask,
            tuple(
                min(int(state.operational[name].balance), cap)
                for name, cap in zip(wallet_names, wallet_caps, strict=True)
            ),
            min(int(state.source.balance), source_cap),
            0 if state.pay_used + pay_need <= pay_daily else min(state.pay_used, pay_daily),
            0
            if state.refill_used + refill_need <= refill_daily
            else min(state.refill_used, refill_daily),
        )

    memo: dict[_OracleKey, tuple[_OracleCost, _OracleChoice]] = {}

    def solve(day_offset: int, mask: int, state: _SimulationState) -> _OracleCost:
        if mask == 0:
            return (0, 0, 0, 0)
        if day_offset == horizon_days:
            return omitted_total(mask)
        key = state_key(day_offset, mask, state)
        cached = memo.get(key)
        if cached is not None:
            return cached[0]

        best: tuple[_OracleCost, _OracleChoice] | None = None
        for index in range(count):
            if not mask & (1 << index):
                continue
            for minimal, item, after in pay_options(index, day_offset, state):
                cost = _add(
                    item_cost(index, item, day_offset),
                    solve(day_offset, mask & ~(1 << index), after),
                )
                if best is None or cost < best[0]:
                    best = (cost, (index, minimal))
        end_day = solve(day_offset + 1, mask, next_day(state, day_offset))
        if best is None or end_day < best[0]:
            best = (end_day, None)
        memo[key] = best
        return best[0]

    root = _SimulationState(dict(snapshot.operational), snapshot.source)
    root.start_day(snapshot.day, snapshot)
    full_mask = (1 << count) - 1
    solve(0, full_mask, root)

    # Replay the optimal choices, recording which constraint blocked each request that
    # was still unpaid when a day ended (the oracle's own binding constraints).
    items: list[ScheduledItem] = []
    binding: set[str] = set()
    state, mask, day_offset = root, full_mask, 0
    while mask and day_offset < horizon_days:
        choice = memo[state_key(day_offset, mask, state)][1]
        if choice is not None:
            index, minimal = choice
            item, _reason = _try_schedule_request(
                ordered[index],
                snapshot.day + day_offset,
                snapshot,
                policy,
                state,
                minimal_refill=minimal,
            )
            assert item is not None
            items.append(item)
            mask &= ~(1 << index)
            continue
        for index in range(count):
            if mask & (1 << index):
                _item, reason = _try_schedule_request(
                    ordered[index], snapshot.day + day_offset, snapshot, policy, state.copy()
                )
                if reason is not None:
                    binding.add(_BINDING[reason])
        state = next_day(state, day_offset)
        day_offset += 1

    scheduled_ids = {item.request_id for item in items}
    infeasible: list[Infeasible] = []
    for request in ordered:
        if request.id in scheduled_ids:
            continue
        active_day = snapshot.payee_active_day.get(request.payee)
        if active_day is None:
            reason = PolicyReasonCode.PAYEE_UNKNOWN
            detail = "Payee is not in the snapshot, so its activation day was never read."
        elif all(
            _needs_exception(request, day, policy)
            for day in range(max(snapshot.day, active_day), snapshot.day + horizon_days)
        ):
            reason = NEEDS_EXCEPTION
            detail = "Approved request exceeds the per-request pay cap; Owner exception required."
        else:
            reason = ORACLE_NOT_SELECTED
            detail = (
                f"No schedule within the oracle's {horizon_days}-day search horizon that pays "
                "this request is both feasible and better under the lexicographic objective."
            )
        if reason in _BINDING:
            binding.add(_BINDING[reason])
        infeasible.append(Infeasible(request_id=request.id, reason=reason, detail=detail))

    return Schedule(
        items=tuple(items),
        infeasible=tuple(infeasible),
        objective=_schedule_objective(ordered, snapshot, policy, items),
        binding=tuple(sorted(binding)),
        solver="ORACLE",
        status="OPTIMAL",
    )


def _add(left: _OracleCost, right: _OracleCost) -> _OracleCost:
    return (left[0] + right[0], left[1] + right[1], left[2] + right[2], left[3] + right[3])
