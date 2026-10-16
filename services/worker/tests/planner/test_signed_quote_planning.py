"""EXE-L02: the planner reads a SIGNED_QUOTE quote only for the configured production adapter."""

from __future__ import annotations

import asyncio
from typing import Any

from eth_hash.auto import keccak

from treasurypilot_worker.config import Settings
from treasurypilot_worker.planner.wiring import read_test_router_quote

MODULE = "0x" + "11" * 20
ADAPTER = "0x" + "88" * 20
TOKEN_OUT = "0x" + "66" * 20


class FakeRpc:
    """``swapRouter()`` answers ``router``; ``tokenOut()`` answers TOKEN_OUT; rates answer 3/2."""

    def __init__(self, router: str) -> None:
        self.router = router

    async def call(self, method: str, params: list[Any]) -> str:
        to, data = params[0]["to"], params[0]["data"]
        if to == MODULE:
            return "0x" + "00" * 12 + self.router[2:]
        if data == "0x" + keccak(b"tokenOut()")[:4].hex():
            return "0x" + "00" * 12 + TOKEN_OUT[2:]
        return "0x" + f"{3:064x}" if "numerator" in data else "0x" + f"{2:064x}"


def _quote(router: str, settings: Settings | None) -> Any:
    return asyncio.run(read_test_router_quote(FakeRpc(router), MODULE, settings))  # type: ignore[arg-type]


def _settings(**kw: Any) -> Settings:
    return Settings(
        swap_adapter_address=ADAPTER,
        swap_quote_rate_numerator=2,
        swap_quote_rate_denominator=1,
        **kw,
    )


def test_the_configured_adapter_yields_a_signed_quote_with_the_indicative_rate() -> None:
    quote = _quote(ADAPTER, _settings())
    assert quote.source == "SIGNED_QUOTE" and quote.router.lower() == ADAPTER
    assert (quote.numerator, quote.denominator) == (2, 1)
    assert quote.token_out.lower() == TOKEN_OUT


def test_an_adapter_without_a_configured_rate_is_not_used() -> None:
    settings = Settings(swap_adapter_address=ADAPTER)
    assert _quote(ADAPTER, settings) is None


def test_any_other_router_or_no_settings_keeps_the_test_router() -> None:
    other = "0x" + "99" * 20
    for settings in (None, _settings(), Settings()):
        quote = _quote(other, settings)
        assert quote.source == "TEST_ROUTER" and quote.router.lower() == other
