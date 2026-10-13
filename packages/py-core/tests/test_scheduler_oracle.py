from __future__ import annotations

import itertools

import pytest
from hypothesis import given, settings

from tests.strategies.financial_engine import SchedulerScenario, small_scheduler_scenarios
from treasurypilot_core.domain import (
    ApprovedRequest,
    Limits,
    PaymentTerms,
    PolicyView,
    Snapshot,
    WalletState,
)
from treasurypilot_core.engine import schedule_edf, schedule_oracle
from treasurypilot_core.engine.scheduler import (
    ORACLE_NOT_SELECTED,
    _schedule_objective,
    _SimulationState,
    _try_schedule_request,
)
from treasurypilot_core.money import BaseUnits


def _snapshot(*, ops_balance: int = 0) -> Snapshot:
    return Snapshot(
        day=0,
        source=WalletState(
            address="safe",
            balance=BaseUnits(0),
            buffer=BaseUnits(0),
            target=BaseUnits(0),
        ),
        operational={
            "ops": WalletState(
                address="ops",
                balance=BaseUnits(ops_balance),
                buffer=BaseUnits(0),
                target=BaseUnits(0),
            )
        },
        used_today={"pay": BaseUnits(0), "refill": BaseUnits(0)},
        payee_active_day={"payee": 0},
        safe_usdc=BaseUnits(0),
        a_usdc=BaseUnits(0),
        pool_available=BaseUnits(0),
        supply_rate_bps=0,
        borrow_rate_bps=0,
        debt=BaseUnits(0),
    )


def _policy(*, pay_daily: int = 100, pay_per_request: int = 100) -> PolicyView:
    return PolicyView(
        pay=Limits(
            per_request=BaseUnits(pay_per_request),
            daily=BaseUnits(pay_daily),
        ),
        refill=Limits(per_request=BaseUnits(0), daily=BaseUnits(0)),
        cooling_seconds=0,
    )


def _request(
    request_id: str,
    *,
    seq: int,
    early_amount: int,
    early_pay_by: int,
) -> ApprovedRequest:
    return ApprovedRequest(
        id=request_id,
        paying_wallet="ops",
        payee="payee",
        amount=BaseUnits(100),
        approved_seq=seq,
        terms=PaymentTerms(net_due_day=2),
        early_amount=BaseUnits(early_amount),
        early_pay_by=early_pay_by,
    )


def test_oracle_finds_the_hand_computed_value_optimum() -> None:
    # Only one invoice fits the day-0 pay cap. Both orders fit the wallet balance:
    # B then A captures 10 + 20 units of discount, while A then B captures 20.
    request_a = _request("A", seq=0, early_amount=80, early_pay_by=1)
    request_b = _request("B", seq=1, early_amount=90, early_pay_by=0)

    result = schedule_oracle(
        [request_a, request_b],
        _snapshot(ops_balance=180),
        _policy(),
    )

    assert [(item.request_id, item.day, item.value) for item in result.items] == [
        ("B", 0, 10),
        ("A", 1, 20),
    ]
    assert result.objective == (0, 0, -30, 2)
    assert result.solver == "ORACLE"
    assert result.status == "OPTIMAL"


def test_oracle_prioritizes_a_feasible_deadline_over_larger_value() -> None:
    due_today = ApprovedRequest(
        id="due-today",
        paying_wallet="ops",
        payee="payee",
        amount=BaseUnits(100),
        approved_seq=0,
        terms=PaymentTerms(net_due_day=0),
    )
    discounted = _request("discounted", seq=1, early_amount=80, early_pay_by=1)

    result = schedule_oracle(
        [due_today, discounted],
        _snapshot(ops_balance=180),
        _policy(),
    )

    assert [(item.request_id, item.day, item.value) for item in result.items] == [
        ("due-today", 0, 0),
        ("discounted", 1, 20),
    ]
    assert result.objective == (0, 0, -20, 2)


def test_oracle_accepts_eight_requests_and_five_day_horizon() -> None:
    requests = [
        ApprovedRequest(
            id=f"request-{index}",
            paying_wallet="ops",
            payee="payee",
            amount=BaseUnits(1),
            approved_seq=index,
            terms=PaymentTerms(net_due_day=4),
        )
        for index in range(8)
    ]

    result = schedule_oracle(requests, _snapshot(), _policy(pay_daily=0))

    assert result.items == ()
    assert len(result.infeasible) == 8


def test_oracle_refuses_more_than_eight_requests() -> None:
    requests = [
        ApprovedRequest(
            id=f"request-{index}",
            paying_wallet="ops",
            payee="payee",
            amount=BaseUnits(1),
            approved_seq=index,
            terms=PaymentTerms(net_due_day=0),
        )
        for index in range(9)
    ]

    with pytest.raises(ValueError, match="at most 8 requests"):
        schedule_oracle(requests, _snapshot(), _policy())


def test_oracle_refuses_horizons_longer_than_five_days() -> None:
    request = ApprovedRequest(
        id="too-far",
        paying_wallet="ops",
        payee="payee",
        amount=BaseUnits(1),
        approved_seq=0,
        terms=PaymentTerms(net_due_day=5),
    )

    with pytest.raises(ValueError, match="horizon of at most 5 days"):
        schedule_oracle([request], _snapshot(), _policy())


@settings(max_examples=50, deadline=None)
@given(small_scheduler_scenarios())
def test_generated_oracle_results_account_for_each_request_once(
    scenario: SchedulerScenario,
) -> None:
    requests, snapshot, policy = scenario

    result = schedule_oracle(requests, snapshot, policy)

    outcome_ids = [item.request_id for item in result.items] + [
        item.request_id for item in result.infeasible
    ]
    assert sorted(outcome_ids) == sorted(request.id for request in requests)
    assert result.objective[0] == 0
    last_day = max(
        [r.terms.net_due_day for r in requests]
        + [
            snapshot.payee_active_day[r.payee]
            for r in requests
            if r.payee in snapshot.payee_active_day
        ]
    )
    assert all(snapshot.day <= item.day <= last_day for item in result.items)


@settings(max_examples=100, deadline=None)
@given(small_scheduler_scenarios())
def test_generated_oracle_is_never_worse_than_edf(scenario: SchedulerScenario) -> None:
    requests, snapshot, policy = scenario

    oracle = schedule_oracle(requests, snapshot, policy)
    edf = schedule_edf(requests, snapshot, policy)

    assert oracle.objective <= edf.objective


def _worst_case_requests(*, count: int = 8, due_day: int = 4) -> list[ApprovedRequest]:
    return [
        ApprovedRequest(
            id=f"request-{index}",
            paying_wallet="ops",
            payee="payee",
            amount=BaseUnits(100 + index),
            approved_seq=index,
            terms=PaymentTerms(net_due_day=due_day),
            early_amount=BaseUnits(50 + index),
            early_pay_by=index % due_day,
        )
        for index in range(count)
    ]


def test_oracle_solves_fixed_worst_case_bounds_with_slack_limits() -> None:
    # N=8, H=5, nothing binding: every shared prefix must be solved once, not per mask.
    requests = _worst_case_requests()

    result = schedule_oracle(
        requests,
        _snapshot(ops_balance=10_000),
        _policy(pay_daily=10_000, pay_per_request=10_000),
    )

    assert len(result.items) == 8
    assert result.objective[:2] == (0, 0)
    assert result.objective[3] == 8


def test_oracle_solves_fixed_worst_case_bounds_with_binding_limits() -> None:
    # N=8, H=5 with a pay cap that fits only two payments a day and a refill budget.
    requests = _worst_case_requests()
    snapshot = _snapshot(ops_balance=150)
    snapshot = snapshot.model_copy(
        update={
            "source": WalletState(
                address="safe",
                balance=BaseUnits(1_000),
                buffer=BaseUnits(0),
                target=BaseUnits(0),
            ),
            "operational": {
                "ops": WalletState(
                    address="ops",
                    balance=BaseUnits(150),
                    buffer=BaseUnits(10),
                    target=BaseUnits(60),
                )
            },
        }
    )
    policy = _policy(pay_daily=220, pay_per_request=200).model_copy(
        update={"refill": Limits(per_request=BaseUnits(300), daily=BaseUnits(400))}
    )

    oracle = schedule_oracle(requests, snapshot, policy)
    edf = schedule_edf(requests, snapshot, policy)

    assert oracle.objective <= edf.objective


def test_oracle_chooses_shortage_refill_when_greedy_top_up_starves_another_wallet() -> None:
    # Two wallets share refill.daily=150. EDF tops A's wallet up to target (150) and
    # leaves nothing for B; refilling only the shortage (50 each) fits both.
    def wallet(name: str) -> WalletState:
        return WalletState(
            address=name, balance=BaseUnits(0), buffer=BaseUnits(0), target=BaseUnits(100)
        )

    snapshot = _snapshot().model_copy(
        update={
            "source": WalletState(
                address="safe",
                balance=BaseUnits(1_000),
                buffer=BaseUnits(0),
                target=BaseUnits(0),
            ),
            "operational": {"ops-a": wallet("ops-a"), "ops-b": wallet("ops-b")},
        }
    )
    policy = _policy(pay_daily=1_000, pay_per_request=1_000).model_copy(
        update={"refill": Limits(per_request=BaseUnits(500), daily=BaseUnits(150))}
    )
    requests = [
        ApprovedRequest(
            id=request_id,
            paying_wallet=wallet_name,
            payee="payee",
            amount=BaseUnits(50),
            approved_seq=seq,
            terms=PaymentTerms(net_due_day=0),
        )
        for seq, (request_id, wallet_name) in enumerate((("A", "ops-a"), ("B", "ops-b")))
    ]

    edf = schedule_edf(requests, snapshot, policy)
    oracle = schedule_oracle(requests, snapshot, policy)

    assert edf.objective[1] == 1
    assert oracle.objective == (0, 0, 0, 4)
    assert sorted((item.request_id, item.refill) for item in oracle.items) == [
        ("A", 50),
        ("B", 50),
    ]


def test_oracle_horizon_includes_payee_active_day() -> None:
    request = ApprovedRequest(
        id="late-payee",
        paying_wallet="ops",
        payee="payee",
        amount=BaseUnits(10),
        approved_seq=0,
        terms=PaymentTerms(net_due_day=1),
    )
    snapshot = _snapshot(ops_balance=100).model_copy(update={"payee_active_day": {"payee": 3}})

    result = schedule_oracle([request], snapshot, _policy())

    # The deadline is unreachable (payee inactive until day 3), so paying late only adds a
    # transaction: omitted on the objective, and the explanation covers the days to day 3.
    assert result.items == ()
    assert result.objective == (0, 0, 0, 0)
    assert [(item.request_id, item.reason) for item in result.infeasible] == [
        ("late-payee", ORACLE_NOT_SELECTED)
    ]
    assert "4-day search horizon" in result.infeasible[0].detail

    far_payee = _snapshot(ops_balance=100).model_copy(update={"payee_active_day": {"payee": 5}})
    with pytest.raises(ValueError, match="horizon of at most 5 days"):
        schedule_oracle([request], far_payee, _policy())


def test_oracle_infeasible_records_are_its_own_not_edfs() -> None:
    requests = _worst_case_requests(count=2, due_day=1)

    result = schedule_oracle(requests, _snapshot(), _policy(pay_daily=0))

    assert {item.reason for item in result.infeasible} == {ORACLE_NOT_SELECTED}
    assert all("30-day" not in item.detail for item in result.infeasible)
    assert all("first blocker" not in item.detail for item in result.infeasible)
    assert "2-day search horizon" in result.infeasible[0].detail


def test_oracle_reports_binding_constraint_of_scheduled_items() -> None:
    # The pay daily cap pushes A to day 1, so it is binding although nothing is omitted.
    request_a = _request("A", seq=0, early_amount=80, early_pay_by=1)
    request_b = _request("B", seq=1, early_amount=90, early_pay_by=0)

    result = schedule_oracle([request_a, request_b], _snapshot(ops_balance=180), _policy())

    assert result.infeasible == ()
    assert result.binding == ("PAY_DAILY_CAP",)


def test_oracle_reports_unknown_payee_without_edf_text() -> None:
    request = ApprovedRequest(
        id="ghost",
        paying_wallet="ops",
        payee="ghost-payee",
        amount=BaseUnits(10),
        approved_seq=0,
        terms=PaymentTerms(net_due_day=0),
    )

    result = schedule_oracle([request], _snapshot(ops_balance=100), _policy())

    assert [(item.request_id, item.reason) for item in result.infeasible] == [
        ("ghost", "PAYEE_UNKNOWN")
    ]
    assert result.binding == ("PAYEE_UNKNOWN",)


def _brute_force_objective(
    requests: list[ApprovedRequest], snapshot: Snapshot, policy: PolicyView
) -> tuple[int, int, int, int]:
    """Enumerate day assignments x same-day orders x refill kinds without any memoization."""

    horizon = (
        max(max(r.terms.net_due_day, snapshot.payee_active_day.get(r.payee, 0)) for r in requests)
        - snapshot.day
        + 1
    )
    best: tuple[int, int, int, int] | None = None
    for days in itertools.product([None, *range(horizon)], repeat=len(requests)):
        paid = [(i, d) for i, d in enumerate(days) if d is not None]
        for order in itertools.permutations(paid):
            ordered_by_day = sorted(order, key=lambda pair: pair[1])  # stable per day
            for minimal in itertools.product((False, True), repeat=len(ordered_by_day)):
                state = _SimulationState(dict(snapshot.operational), snapshot.source)
                items = []
                current_day = None
                ok = True
                for (i, d), use_minimal in zip(ordered_by_day, minimal, strict=True):
                    if d != current_day:
                        state.start_day(snapshot.day + d, snapshot)
                        current_day = d
                    item, _ = _try_schedule_request(
                        requests[i],
                        snapshot.day + d,
                        snapshot,
                        policy,
                        state,
                        minimal_refill=use_minimal,
                    )
                    if item is None:
                        ok = False
                        break
                    items.append(item)
                if not ok:
                    continue
                # Same-day state resets only when the day changes, so day order must be
                # non-decreasing; sorted() guarantees it.
                objective = _schedule_objective(
                    sorted(requests, key=lambda r: (r.terms.net_due_day, r.approved_seq, r.id)),
                    snapshot,
                    policy,
                    items,
                )
                if best is None or objective < best:
                    best = objective
    assert best is not None
    return best


@settings(max_examples=40, deadline=None)
@given(small_scheduler_scenarios(max_requests=3, max_due_offset=2))
def test_generated_oracle_objective_matches_brute_force(scenario: SchedulerScenario) -> None:
    requests, snapshot, policy = scenario

    assert schedule_oracle(requests, snapshot, policy).objective == _brute_force_objective(
        requests, snapshot, policy
    )
