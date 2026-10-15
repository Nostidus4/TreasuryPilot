"""Terms-aware scheduler B2: an OR-Tools CP-SAT model of the BR-052 objective (ADR-015).

The model searches exactly the space the exhaustive oracle searches, so the two return
the same objective on every instance the oracle can solve:

* every request is paid on at most one day of the horizon, or omitted;
* payments are totally ordered into *slots*, days never decrease along the slots, and
  the order inside a day is free (it changes wallet balances and the daily counters);
* a payment's refill is the BR-032 outcome: nothing when no shortage exists, otherwise
  the shortage, or the bounded top-up to target when the refill caps allow it.

Payment rules (cooling, per-request cap, daily pay cap, refill bound, daily refill cap,
source capacity, wallet buffer) are the integer constraints of financial-engine section 8.4.
The objective is solved lexicographically in stages: deadlines missed, value, transaction
count, approval-order tie-break. Each stage fixes the optimum of the previous one.

Determinism (M07-D7): inputs are sorted, one search worker, fixed seed. Identical inputs
give identical outputs unless a stage hits the wall-clock limit, in which case the answer
depends on machine speed (it is then ``FEASIBLE`` or ``FALLBACK``, never ``OPTIMAL``).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from ortools.sat.python import cp_model

from treasurypilot_core.domain import (
    ApprovedRequest,
    Infeasible,
    PolicyView,
    Schedule,
    ScheduledItem,
    Snapshot,
)
from treasurypilot_core.engine.payment_terms import pay_amount, request_value
from treasurypilot_core.engine.scheduler import (
    _BINDING,
    HORIZON_DAYS,
    NEEDS_EXCEPTION,
    _deadline_feasible,
    _needs_exception,
    _oracle_horizon_days,
    _ordered_requests,
    _schedule_objective,
    _SimulationState,
    _try_schedule_request,
    schedule_edf,
)
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy.reason_codes import PolicyReasonCode

CPSAT_NOT_SELECTED = "CPSAT_NOT_SELECTED"
DEFAULT_TIME_LIMIT_SECONDS = 5.0
CPSAT_NUM_WORKERS = 1
CPSAT_RANDOM_SEED = 42
# CP-SAT works on signed 64-bit integers; stay well below 2**63 so sums cannot wrap.
_INT_LIMIT = 2**62

_NO_FEE = BaseUnits(0)
_log = structlog.get_logger(__name__)


class _CpSatUnavailable(Exception):
    """The CP-SAT result cannot be used; the caller returns the EDF schedule instead."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    """A payable (request, day offset) pair with its debit and value."""

    day: int
    amount: int
    value: int


def _fallback(edf: Schedule, reason: str, *, unexpected: bool = False) -> Schedule:
    # An unexpected error is a bug, not an expected limit: log it loudly so the EDF
    # fallback cannot mask a model regression.
    (_log.error if unexpected else _log.warning)("cpsat_fallback", reason=reason)
    return edf.model_copy(update={"status": "FALLBACK"})


def _static_wallet_ok(request: ApprovedRequest, snapshot: Snapshot) -> bool:
    wallet = snapshot.operational[request.paying_wallet]
    # decide_refill stops with WRONG_REFILL_TARGET before looking at any amount.
    return wallet.address == request.paying_wallet and snapshot.source.address != wallet.address


def _candidates(
    request: ApprovedRequest,
    snapshot: Snapshot,
    policy: PolicyView,
    horizon: int,
    fee_in_asset: BaseUnits,
    fee_hold_today: bool,
) -> list[_Candidate]:
    active_day = snapshot.payee_active_day.get(request.payee)
    if active_day is None or not _static_wallet_ok(request, snapshot):
        return []
    result: list[_Candidate] = []
    for offset in range(horizon):
        day = snapshot.day + offset
        if day < active_day or _needs_exception(request, day, policy):
            continue
        if fee_hold_today and offset == 0:
            continue  # the fee policy holds today; later days stay open
        result.append(
            _Candidate(
                day=offset,
                amount=int(pay_amount(request, day)),
                value=request_value(
                    request,
                    day,
                    fee_in_asset=fee_in_asset,
                    supply_rate_bps=snapshot.supply_rate_bps,
                ),
            )
        )
    return result


def _tie_break_weights(ordered: Sequence[ApprovedRequest], horizon: int) -> list[int]:
    """Weights making earlier ``approved_seq`` strictly dominate later ones when they fit.

    Exact lexicographic weights are powers of ``horizon + 1``; for very large batches
    they would overflow 64 bits, and the weights degrade to a linear rank (still
    deterministic, no longer strictly lexicographic).
    """

    count = len(ordered)
    rank = {
        request.id: position
        for position, request in enumerate(
            sorted(ordered, key=lambda request: (request.approved_seq, request.id))
        )
    }
    base = horizon + 1
    if base**count * horizon < _INT_LIMIT // 64:
        return [base ** (count - 1 - rank[request.id]) for request in ordered]
    return [count - rank[request.id] for request in ordered]


def _bounds_guard(
    ordered: Sequence[ApprovedRequest],
    candidates: Sequence[Sequence[_Candidate]],
    weights: Sequence[int],
    snapshot: Snapshot,
    policy: PolicyView,
    horizon: int,
) -> None:
    """Reject inputs whose magnitudes could overflow the solver's 64-bit arithmetic."""

    total = (
        int(snapshot.source.balance)
        + int(snapshot.source.buffer)
        + int(snapshot.used_today["pay"])
        + int(snapshot.used_today["refill"])
        + int(policy.pay.daily)
        + int(policy.refill.daily)
        + int(policy.refill.per_request)
        + int(policy.pay.per_request)
    )
    for wallet in snapshot.operational.values():
        total += int(wallet.balance) + int(wallet.buffer) + int(wallet.target)
    for request, options in zip(ordered, candidates, strict=True):
        total += int(request.amount) + int(request.early_amount or 0)
        total += sum(abs(option.value) + option.amount for option in options)
    total += sum(weights) * (horizon + 1)
    if total * (2 * len(ordered) + horizon + 8) >= _INT_LIMIT:
        raise _CpSatUnavailable("input magnitudes exceed the CP-SAT 64-bit bound")


def schedule_cpsat(
    requests: Sequence[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
    *,
    time_limit_seconds: float = DEFAULT_TIME_LIMIT_SECONDS,
    fee_in_asset: BaseUnits = _NO_FEE,
    fee_hold_today: bool = False,
) -> Schedule:
    """Return the BR-052 optimum found by CP-SAT, or the EDF schedule as ``FALLBACK``.

    ``time_limit_seconds`` is the wall-clock budget for the whole call (model build and
    all four stages; each stage receives an equal share of what remains). On a model
    error, an exceeded bound, a missing solution, a plan that does not replay under the
    shared payment rules, or a result worse than EDF, the EDF schedule is returned with
    ``status="FALLBACK"``. ``status="FEASIBLE"`` means every stage returned a solution
    but at least one was not proven optimal before its time share ran out.

    ``fee_in_asset`` is the estimated plan fee in asset units: an early payment is only
    worth its saving minus that fee and the supply interest forgone. ``fee_hold_today``
    marks today infeasible (treasury fee hold); later days are unaffected.
    """

    started = time.monotonic()
    ordered = _ordered_requests(requests, snapshot)
    if not ordered:
        return Schedule(
            items=(),
            infeasible=(),
            objective=(0, 0, 0, 0),
            binding=(),
            solver="CPSAT",
            status="OPTIMAL",
        )
    edf = schedule_edf(ordered, snapshot, policy)
    if snapshot.refill_paths:
        # shortcut: the CP-SAT model has one (Safe T) source; extend it when paths are in use.
        return _fallback(edf, "operational refill paths are only planned by EDF")
    try:
        return _solve(
            ordered,
            snapshot,
            policy,
            edf,
            started=started,
            time_limit_seconds=time_limit_seconds,
            fee_in_asset=fee_in_asset,
            fee_hold_today=fee_hold_today,
        )
    except _CpSatUnavailable as error:
        return _fallback(edf, str(error))
    except Exception as error:  # solver crashes must never take the planner down
        return _fallback(edf, f"solver error: {type(error).__name__}: {error}", unexpected=True)


def _solve(
    ordered: Sequence[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
    edf: Schedule,
    *,
    started: float,
    time_limit_seconds: float,
    fee_in_asset: BaseUnits,
    fee_hold_today: bool,
) -> Schedule:
    horizon = min(HORIZON_DAYS, _oracle_horizon_days(ordered, snapshot))
    candidates = [
        _candidates(request, snapshot, policy, horizon, fee_in_asset, fee_hold_today)
        for request in ordered
    ]
    weights = _tie_break_weights(ordered, horizon)
    _bounds_guard(ordered, candidates, weights, snapshot, policy, horizon)
    deadline_feasible = [_deadline_feasible(request, snapshot, policy) for request in ordered]

    # Only requests with at least one payable day take part in the model.
    members = [index for index, options in enumerate(candidates) if options]
    chosen: list[tuple[int, int, int, int]] = []  # (request index, day, refill, value)
    status: str = "OPTIMAL"
    if members:
        chosen, status = _optimise(
            ordered,
            candidates,
            weights,
            deadline_feasible,
            members,
            snapshot,
            policy,
            horizon,
            started=started,
            time_limit_seconds=time_limit_seconds,
        )

    result = _build_schedule(ordered, chosen, status, snapshot, policy, horizon)
    # A fee changes the values the model maximises but not the missed-deadline term, so
    # only that term is comparable then; a fee hold removes days EDF may still use.
    if not fee_hold_today:
        terms = 4 if int(fee_in_asset) == 0 else 2
        if result.objective[:terms] > edf.objective[:terms]:
            raise _CpSatUnavailable("CP-SAT result is worse than the EDF schedule")
    return result


def _optimise(
    ordered: Sequence[ApprovedRequest],
    candidates: Sequence[Sequence[_Candidate]],
    weights: Sequence[int],
    deadline_feasible: Sequence[bool],
    members: Sequence[int],
    snapshot: Snapshot,
    policy: PolicyView,
    horizon: int,
    *,
    started: float,
    time_limit_seconds: float,
) -> tuple[list[tuple[int, int, int, int]], str]:
    model = cp_model.CpModel()
    slots = len(members)
    wallet_names = sorted(snapshot.operational)
    source = snapshot.source
    source_balance = int(source.balance)
    source_buffer = int(source.buffer)
    pay_daily = int(policy.pay.daily)
    used_pay = int(snapshot.used_today["pay"])
    used_refill = int(snapshot.used_today["refill"])
    max_amount = [
        max((option.amount for option in candidates[i]), default=0) for i in range(len(ordered))
    ]
    amount_cap = sum(max_amount[i] for i in members)
    # Daily/per-request limits larger than anything reachable never bind: clamp them so
    # domains stay small without changing any comparison.
    pay_daily_c = min(pay_daily, used_pay + amount_cap + 1)
    refill_daily_c = min(int(policy.refill.daily), used_refill + source_balance + 1)
    per_refill_c = min(int(policy.refill.per_request), source_balance + 1)

    # --- request-level variables -------------------------------------------------
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    day_of: dict[int, cp_model.IntVar] = {}
    amount_of: dict[int, cp_model.IntVar] = {}
    paid_expr: dict[int, cp_model.LinearExpr] = {}
    for i in members:
        for option in candidates[i]:
            x[i, option.day] = model.NewBoolVar(f"x_{i}_{option.day}")
        day_of[i] = model.NewIntVar(0, horizon - 1, f"day_{i}")
        amount_of[i] = model.NewIntVar(0, max_amount[i], f"amount_{i}")
        paid_expr[i] = cp_model.LinearExpr.sum([x[i, option.day] for option in candidates[i]])
        model.Add(paid_expr[i] <= 1)  # constraint 1
        model.Add(day_of[i] == sum(option.day * x[i, option.day] for option in candidates[i]))
        model.Add(amount_of[i] == sum(option.amount * x[i, option.day] for option in candidates[i]))

    # --- slot sequence -------------------------------------------------------------
    z = {(i, s): model.NewBoolVar(f"z_{i}_{s}") for i in members for s in range(slots)}
    used = [model.NewBoolVar(f"used_{s}") for s in range(slots)]
    day_v = [model.NewIntVar(0, horizon - 1, f"dayv_{s}") for s in range(slots)]
    for i in members:
        model.Add(sum(z[i, s] for s in range(slots)) == paid_expr[i])
    for s in range(slots):
        model.Add(sum(z[i, s] for i in members) == used[s])
        if s + 1 < slots:
            model.Add(used[s] >= used[s + 1])
            model.Add(day_v[s] <= day_v[s + 1])
        if s == 0:
            model.Add(day_v[0] == 0).OnlyEnforceIf(used[0].Not())
        else:
            model.Add(day_v[s] == day_v[s - 1]).OnlyEnforceIf(used[s].Not())
        for i in members:
            model.Add(day_v[s] == day_of[i]).OnlyEnforceIf(z[i, s])

    # --- state carried along the slots ---------------------------------------------
    wallet_cap = {
        name: int(snapshot.operational[name].balance) + source_balance for name in wallet_names
    }
    balance = {
        name: [model.NewIntVar(0, wallet_cap[name], f"bal_{name}_{s}") for s in range(slots + 1)]
        for name in wallet_names
    }
    for name in wallet_names:
        model.Add(balance[name][0] == int(snapshot.operational[name].balance))
    src = [model.NewIntVar(0, source_balance, f"src_{s}") for s in range(slots + 1)]
    model.Add(src[0] == source_balance)

    amt = [model.NewIntVar(0, max(amount_cap, 0), f"amt_{s}") for s in range(slots)]
    ref = [model.NewIntVar(0, source_balance, f"ref_{s}") for s in range(slots)]
    bsel = [model.NewIntVar(0, max(wallet_cap.values()), f"bsel_{s}") for s in range(slots)]
    buf_max = max(int(w.buffer) for w in snapshot.operational.values())
    tgt_max = max(int(w.target) for w in snapshot.operational.values())
    bufv = [model.NewIntVar(0, buf_max, f"buf_{s}") for s in range(slots)]
    tgtv = [model.NewIntVar(0, tgt_max, f"tgt_{s}") for s in range(slots)]
    need_cap = amount_cap + max(buf_max, tgt_max) + 1
    need_min = [model.NewIntVar(0, need_cap, f"min_{s}") for s in range(slots)]
    need_pref = [model.NewIntVar(0, need_cap, f"pref_{s}") for s in range(slots)]
    cap_src = [model.NewIntVar(0, source_balance, f"capsrc_{s}") for s in range(slots)]
    cap_day = [model.NewIntVar(0, refill_daily_c, f"capday_{s}") for s in range(slots)]
    cap_all = [model.NewIntVar(0, source_balance, f"cap_{s}") for s in range(slots)]
    pay_base = [model.NewIntVar(0, used_pay + amount_cap, f"paybase_{s}") for s in range(slots)]
    pay_acc = [model.NewIntVar(0, used_pay + amount_cap, f"payacc_{s}") for s in range(slots)]
    refill_base = [
        model.NewIntVar(0, used_refill + source_balance, f"refbase_{s}") for s in range(slots)
    ]

    for s in range(slots):
        for i in members:
            request = ordered[i]
            wallet = snapshot.operational[request.paying_wallet]
            model.Add(amt[s] == amount_of[i]).OnlyEnforceIf(z[i, s])
            model.Add(bsel[s] == balance[request.paying_wallet][s]).OnlyEnforceIf(z[i, s])
            model.Add(bufv[s] == int(wallet.buffer)).OnlyEnforceIf(z[i, s])
            model.Add(tgtv[s] == int(wallet.target)).OnlyEnforceIf(z[i, s])
        for var in (amt[s], ref[s], bsel[s], bufv[s], tgtv[s]):
            model.Add(var == 0).OnlyEnforceIf(used[s].Not())

        for name in wallet_names:
            in_wallet = model.NewBoolVar(f"in_{name}_{s}")
            model.Add(
                sum(z[i, s] for i in members if ordered[i].paying_wallet == name) == in_wallet
            )
            model.Add(balance[name][s + 1] == balance[name][s] + ref[s] - amt[s]).OnlyEnforceIf(
                in_wallet
            )
            model.Add(balance[name][s + 1] == balance[name][s]).OnlyEnforceIf(in_wallet.Not())
        model.Add(src[s + 1] == src[s] - ref[s])

        # Daily pay (constraint 4) and refill (5) counters restart on every new day;
        # today's usage seeds day offset 0.
        same_day = model.NewBoolVar(f"same_{s}")
        if s == 0:
            model.Add(day_v[0] == 0).OnlyEnforceIf(same_day)
            model.Add(day_v[0] >= 1).OnlyEnforceIf(same_day.Not())
            model.Add(pay_base[0] == used_pay).OnlyEnforceIf(same_day)
            model.Add(refill_base[0] == used_refill).OnlyEnforceIf(same_day)
        else:
            model.Add(day_v[s] == day_v[s - 1]).OnlyEnforceIf(same_day)
            model.Add(day_v[s] > day_v[s - 1]).OnlyEnforceIf(same_day.Not())
            model.Add(pay_base[s] == pay_acc[s - 1]).OnlyEnforceIf(same_day)
            model.Add(refill_base[s] == refill_base[s - 1] + ref[s - 1]).OnlyEnforceIf(same_day)
        model.Add(pay_base[s] == 0).OnlyEnforceIf(same_day.Not())
        model.Add(refill_base[s] == 0).OnlyEnforceIf(same_day.Not())
        model.Add(pay_acc[s] == pay_base[s] + amt[s])
        model.Add(pay_acc[s] <= pay_daily_c).OnlyEnforceIf(used[s])

        # Refill rules (BR-032 / constraints 5, 6, 8).
        model.AddMaxEquality(need_min[s], [amt[s] + bufv[s] - bsel[s], 0])
        model.AddMaxEquality(need_pref[s], [amt[s] + tgtv[s] - bsel[s], 0])
        model.AddMaxEquality(cap_src[s], [src[s] - source_buffer, 0])
        model.AddMaxEquality(cap_day[s], [refill_daily_c - refill_base[s], 0])
        model.AddMinEquality(cap_all[s], [cap_src[s], cap_day[s], per_refill_c])
        short = model.NewBoolVar(f"short_{s}")
        model.Add(need_min[s] >= 1).OnlyEnforceIf(short)
        model.Add(need_min[s] == 0).OnlyEnforceIf(short.Not())
        top_up = model.NewBoolVar(f"topup_{s}")
        model.AddImplication(top_up, short)
        model.Add(ref[s] == 0).OnlyEnforceIf(short.Not())
        model.Add(need_min[s] <= need_pref[s]).OnlyEnforceIf(short)  # refill bound
        model.Add(cap_all[s] >= need_min[s]).OnlyEnforceIf(short)
        model.Add(ref[s] == need_min[s]).OnlyEnforceIf(short, top_up.Not())
        model.Add(cap_all[s] >= need_pref[s]).OnlyEnforceIf(top_up)
        model.Add(ref[s] == need_pref[s]).OnlyEnforceIf(top_up)

    # --- objective stages ------------------------------------------------------------
    zero = model.NewConstant(0)  # keeps every stage expression a LinearExpr
    missed = (
        zero
        + sum(
            1
            - sum(
                x[i, o.day]
                for o in candidates[i]
                if o.day <= ordered[i].terms.net_due_day - snapshot.day
            )
            for i in members
            if deadline_feasible[i]
        )
        + sum(1 for i in range(len(ordered)) if deadline_feasible[i] and i not in members)
    )
    value = zero + sum(o.value * x[i, o.day] for i in members for o in candidates[i])
    refilled = [model.NewBoolVar(f"refilled_{s}") for s in range(slots)]
    for s in range(slots):
        model.Add(ref[s] >= 1).OnlyEnforceIf(refilled[s])
        model.Add(ref[s] == 0).OnlyEnforceIf(refilled[s].Not())
    transactions = zero + sum(used[s] + refilled[s] for s in range(slots))
    tie_break = (
        zero
        + sum(
            weights[i]
            * (sum(o.day * x[i, o.day] for o in candidates[i]) + horizon * (1 - paid_expr[i]))
            for i in members
        )
        + sum(weights[i] * horizon for i in range(len(ordered)) if i not in members)
    )

    stages: list[tuple[bool, cp_model.LinearExprT]] = [
        (False, missed),
        (True, value),
        (False, transactions),
        (False, tie_break),
    ]
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = CPSAT_NUM_WORKERS
    solver.parameters.random_seed = CPSAT_RANDOM_SEED
    solver.parameters.log_search_progress = False
    outcome = "OPTIMAL"
    for position, (maximise, expression) in enumerate(stages):
        remaining = time_limit_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise _CpSatUnavailable("time limit exhausted before the solve finished")
        solver.parameters.max_time_in_seconds = remaining / (len(stages) - position)
        if maximise:
            model.Maximize(expression)
        else:
            model.Minimize(expression)
        solved = solver.Solve(model)
        if solved == cp_model.OPTIMAL:
            bound_op = "=="
        elif solved == cp_model.FEASIBLE:
            outcome = "FEASIBLE"
            bound_op = ">=" if maximise else "<="
        else:
            raise _CpSatUnavailable(f"stage {position + 1} ended with {solver.StatusName(solved)}")
        reached = solver.Value(expression)  # exact integer, unlike ObjectiveValue()
        if position + 1 < len(stages):
            if bound_op == "==":
                model.Add(expression == reached)
            elif bound_op == ">=":
                model.Add(expression >= reached)
            else:
                model.Add(expression <= reached)

    chosen: list[tuple[int, int, int, int]] = []
    for s in range(slots):
        if not solver.Value(used[s]):
            continue
        index = next(i for i in members if solver.Value(z[i, s]))
        day = solver.Value(day_v[s])
        option = next(o for o in candidates[index] if o.day == day)
        chosen.append((index, day, solver.Value(ref[s]), option.value))
    return chosen, outcome


def _build_schedule(
    ordered: Sequence[ApprovedRequest],
    chosen: Sequence[tuple[int, int, int, int]],
    status: str,
    snapshot: Snapshot,
    policy: PolicyView,
    horizon: int,
) -> Schedule:
    """Replay the solver's plan through the shared payment rules and describe the leftovers."""

    by_day: dict[int, list[tuple[int, int, int]]] = {}
    for index, day, refill, value in chosen:
        by_day.setdefault(day, []).append((index, refill, value))

    state = _SimulationState.start(snapshot, ordered)
    items: list[ScheduledItem] = []
    binding: set[str] = set()
    unpaid = set(range(len(ordered)))
    for offset in range(horizon):
        day = snapshot.day + offset
        state.start_day(day, snapshot)
        for index, refill, value in by_day.get(offset, []):
            checked = _replay(ordered[index], day, snapshot, policy, state, refill)
            items.append(
                ScheduledItem(
                    request_id=ordered[index].id,
                    day=day,
                    refill=checked,
                    value=value,
                )
            )
            unpaid.discard(index)
        for index in sorted(unpaid):
            _item, reason = _try_schedule_request(
                ordered[index], day, snapshot, policy, state.copy()
            )
            if reason is not None:
                binding.add(_BINDING[reason])

    scheduled_ids = {item.request_id for item in items}
    infeasible: list[Infeasible] = []
    for request in ordered:
        if request.id in scheduled_ids:
            continue
        active_day = snapshot.payee_active_day.get(request.payee)
        if active_day is None:
            reason = PolicyReasonCode.PAYEE_UNKNOWN
            detail = "Payee is not in the snapshot, so its activation day was never read."
        elif (days := range(max(snapshot.day, active_day), snapshot.day + horizon)) and all(
            _needs_exception(request, d, policy) for d in days
        ):
            reason = NEEDS_EXCEPTION
            detail = "Approved request exceeds the per-request pay cap; Owner exception required."
        else:
            reason = CPSAT_NOT_SELECTED
            detail = (
                f"No payment of this request within the {horizon}-day horizon is both "
                "feasible and better under the lexicographic objective."
            )
        if reason in _BINDING:
            binding.add(_BINDING[reason])
        infeasible.append(Infeasible(request_id=request.id, reason=reason, detail=detail))

    return Schedule(
        items=tuple(items),
        infeasible=tuple(infeasible),
        objective=_schedule_objective(ordered, snapshot, policy, items),
        binding=tuple(sorted(binding)),
        solver="CPSAT",
        status="OPTIMAL" if status == "OPTIMAL" else "FEASIBLE",
    )


def _replay(
    request: ApprovedRequest,
    day: int,
    snapshot: Snapshot,
    policy: PolicyView,
    state: _SimulationState,
    refill: int,
) -> BaseUnits:
    """Apply one planned payment through the shared rules; reject a plan they would block."""

    for minimal in (False, True):
        trial = state.copy()
        item, _reason = _try_schedule_request(
            request, day, snapshot, policy, trial, minimal_refill=minimal
        )
        if item is not None and int(item.refill) == refill:
            _try_schedule_request(request, day, snapshot, policy, state, minimal_refill=minimal)
            return item.refill
    raise _CpSatUnavailable(f"plan for {request.id!r} on day {day} fails the payment rules")
