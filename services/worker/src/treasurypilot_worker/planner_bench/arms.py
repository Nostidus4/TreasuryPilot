"""The three arms and the outcome metrics they are compared on.

* B0: manual / earliest-deadline-first, idle cash. The EDF schedule on the state as found; no
  supply or withdraw action is ever taken.
* B1: the deterministic planner. EDF plus the liquidity engine's one action per cycle (SUPPLY
  idle cash, WITHDRAW to restore the reserve), then EDF again on the post-action balances.
* B2: B1 plus the AI proposal, through the production `select_plan` (valid and strictly better,
  else B1's plan). It plans on exactly B1's post-liquidity state and is checked by the same
  `score`, so the arms differ only in the plan.

All money is integer base units. With six-decimal assets one USD micro equals one base unit, so
AI cost is netted against value directly (`Scenario` loading refuses other decimals).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

from treasurypilot_core.domain import (
    ApprovedRequest,
    Schedule,
    ScheduledItem,
    Snapshot,
)
from treasurypilot_core.engine import (
    decide_liquidity,
    exception_values,
    liquidity_position,
    schedule_edf,
    score,
)
from treasurypilot_core.money import BaseUnits
from treasurypilot_worker.planner_bench.scenarios import Scenario

_BPS = 10_000
_DAYS_PER_YEAR = 365


@dataclass(frozen=True)
class Outcome:
    """What one arm achieved on one scenario (one repetition for B2)."""

    violations: int
    value_saved: int
    interest: int
    on_time: int
    requests: int
    paid: int
    missed_deadlines: int
    exceptions: int
    tx_count: int
    reserve_breaches: int
    liquidity_action: str
    latency_ms: int
    cost_usd_micros: int

    @property
    def net_benefit(self) -> int:
        """Value saved plus supply interest over the horizon, before AI cost."""

        return self.value_saved + self.interest

    @property
    def net_after_cost(self) -> int:
        return self.net_benefit - self.cost_usd_micros

    def worse_than(self, other: Outcome) -> list[str]:
        """Outcome metrics (never cost or latency) on which `self` loses to `other`."""

        worse = []
        if self.violations > other.violations:
            worse.append("violations")
        if self.value_saved < other.value_saved:
            worse.append("value saved")
        if self.net_benefit < other.net_benefit:
            worse.append("net benefit")
        if self.missed_deadlines > other.missed_deadlines:
            worse.append("missed deadlines")
        if self.on_time < other.on_time:
            worse.append("on-time")
        if self.exceptions > other.exceptions:
            worse.append("exceptions")
        if self.tx_count > other.tx_count:
            worse.append("transactions")
        if self.reserve_breaches > other.reserve_breaches:
            worse.append("reserve breaches")
        return worse


@dataclass(frozen=True)
class Position:
    """The state an arm plans on: the snapshot after the arm's liquidity action."""

    snapshot: Snapshot
    action: str
    interest: int


def _interest(snapshot: Snapshot, horizon_days: int) -> int:
    """Simple interest on what sits in Aave for the horizon (floor)."""

    return int(snapshot.a_usdc) * snapshot.supply_rate_bps * horizon_days // (_BPS * _DAYS_PER_YEAR)


def idle_position(scenario: Scenario) -> Position:
    """B0: the state as found, cash left where it is."""

    snap = scenario.snapshot
    return Position(snap, "NONE", _interest(snap, scenario.horizon_days))


def liquidity_state(scenario: Scenario, plan: Schedule) -> Position:
    """Apply the liquidity engine's single action for `plan` and return the new state."""

    snap = scenario.snapshot
    decision = decide_liquidity(snap, scenario.requests, plan, scenario.liquidity)
    amount = int(decision.amount)
    if decision.kind == "SUPPLY":
        moved = {
            "source": snap.source.model_copy(
                update={"balance": BaseUnits(int(snap.source.balance) - amount)}
            ),
            "safe_usdc": BaseUnits(int(snap.safe_usdc) - amount),
            "a_usdc": BaseUnits(int(snap.a_usdc) + amount),
        }
    elif decision.kind in ("WITHDRAW", "INSUFFICIENT_LIQUIDITY") and amount > 0:
        moved = {
            "source": snap.source.model_copy(
                update={"balance": BaseUnits(int(snap.source.balance) + amount)}
            ),
            "safe_usdc": BaseUnits(int(snap.safe_usdc) + amount),
            "a_usdc": BaseUnits(int(snap.a_usdc) - amount),
            "pool_available": BaseUnits(int(snap.pool_available) - amount),
        }
    else:
        return idle_position(scenario)
    moved_snap = snap.model_copy(update=moved)
    kind = decision.kind if amount > 0 else "NONE"
    return Position(moved_snap, kind, _interest(moved_snap, scenario.horizon_days))


def _as_schedule(items: Sequence[ScheduledItem], plan_score: tuple[int, int, int, int]) -> Schedule:
    return Schedule(
        items=tuple(items),
        infeasible=(),
        objective=plan_score,
        binding=(),
        solver="EDF",
        status="FEASIBLE",
    )


def measure(
    scenario: Scenario,
    position: Position,
    items: Sequence[ScheduledItem],
    *,
    latency_ms: int = 0,
    cost_usd_micros: int = 0,
) -> Outcome:
    """Score one plan on one state with the shared engine `score` (ground truth is not used)."""

    snap, requests = position.snapshot, scenario.requests
    plan_score = score(items, requests, snap, scenario.policy)
    violations, missed, negated_value, tx_count = plan_score
    paid_day = {item.request_id: item.day for item in items}
    on_time = sum(1 for r in requests if r.id in paid_day and paid_day[r.id] <= r.terms.net_due_day)
    reserve = liquidity_position(
        snap, requests, _as_schedule(items, plan_score), scenario.liquidity
    )
    return Outcome(
        violations=violations,
        value_saved=-negated_value,
        interest=position.interest,
        on_time=on_time,
        requests=len(requests),
        paid=len(paid_day),
        missed_deadlines=missed,
        exceptions=len(exception_values(_unpaid(requests, paid_day), snap, scenario.policy)),
        tx_count=tx_count,
        reserve_breaches=int(int(reserve.deficit) > 0),
        liquidity_action=position.action,
        latency_ms=latency_ms,
        cost_usd_micros=cost_usd_micros,
    )


def _unpaid(requests: Sequence[ApprovedRequest], paid_day: dict[str, int]) -> list[ApprovedRequest]:
    return [r for r in requests if r.id not in paid_day]


@dataclass(frozen=True)
class DeterministicArms:
    """B0 and B1 outcomes plus what B2 needs to plan on the same state as B1."""

    b0: Outcome
    b1: Outcome
    b1_position: Position
    b1_schedule: Schedule


def _elapsed_ms(started: int) -> int:
    return (time.perf_counter_ns() - started) // 1_000_000


def run_deterministic(scenario: Scenario) -> DeterministicArms:
    started = time.perf_counter_ns()
    b0_plan = schedule_edf(scenario.requests, scenario.snapshot, scenario.policy)
    b0 = measure(
        scenario,
        idle_position(scenario),
        b0_plan.items,
        latency_ms=_elapsed_ms(started),
    )
    started = time.perf_counter_ns()
    position = liquidity_state(scenario, b0_plan)
    b1_plan = (
        b0_plan
        if position.snapshot is scenario.snapshot
        else schedule_edf(scenario.requests, position.snapshot, scenario.policy)
    )
    b1 = measure(scenario, position, b1_plan.items, latency_ms=_elapsed_ms(started))
    return DeterministicArms(b0, b1, position, b1_plan)
