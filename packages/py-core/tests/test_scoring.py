from __future__ import annotations

from treasurypilot_core.domain import (
    ApprovedRequest,
    Limits,
    PaymentTerms,
    PolicyView,
    ScheduledItem,
    Snapshot,
    WalletState,
)
from treasurypilot_core.engine import binding_constraints, compare_plans, exception_values, score
from treasurypilot_core.money import BaseUnits


def _snapshot(
    *,
    balance: int = 10_000,
    buffer: int = 0,
    target: int = 0,
    source_balance: int = 10_000,
    active_day: int = 0,
) -> Snapshot:
    return Snapshot(
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
                balance=BaseUnits(balance),
                buffer=BaseUnits(buffer),
                target=BaseUnits(max(buffer, target)),
            )
        },
        used_today={"pay": BaseUnits(0), "refill": BaseUnits(0)},
        payee_active_day={"payee": active_day},
        safe_usdc=BaseUnits(source_balance),
        a_usdc=BaseUnits(0),
        pool_available=BaseUnits(0),
        supply_rate_bps=0,
        borrow_rate_bps=0,
        debt=BaseUnits(0),
    )


def _policy(
    *,
    pay_daily: int = 10_000,
    pay_per_request: int = 10_000,
    refill_daily: int = 10_000,
    refill_per_request: int = 10_000,
) -> PolicyView:
    return PolicyView(
        pay=Limits(per_request=BaseUnits(pay_per_request), daily=BaseUnits(pay_daily)),
        refill=Limits(
            per_request=BaseUnits(refill_per_request), daily=BaseUnits(refill_daily)
        ),
        cooling_seconds=0,
    )


def _request(request_id: str = "r1", *, amount: int = 100, due: int = 2) -> ApprovedRequest:
    return ApprovedRequest(
        id=request_id,
        paying_wallet="ops",
        payee="payee",
        amount=BaseUnits(amount),
        approved_seq=0,
        terms=PaymentTerms(net_due_day=due),
    )


def test_plan_score_recomputes_value_and_compare_is_deterministic() -> None:
    request = ApprovedRequest(
        id="discounted",
        paying_wallet="ops",
        payee="payee",
        amount=BaseUnits(1_000),
        approved_seq=0,
        terms=PaymentTerms(
            net_due_day=2,
            discount_bps=1_000,
            discount_deadline_day=0,
        ),
        early_amount=BaseUnits(900),
        early_pay_by=0,
    )
    early = [ScheduledItem(request_id=request.id, day=0, refill=BaseUnits(0), value=-999_999)]
    late = [ScheduledItem(request_id=request.id, day=2, refill=BaseUnits(0), value=999_999)]

    assert score(early, [request], _snapshot(), _policy()) == (0, 0, -100, 1)
    assert score(late, [request], _snapshot(), _policy()) == (0, 0, 0, 1)
    assert compare_plans(early, late, [request], _snapshot(), _policy()) == -1
    assert compare_plans(late, late, [request], _snapshot(), _policy()) == 0


def test_invalid_same_day_plan_is_penalized_and_does_not_spend_twice() -> None:
    requests = [_request("a", amount=60), _request("b", amount=60)]
    plan = [
        ScheduledItem(request_id="a", day=0, refill=BaseUnits(0), value=0),
        ScheduledItem(request_id="b", day=0, refill=BaseUnits(0), value=0),
    ]

    assert score(plan, requests, _snapshot(), _policy(pay_daily=100)) == (1, 1, 0, 1)


def test_binding_constraints_include_observed_and_allowed_values() -> None:
    request = _request(amount=100, due=0)
    plan = [ScheduledItem(request_id=request.id, day=1, refill=BaseUnits(0), value=0)]

    details = binding_constraints(
        plan,
        [request],
        _snapshot(balance=1_000, buffer=900, active_day=2),
        _policy(pay_daily=100),
    )

    observed = {(detail.name, detail.used, detail.limit) for detail in details}
    assert ("PAY_DAILY_CAP", 100, 100) in observed
    assert ("BUFFER", 900, 900) in observed
    assert ("COOLING", 1, 2) in observed
    assert ("DEADLINE", 1, 0) in observed


def test_binding_constraints_report_source_refill_bound_and_refill_daily_values() -> None:
    request = _request(amount=100)
    plan = [ScheduledItem(request_id=request.id, day=0, refill=BaseUnits(200), value=0)]

    details = binding_constraints(
        plan,
        [request],
        _snapshot(balance=0, target=100, source_balance=200),
        _policy(refill_daily=200),
    )

    observed = {(detail.name, detail.used, detail.limit) for detail in details}
    assert ("REFILL_BOUND", 200, 200) in observed
    assert ("SOURCE_CAPACITY", 200, 200) in observed
    assert ("REFILL_DAILY_CAP", 200, 200) in observed


def test_exception_value_reports_potential_value_if_cap_is_granted() -> None:
    request = ApprovedRequest(
        id="over-cap",
        paying_wallet="ops",
        payee="payee",
        amount=BaseUnits(200),
        approved_seq=0,
        terms=PaymentTerms(net_due_day=5, discount_bps=1_000, discount_deadline_day=1),
        early_amount=BaseUnits(180),
        early_pay_by=1,
    )

    values = exception_values([request], _snapshot(), _policy(pay_per_request=100))
    assert [(value.request_id, value.value) for value in values] == [("over-cap", 20)]
