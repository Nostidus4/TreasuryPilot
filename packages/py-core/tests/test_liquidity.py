from __future__ import annotations

from itertools import product

import pytest

from treasurypilot_core.domain import WalletState
from treasurypilot_core.engine import (
    available,
    cap,
    funding_deficit,
    preferred_refill,
    refill_bound,
    shortage,
    source_capacity,
)
from treasurypilot_core.money import BaseUnits


def wallet(*, balance: int, buffer: int, target: int) -> WalletState:
    return WalletState(
        address="0xwallet",
        balance=BaseUnits(balance),
        buffer=BaseUnits(buffer),
        target=BaseUnits(target),
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
