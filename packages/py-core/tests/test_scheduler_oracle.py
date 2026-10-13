from __future__ import annotations

import random
from time import perf_counter

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.strategies.financial_engine import SchedulerScenario, small_scheduler_scenarios
from treasurypilot_core.domain import (
    ApprovedRequest,
    Limits,
    PaymentTerms,
    PolicyView,
    Snapshot,
    WalletState,
)
from treasurypilot_core.engine import schedule_oracle
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


def _generated_perf_scenario(rng: random.Random) -> SchedulerScenario:
    """Build a cheap seeded case for the 1,000-instance throughput acceptance."""

    request_count = rng.randint(1, 4)
    due_offset = rng.randint(0, 2)
    payees = {f"payee-{index}": rng.randint(0, due_offset) for index in range(2)}
    requests = []
    for index in range(request_count):
        due = rng.randint(0, due_offset)
        amount = rng.randint(1, 200)
        early = rng.choice((True, False))
        requests.append(
            ApprovedRequest(
                id=f"request-{index}",
                paying_wallet="ops",
                payee=rng.choice((*payees, "unknown-payee")),
                amount=BaseUnits(amount),
                approved_seq=rng.randrange(request_count),
                terms=PaymentTerms(net_due_day=due),
                early_amount=(BaseUnits(rng.randint(1, amount)) if early else None),
                early_pay_by=(rng.randint(0, due) if early else None),
                exception_granted=rng.choice((True, False)),
            )
        )
    source_balance = rng.randint(0, 600)
    ops_buffer = rng.randint(0, 30)
    snapshot = Snapshot(
        day=0,
        source=WalletState(
            address="safe",
            balance=BaseUnits(source_balance),
            buffer=BaseUnits(0),
            target=BaseUnits(0),
        ),
        operational={
            "ops": WalletState(
                address="ops",
                balance=BaseUnits(rng.randint(0, 300)),
                buffer=BaseUnits(ops_buffer),
                target=BaseUnits(ops_buffer + rng.randint(0, 100)),
            )
        },
        used_today={"pay": BaseUnits(rng.randint(0, 100)), "refill": BaseUnits(0)},
        payee_active_day=payees,
        safe_usdc=BaseUnits(source_balance),
        a_usdc=BaseUnits(0),
        pool_available=BaseUnits(0),
        supply_rate_bps=rng.randint(0, 500),
        borrow_rate_bps=0,
        debt=BaseUnits(0),
    )
    policy = PolicyView(
        pay=Limits(
            per_request=BaseUnits(rng.randint(1, 250)),
            daily=BaseUnits(rng.randint(1, 300)),
        ),
        refill=Limits(
            per_request=BaseUnits(rng.randint(0, 300)),
            daily=BaseUnits(rng.randint(0, 400)),
        ),
        cooling_seconds=0,
    )
    return requests, snapshot, policy


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
    assert all(
        snapshot.day <= item.day <= max(r.terms.net_due_day for r in requests)
        for item in result.items
    )


@settings(max_examples=1, deadline=None)
@given(seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_one_thousand_generated_cases_finish_within_sixty_seconds(
    seed: int,
) -> None:
    rng = random.Random(seed)
    scenarios = [_generated_perf_scenario(rng) for _ in range(1_000)]
    started = perf_counter()
    for requests, snapshot, policy in scenarios:
        schedule_oracle(requests, snapshot, policy)
    elapsed = perf_counter() - started

    assert len(scenarios) == 1_000
    assert elapsed < 60
