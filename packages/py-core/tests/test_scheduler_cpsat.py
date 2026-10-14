from __future__ import annotations

from collections.abc import Sequence

import pytest
from hypothesis import given, settings

from tests.strategies.financial_engine import SchedulerScenario, small_scheduler_scenarios
from tests.test_scheduler_oracle import _policy, _request, _snapshot
from treasurypilot_core.domain import ApprovedRequest, PaymentTerms, ScheduledItem
from treasurypilot_core.engine import (
    get_solver,
    schedule_cpsat,
    schedule_edf,
    schedule_oracle,
)
from treasurypilot_core.engine.cpsat import CPSAT_NOT_SELECTED
from treasurypilot_core.engine.scheduler import _SimulationState, _try_schedule_request
from treasurypilot_core.money import BaseUnits


def _replay_is_valid(scenario: SchedulerScenario, result_items: Sequence[ScheduledItem]) -> bool:
    """Independent validator: every item must pass the shared payment rules in order."""

    requests, snapshot, policy = scenario
    by_id = {request.id: request for request in requests}
    state = _SimulationState(dict(snapshot.operational), snapshot.source)
    day = -1
    for item in result_items:
        if item.day != day:
            day = item.day
            state.start_day(day, snapshot)
        for minimal in (False, True):
            trial = state.copy()
            accepted, _ = _try_schedule_request(
                by_id[item.request_id], day, snapshot, policy, trial, minimal_refill=minimal
            )
            if accepted is not None and accepted.refill == item.refill:
                state = trial
                break
        else:
            return False
    return True


def test_cpsat_finds_the_hand_computed_value_optimum() -> None:
    # Same instance as the oracle's hand case: B on day 0 (+10) then A on day 1 (+20).
    request_a = _request("A", seq=0, early_amount=80, early_pay_by=1)
    request_b = _request("B", seq=1, early_amount=90, early_pay_by=0)

    result = schedule_cpsat([request_a, request_b], _snapshot(ops_balance=180), _policy())

    assert [(item.request_id, item.day, item.value) for item in result.items] == [
        ("B", 0, 10),
        ("A", 1, 20),
    ]
    assert result.objective == (0, 0, -30, 2)
    assert result.solver == "CPSAT"
    assert result.status == "OPTIMAL"


def test_cpsat_beats_edf_when_earliest_due_first_wastes_a_discount() -> None:
    # EDF pays the lower-seq request first on day 0 although only B's discount expires
    # today; the optimum swaps them and captures both discounts.
    request_a = _request("A", seq=0, early_amount=80, early_pay_by=1)
    request_b = _request("B", seq=1, early_amount=90, early_pay_by=0)
    snapshot, policy = _snapshot(ops_balance=180), _policy()

    edf = schedule_edf([request_a, request_b], snapshot, policy)
    result = schedule_cpsat([request_a, request_b], snapshot, policy)

    assert result.objective < edf.objective


def test_cpsat_prioritizes_a_feasible_deadline_over_larger_value() -> None:
    due_today = ApprovedRequest(
        id="due-today",
        paying_wallet="ops",
        payee="payee",
        amount=BaseUnits(100),
        approved_seq=0,
        terms=PaymentTerms(net_due_day=0),
    )
    discounted = _request("discounted", seq=1, early_amount=80, early_pay_by=1)

    result = schedule_cpsat([due_today, discounted], _snapshot(ops_balance=180), _policy())

    assert [(item.request_id, item.day) for item in result.items] == [
        ("due-today", 0),
        ("discounted", 1),
    ]
    assert result.objective == (0, 0, -20, 2)


def test_cpsat_reports_requests_it_cannot_pay() -> None:
    unknown = ApprovedRequest(
        id="stranger",
        paying_wallet="ops",
        payee="nobody",
        amount=BaseUnits(5),
        approved_seq=0,
        terms=PaymentTerms(net_due_day=1),
    )
    too_big = ApprovedRequest(
        id="too-big",
        paying_wallet="ops",
        payee="payee",
        amount=BaseUnits(500),
        approved_seq=1,
        terms=PaymentTerms(net_due_day=1),
    )

    result = schedule_cpsat([unknown, too_big], _snapshot(ops_balance=1000), _policy())

    assert result.items == ()
    assert {(i.request_id, i.reason) for i in result.infeasible} == {
        ("stranger", "PAYEE_UNKNOWN"),
        ("too-big", "NEEDS_EXCEPTION"),
    }
    assert result.status == "OPTIMAL"


def test_cpsat_unselected_request_gets_its_own_reason() -> None:
    # The daily cap only fits one payment per day and the horizon ends on day 0.
    requests = [
        ApprovedRequest(
            id=f"r{index}",
            paying_wallet="ops",
            payee="payee",
            amount=BaseUnits(60),
            approved_seq=index,
            terms=PaymentTerms(net_due_day=0),
        )
        for index in range(2)
    ]

    result = schedule_cpsat(requests, _snapshot(ops_balance=500), _policy())

    assert [item.request_id for item in result.items] == ["r0"]
    assert [(i.request_id, i.reason) for i in result.infeasible] == [("r1", CPSAT_NOT_SELECTED)]
    assert "PAY_DAILY_CAP" in result.binding


def test_cpsat_skips_early_payment_when_the_fee_exceeds_the_discount() -> None:
    request = _request("A", seq=0, early_amount=90, early_pay_by=0)
    snapshot, policy = _snapshot(ops_balance=500), _policy()

    free = schedule_cpsat([request], snapshot, policy)
    costly = schedule_cpsat([request], snapshot, policy, fee_in_asset=BaseUnits(15))

    assert [(item.day, item.value) for item in free.items] == [(0, 10)]
    # Saving 10 - fee 15 < 0, so the early day is worth less than paying right after the
    # early window (value 0, earliest tie-break day).
    assert [(item.day, item.value) for item in costly.items] == [(1, 0)]


def test_cpsat_treats_fee_held_today_as_infeasible_for_today_only() -> None:
    request = _request("A", seq=0, early_amount=90, early_pay_by=1)

    result = schedule_cpsat([request], _snapshot(ops_balance=500), _policy(), fee_hold_today=True)

    assert [(item.day, item.value) for item in result.items] == [(1, 10)]


def test_cpsat_counts_forgone_supply_interest_in_the_value() -> None:
    request = _request("A", seq=0, early_amount=90, early_pay_by=1)
    snapshot = _snapshot(ops_balance=500).model_copy(update={"supply_rate_bps": 10_000})

    result = schedule_cpsat([request], snapshot, _policy())

    # 90 * 100% * 1 day / 365 = 0 in integer math, so the discount is fully kept.
    assert result.items[0].value == 10


def test_cpsat_empty_input_is_an_empty_optimal_schedule() -> None:
    result = schedule_cpsat([], _snapshot(), _policy())

    assert result.items == () and result.infeasible == ()
    assert (result.solver, result.status) == ("CPSAT", "OPTIMAL")


def test_forced_one_millisecond_limit_returns_the_edf_schedule_as_fallback() -> None:
    request_a = _request("A", seq=0, early_amount=80, early_pay_by=1)
    request_b = _request("B", seq=1, early_amount=90, early_pay_by=0)
    snapshot, policy = _snapshot(ops_balance=180), _policy()

    result = schedule_cpsat([request_a, request_b], snapshot, policy, time_limit_seconds=0.001)

    expected = schedule_edf([request_a, request_b], snapshot, policy)
    assert result == expected.model_copy(update={"status": "FALLBACK"})
    assert (result.solver, result.status) == ("EDF", "FALLBACK")


def test_solver_crash_falls_back_to_edf(monkeypatch: pytest.MonkeyPatch) -> None:
    from treasurypilot_core.engine import cpsat

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cpsat, "_optimise", boom)
    request = _request("A", seq=0, early_amount=80, early_pay_by=1)

    result = schedule_cpsat([request], _snapshot(ops_balance=500), _policy())

    assert (result.solver, result.status) == ("EDF", "FALLBACK")


def test_bounds_guard_falls_back_instead_of_building_an_overflowing_model() -> None:
    huge = ApprovedRequest(
        id="huge",
        paying_wallet="ops",
        payee="payee",
        amount=BaseUnits(2**62),
        approved_seq=0,
        terms=PaymentTerms(net_due_day=1),
        exception_granted=True,
    )
    snapshot = _snapshot(ops_balance=2**62)

    result = schedule_cpsat([huge], snapshot, _policy(pay_daily=2**63, pay_per_request=2**63))

    assert (result.solver, result.status) == ("EDF", "FALLBACK")


def test_solver_registry_exposes_all_three_implementations() -> None:
    assert get_solver("EDF") is schedule_edf
    assert get_solver("CPSAT") is schedule_cpsat
    assert get_solver("ORACLE") is schedule_oracle


@settings(max_examples=60, deadline=None)
@given(small_scheduler_scenarios())
def test_cpsat_objective_equals_the_oracle_objective(scenario: SchedulerScenario) -> None:
    requests, snapshot, policy = scenario

    cpsat = schedule_cpsat(requests, snapshot, policy)
    oracle = schedule_oracle(requests, snapshot, policy)

    assert cpsat.status == "OPTIMAL"
    assert cpsat.objective == oracle.objective


@settings(max_examples=60, deadline=None)
@given(small_scheduler_scenarios())
def test_cpsat_never_schedules_what_the_validator_would_block(
    scenario: SchedulerScenario,
) -> None:
    requests, snapshot, policy = scenario

    result = schedule_cpsat(requests, snapshot, policy)

    assert _replay_is_valid(scenario, result.items)
    outcome_ids = [item.request_id for item in result.items] + [
        item.request_id for item in result.infeasible
    ]
    assert sorted(outcome_ids) == sorted(request.id for request in requests)


@settings(max_examples=60, deadline=None)
@given(small_scheduler_scenarios())
def test_cpsat_is_never_worse_than_edf(scenario: SchedulerScenario) -> None:
    requests, snapshot, policy = scenario

    assert (
        schedule_cpsat(requests, snapshot, policy).objective
        <= schedule_edf(requests, snapshot, policy).objective
    )


@settings(max_examples=25, deadline=None)
@given(small_scheduler_scenarios())
def test_cpsat_output_is_byte_identical_for_the_same_input(scenario: SchedulerScenario) -> None:
    requests, snapshot, policy = scenario

    first = schedule_cpsat(requests, snapshot, policy)
    second = schedule_cpsat(list(reversed(requests)), snapshot, policy)

    assert first.model_dump_json() == second.model_dump_json()


def test_payee_activating_beyond_the_horizon_is_not_selected_not_needing_an_exception() -> None:
    request = _request("A", seq=0, early_amount=80, early_pay_by=1)
    snapshot = _snapshot(ops_balance=500).model_copy(update={"payee_active_day": {"payee": 40}})

    result = schedule_cpsat([request], snapshot, _policy())

    assert [(item.request_id, item.reason) for item in result.infeasible] == [
        ("A", CPSAT_NOT_SELECTED)
    ]


def test_worse_than_edf_guard_still_checks_missed_deadlines_when_a_fee_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from treasurypilot_core.engine import cpsat

    # A solver that pays nothing misses a deadline EDF meets, whatever the fee.
    monkeypatch.setattr(cpsat, "_optimise", lambda *_args, **_kwargs: ([], "OPTIMAL"))
    request = _request("A", seq=0, early_amount=80, early_pay_by=1)

    result = schedule_cpsat(
        [request], _snapshot(ops_balance=500), _policy(), fee_in_asset=BaseUnits(1)
    )

    assert (result.solver, result.status) == ("EDF", "FALLBACK")
