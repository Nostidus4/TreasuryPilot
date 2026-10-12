from __future__ import annotations

from itertools import product

import pytest

from treasurypilot_core.domain import (
    ApprovedRequest,
    Limits,
    PaymentTerms,
    PolicyView,
    RefillDecision,
    WalletState,
)
from treasurypilot_core.engine import (
    available,
    cap,
    decide_refill,
    funding_deficit,
    preferred_refill,
    refill_bound,
    shortage,
    source_capacity,
)
from treasurypilot_core.money import BaseUnits


def wallet(*, balance: int, buffer: int, target: int, address: str = "0xwallet") -> WalletState:
    return WalletState(
        address=address,
        balance=BaseUnits(balance),
        buffer=BaseUnits(buffer),
        target=BaseUnits(target),
    )


def source_wallet(*, balance: int, buffer: int = 0) -> WalletState:
    return wallet(balance=balance, buffer=buffer, target=buffer, address="0xsource")


def request(*, amount: int) -> ApprovedRequest:
    return ApprovedRequest(
        id="request-1",
        paying_wallet="0xwallet",
        payee="0xpayee",
        amount=BaseUnits(amount),
        approved_seq=1,
        terms=PaymentTerms(net_due_day=20_000),
    )


def policy(*, per_request: int, daily: int) -> PolicyView:
    return PolicyView(
        pay=Limits(per_request=BaseUnits(10_000), daily=BaseUnits(10_000)),
        refill=Limits(per_request=BaseUnits(per_request), daily=BaseUnits(daily)),
        cooling_seconds=0,
    )


def decide(
    *,
    balance: int,
    buffer: int,
    target: int,
    protected_other: int,
    amount: int,
    source_balance: int,
    source_buffer: int = 0,
    per_request: int = 10_000,
    daily: int = 10_000,
    used_today: int = 0,
    source_protected: int = 0,
) -> RefillDecision:
    return decide_refill(
        request(amount=amount),
        wallet(balance=balance, buffer=buffer, target=target),
        source_wallet(balance=source_balance, buffer=source_buffer),
        policy(per_request=per_request, daily=daily),
        BaseUnits(used_today),
        BaseUnits(protected_other),
        source_protected=BaseUnits(source_protected),
    )


def test_domain_section_3_4_golden_values() -> None:
    operational = wallet(balance=300, buffer=50, target=150)

    assert shortage(operational, BaseUnits(400), BaseUnits(100)) == BaseUnits(250)
    assert preferred_refill(operational, BaseUnits(400), BaseUnits(100)) == BaseUnits(350)
    assert refill_bound(operational, BaseUnits(400)) == BaseUnits(250)


def test_uc_02_golden_values() -> None:
    operational = wallet(balance=20, buffer=10, target=10)

    assert shortage(operational, BaseUnits(100), BaseUnits(0)) == BaseUnits(90)
    assert preferred_refill(operational, BaseUnits(100), BaseUnits(0)) == BaseUnits(90)
    assert refill_bound(operational, BaseUnits(100)) == BaseUnits(90)


def test_available_and_funding_deficit_use_the_same_protected_floor() -> None:
    funded = wallet(balance=300, buffer=50, target=150)
    underfunded = wallet(balance=120, buffer=50, target=150)

    assert available(funded, BaseUnits(100)) == BaseUnits(150)
    assert funding_deficit(funded, BaseUnits(100)) == BaseUnits(0)
    assert available(underfunded, BaseUnits(100)) == BaseUnits(0)
    assert funding_deficit(underfunded, BaseUnits(100)) == BaseUnits(30)


def test_source_capacity_has_zero_gas_term_in_m1() -> None:
    source = wallet(balance=500, buffer=50, target=100)

    assert source_capacity(source, BaseUnits(100)) == BaseUnits(350)


def test_cap_is_the_tightest_source_or_policy_limit() -> None:
    assert cap(BaseUnits(350), BaseUnits(500), BaseUnits(400)) == BaseUnits(350)
    assert cap(BaseUnits(500), BaseUnits(300), BaseUnits(400)) == BaseUnits(300)
    assert cap(BaseUnits(500), BaseUnits(400), BaseUnits(200)) == BaseUnits(200)


def test_all_calculations_return_integer_base_units() -> None:
    operational = wallet(balance=300, buffer=50, target=150)
    source = wallet(balance=500, buffer=50, target=100)
    values = (
        available(operational, BaseUnits(100)),
        funding_deficit(operational, BaseUnits(100)),
        shortage(operational, BaseUnits(400), BaseUnits(100)),
        preferred_refill(operational, BaseUnits(400), BaseUnits(100)),
        source_capacity(source, BaseUnits(100)),
        refill_bound(operational, BaseUnits(400)),
        cap(BaseUnits(350), BaseUnits(500), BaseUnits(400)),
    )

    assert all(type(value) is BaseUnits for value in values)


def test_calculations_reject_values_outside_the_money_type() -> None:
    operational = wallet(balance=1, buffer=0, target=0)

    with pytest.raises(TypeError, match="protected_other"):
        available(operational, 1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="demand"):
        shortage(operational, 1, BaseUnits(0))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="amount"):
        refill_bound(operational, 1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="source_capacity"):
        cap(1, BaseUnits(1), BaseUnits(1))  # type: ignore[arg-type]


def test_liquidity_formula_properties_over_integer_grid() -> None:
    for balance, buffer, target_delta, protected_other, demand in product(
        (0, 1, 20, 100, 1_000),
        (0, 1, 10, 50),
        (0, 1, 100),
        (0, 1, 25, 200),
        (0, 1, 75, 500),
    ):
        operational = wallet(
            balance=balance,
            buffer=buffer,
            target=buffer + target_delta,
        )
        protected = BaseUnits(protected_other)
        request_amount = BaseUnits(demand)

        usable = available(operational, protected)
        deficit = funding_deficit(operational, protected)
        minimum = shortage(operational, request_amount, protected)
        preferred = preferred_refill(operational, request_amount, protected)
        bound = refill_bound(operational, request_amount)

        assert int(usable) - int(deficit) == balance - protected_other - buffer
        assert minimum <= preferred
        assert int(preferred) - int(minimum) <= target_delta
        assert int(bound) == max(0, demand + buffer + target_delta - balance)
        assert all(value >= 0 for value in (usable, deficit, minimum, preferred, bound))


def test_cap_properties_over_integer_grid() -> None:
    for source, remaining, per_refill in product(
        (0, 1, 100),
        (0, 1, 50, 200),
        (0, 1, 75, 300),
    ):
        result = cap(BaseUnits(source), BaseUnits(remaining), BaseUnits(per_refill))

        assert result == min(source, remaining, per_refill)
        assert result <= source
        assert result <= remaining
        assert result <= per_refill


def test_refill_decision_table_no_shortage_does_not_refill_to_target() -> None:
    decision = decide(
        balance=150,
        buffer=10,
        target=100,
        protected_other=0,
        amount=100,
        source_balance=10_000,
    )

    assert decision.kind == "none"
    assert decision.amount == BaseUnits(0)
    assert decision.reason == "NO_REFILL_REQUIRED"


def test_refill_decision_table_stops_when_shortage_exceeds_contract_bound() -> None:
    decision = decide(
        balance=0,
        buffer=40,
        target=60,
        protected_other=300,
        amount=50,
        source_balance=10_000,
    )

    assert decision.kind == "stop"
    assert decision.amount == BaseUnits(0)
    assert decision.reason == "REFILL_BOUND"


@pytest.mark.parametrize("available_cap", [250, 300, 350, 10_000])
def test_refill_decision_table_uses_bounded_preferred_amount(available_cap: int) -> None:
    decision = decide(
        balance=300,
        buffer=50,
        target=150,
        protected_other=100,
        amount=400,
        source_balance=available_cap,
    )

    assert decision.kind == "preferred"
    assert decision.amount == BaseUnits(250)
    assert decision.reason == "TARGET_REACHED"


def test_refill_decision_table_uses_shortage_when_target_cannot_be_reached() -> None:
    decision = decide(
        balance=100,
        buffer=50,
        target=150,
        protected_other=0,
        amount=200,
        source_balance=150,
    )

    assert decision.kind == "shortage"
    assert decision.amount == BaseUnits(150)
    assert decision.reason == "TARGET_NOT_REACHED"


def test_remaining_daily_budget_equal_to_shortage_is_allowed() -> None:
    decision = decide(
        balance=100,
        buffer=50,
        target=150,
        protected_other=0,
        amount=200,
        source_balance=10_000,
        daily=500,
        used_today=350,
    )

    assert decision.kind == "shortage"
    assert decision.amount == BaseUnits(150)
    assert decision.reason == "TARGET_NOT_REACHED"


def test_refill_decision_table_reports_insufficient_source() -> None:
    decision = decide(
        balance=300,
        buffer=50,
        target=150,
        protected_other=100,
        amount=400,
        source_balance=200,
    )

    assert decision.kind == "stop"
    assert decision.amount == BaseUnits(0)
    assert decision.reason == "SOURCE_INSUFFICIENT"


def test_source_capacity_protects_the_source_buffer() -> None:
    decision = decide(
        balance=100,
        buffer=50,
        target=150,
        protected_other=0,
        amount=200,
        source_balance=199,
        source_buffer=50,
    )

    assert decision.kind == "stop"
    assert decision.reason == "SOURCE_INSUFFICIENT"


def test_per_request_refill_limit_is_part_of_the_cap() -> None:
    decision = decide(
        balance=100,
        buffer=50,
        target=150,
        protected_other=0,
        amount=200,
        source_balance=10_000,
        per_request=149,
    )

    assert decision.kind == "stop"
    assert decision.reason == "OVER_REFILL_PER_REQUEST"


def test_per_request_limit_reason_precedes_source_reason() -> None:
    decision = decide(
        balance=100,
        buffer=50,
        target=150,
        protected_other=0,
        amount=200,
        source_balance=5,
        per_request=10,
        daily=1_000,
    )

    assert decision.reason == "OVER_REFILL_PER_REQUEST"


def test_source_holds_reduce_source_capacity() -> None:
    decision = decide(
        balance=100,
        buffer=50,
        target=150,
        protected_other=0,
        amount=200,
        source_balance=1_000,
        source_buffer=100,
        source_protected=800,
    )

    assert decision.kind == "stop"
    assert decision.reason == "SOURCE_INSUFFICIENT"


def test_refill_target_must_be_the_request_paying_wallet() -> None:
    other_wallet = wallet(balance=100, buffer=50, target=150, address="0xother")

    decision = decide_refill(
        request(amount=200),
        other_wallet,
        source_wallet(balance=10_000),
        policy(per_request=10_000, daily=10_000),
        BaseUnits(0),
        BaseUnits(0),
        source_protected=BaseUnits(0),
    )

    assert decision == RefillDecision(
        kind="stop", amount=BaseUnits(0), reason="WRONG_REFILL_TARGET"
    )


def test_source_cannot_be_the_paying_wallet() -> None:
    paying = wallet(balance=100, buffer=50, target=150)

    decision = decide_refill(
        request(amount=200),
        paying,
        paying,
        policy(per_request=10_000, daily=10_000),
        BaseUnits(0),
        BaseUnits(0),
        source_protected=BaseUnits(0),
    )

    assert decision.reason == "WRONG_REFILL_TARGET"


def test_refill_decision_table_reports_exhausted_daily_refill_budget() -> None:
    decision = decide(
        balance=100,
        buffer=50,
        target=150,
        protected_other=0,
        amount=200,
        source_balance=10_000,
        daily=500,
        used_today=351,
    )

    assert decision.kind == "stop"
    assert decision.amount == BaseUnits(0)
    assert decision.reason == "OVER_REFILL_DAILY"


def test_daily_limit_reason_precedes_source_reason_when_both_are_insufficient() -> None:
    decision = decide(
        balance=100,
        buffer=50,
        target=150,
        protected_other=0,
        amount=200,
        source_balance=1,
        daily=100,
    )

    assert decision.reason == "OVER_REFILL_DAILY"


def test_refill_daily_budget_saturates_at_zero_when_usage_reaches_the_limit() -> None:
    at_limit = decide(
        balance=100,
        buffer=50,
        target=150,
        protected_other=0,
        amount=200,
        source_balance=10_000,
        daily=100,
        used_today=100,
    )
    over_limit = decide(
        balance=100,
        buffer=50,
        target=150,
        protected_other=0,
        amount=200,
        source_balance=10_000,
        daily=100,
        used_today=101,
    )

    assert at_limit == over_limit
    assert at_limit.reason == "OVER_REFILL_DAILY"


def test_decide_refill_rejects_values_outside_the_money_type() -> None:
    with pytest.raises(TypeError, match="used_today"):
        decide_refill(
            request(amount=1),
            wallet(balance=0, buffer=0, target=0),
            source_wallet(balance=1),
            policy(per_request=1, daily=1),
            0,  # type: ignore[arg-type]
            BaseUnits(0),
            source_protected=BaseUnits(0),
        )

    with pytest.raises(TypeError, match="protected_other"):
        decide_refill(
            request(amount=1),
            wallet(balance=0, buffer=0, target=0),
            source_wallet(balance=1),
            policy(per_request=1, daily=1),
            BaseUnits(0),
            0,  # type: ignore[arg-type]
            source_protected=BaseUnits(0),
        )

    with pytest.raises(TypeError, match="source_protected"):
        decide_refill(
            request(amount=1),
            wallet(balance=0, buffer=0, target=0),
            source_wallet(balance=1),
            policy(per_request=1, daily=1),
            BaseUnits(0),
            BaseUnits(0),
            source_protected=0,  # type: ignore[arg-type]
        )


def test_refill_decision_properties_over_integer_grid() -> None:
    for balance, buffer, target_delta, protected_other, amount, source, daily_used in product(
        (0, 1, 20, 100),
        (0, 1, 10),
        (0, 1, 100),
        (0, 1, 25),
        (0, 1, 75, 200),
        (0, 1, 100, 500),
        (0, 1, 100),
    ):
        target = buffer + target_delta
        daily = 100
        decision = decide(
            balance=balance,
            buffer=buffer,
            target=target,
            protected_other=protected_other,
            amount=amount,
            source_balance=source,
            per_request=75,
            daily=daily,
            used_today=daily_used,
        )
        bound = max(0, amount + target - balance)
        remaining_daily = max(0, daily - daily_used)
        actual_cap = min(source, remaining_daily, 75)

        assert type(decision.amount) is BaseUnits
        assert decision.amount >= 0
        assert decision.amount <= bound
        assert decision.amount <= actual_cap
        if decision.kind in {"none", "stop"}:
            assert decision.amount == 0
