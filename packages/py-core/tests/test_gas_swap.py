"""EXE-011: the engine sizes the swap-for-gas step and computes its minOut."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from treasurypilot_core.eip712 import SWAP_IN, plan_hash
from treasurypilot_core.engine import GasQuote, GasSwapInfeasible, plan_gas_swap, swap_min_out
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import Action, ExecutionPlan, PlanStep

ROUTER = "0x" + "99" * 20
SAFE_T = "0x" + "22" * 20
ASSET = "0x" + "55" * 20


def _quote(numerator: int = 3, denominator: int = 2) -> GasQuote:
    return GasQuote(
        router=ROUTER, token_out="0x" + "88" * 20, numerator=numerator, denominator=denominator
    )


def test_no_shortage_means_no_swap() -> None:
    swap = plan_gas_swap(
        required_wei=100,
        native_balance_wei=100,
        quote=_quote(),
        slippage_bps=100,
        max_amount_in=10**9,
    )
    assert swap is None


def test_swap_covers_the_shortfall_at_the_worst_accepted_rate() -> None:
    swap = plan_gas_swap(
        required_wei=1_000,
        native_balance_wei=400,
        quote=_quote(),
        slippage_bps=100,
        max_amount_in=10**9,
    )
    assert swap is not None
    assert swap.venue == "TEST_ROUTER"
    assert swap.min_out >= 600
    assert swap.min_out == swap_min_out(int(swap.amount_in), _quote(), 100)
    assert swap.expected_out == int(swap.amount_in) * 3 // 2
    assert swap.min_out < swap.expected_out  # the slippage tolerance is applied


def test_swap_is_the_smallest_amount_that_covers_the_shortfall() -> None:
    swap = plan_gas_swap(
        required_wei=1_000,
        native_balance_wei=0,
        quote=_quote(),
        slippage_bps=100,
        max_amount_in=10**9,
    )
    assert swap is not None
    assert swap_min_out(int(swap.amount_in) - 1, _quote(), 100) < 1_000


def test_swap_over_the_bound_is_infeasible() -> None:
    with pytest.raises(GasSwapInfeasible):
        plan_gas_swap(
            required_wei=1_000,
            native_balance_wei=0,
            quote=_quote(),
            slippage_bps=0,
            max_amount_in=10,
        )


@pytest.mark.parametrize("bps", [-1, 10_000])
def test_slippage_must_be_below_one_hundred_percent(bps: int) -> None:
    with pytest.raises(GasSwapInfeasible):
        swap_min_out(100, _quote(), bps)


def test_quote_rate_must_be_positive() -> None:
    with pytest.raises(GasSwapInfeasible):
        swap_min_out(100, _quote(numerator=0), 0)


@given(
    shortfall=st.integers(1, 10**18),
    numerator=st.integers(1, 10**6),
    denominator=st.integers(1, 10**6),
    bps=st.integers(0, 9_999),
)
def test_min_out_always_covers_the_shortfall(
    shortfall: int, numerator: int, denominator: int, bps: int
) -> None:
    swap = plan_gas_swap(
        required_wei=shortfall,
        native_balance_wei=0,
        quote=_quote(numerator, denominator),
        slippage_bps=bps,
        max_amount_in=10**40,
    )
    assert swap is not None and swap.min_out >= shortfall


def test_swap_step_maps_to_swap_in_and_keeps_min_out_outside_the_plan_hash() -> None:
    step = PlanStep(
        seq=0,
        step_id=b"\x0c" * 32,
        action=Action.SWAP,
        from_wallet=SAFE_T,
        to=ROUTER,
        asset=ASSET,
        amount=BaseUnits(700),
        min_out=BaseUnits(1_000),
        venue="TEST_ROUTER",
    )
    plan = ExecutionPlan(
        request_id=b"\x01" * 32,
        treasury="0x" + "11" * 20,
        chain_id=31337,
        steps=[step],
        planner_source="DETERMINISTIC",
        evidence_ids=[],
    )
    message = plan.message()

    assert message["steps"][0]["action"] == SWAP_IN
    assert message["swaps"] == {
        "0x" + "0c" * 32: {"minOut": 1_000, "venue": "TEST_ROUTER"},
    }
    plan_hash(message["requestId"], message["treasury"], message["chainId"], message["steps"])
