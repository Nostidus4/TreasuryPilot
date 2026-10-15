"""Gas-swap sizing (F-064, EXE-011): how much cash to swap on the test router, and its minOut.

The test router pays ``amount_in * numerator / denominator`` of its output token, which the test
setup treats as 1 unit per wei of executor gas. Every figure is an integer in base units.
"""

from __future__ import annotations

from typing import Literal

from treasurypilot_core.domain.models import FrozenModel, NonNegativeInt
from treasurypilot_core.money import BaseUnits

BPS = 10_000
GAS_SWAP_VENUE: Literal["TEST_ROUTER"] = "TEST_ROUTER"


class GasSwapInfeasible(ValueError):
    """The shortfall cannot be covered inside the swap bound."""


class GasQuote(FrozenModel):
    """A quote from the configured test source: out = in * numerator // denominator."""

    source: Literal["TEST_ROUTER"] = GAS_SWAP_VENUE
    router: str
    token_out: str
    numerator: int
    denominator: int


class GasSwap(FrozenModel):
    venue: Literal["TEST_ROUTER"] = GAS_SWAP_VENUE
    router: str
    amount_in: BaseUnits
    min_out: BaseUnits
    expected_out: BaseUnits


def swap_min_out(amount_in: int, quote: GasQuote, slippage_bps: int) -> int:
    """The lowest output the swap may return: the quote less the slippage tolerance, rounded down."""

    _check(quote, slippage_bps)
    return amount_in * quote.numerator * (BPS - slippage_bps) // (quote.denominator * BPS)


def plan_gas_swap(
    *,
    required_wei: NonNegativeInt,
    native_balance_wei: NonNegativeInt,
    quote: GasQuote,
    slippage_bps: int,
    max_amount_in: NonNegativeInt,
) -> GasSwap | None:
    """None without a gas shortage; else the smallest swap whose minOut covers the shortfall.

    Raises ``GasSwapInfeasible`` when that swap exceeds ``max_amount_in`` (the module's per-tx cap).
    """

    _check(quote, slippage_bps)
    shortfall = required_wei - native_balance_wei
    if shortfall <= 0:
        return None
    worst_rate = quote.numerator * (BPS - slippage_bps)
    amount_in = -(-shortfall * quote.denominator * BPS // worst_rate)  # ceiling division
    if amount_in > max_amount_in:
        raise GasSwapInfeasible(f"swap of {amount_in} exceeds the bound {max_amount_in}")
    return GasSwap(
        router=quote.router,
        amount_in=BaseUnits(amount_in),
        min_out=BaseUnits(swap_min_out(amount_in, quote, slippage_bps)),
        expected_out=BaseUnits(amount_in * quote.numerator // quote.denominator),
    )


def _check(quote: GasQuote, slippage_bps: int) -> None:
    if quote.numerator <= 0 or quote.denominator <= 0:
        raise GasSwapInfeasible("quote rate must be positive")
    if not 0 <= slippage_bps < BPS:
        raise GasSwapInfeasible("slippage_bps must be in [0, 10000)")
