import asyncio
import logging
import uuid

import pytest

from treasurypilot_worker.planner.gas import GasSwapDeps, with_gas_swap


def test_shortage_with_swapping_disabled_warns_and_keeps_the_plan(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def balance(_: uuid.UUID) -> int:
        return 1

    async def quote(_: uuid.UUID, __: str) -> None:
        raise AssertionError("no quote when disabled")

    plan = object()
    deps = GasSwapDeps(balance, quote, 100, None)
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(
            with_gas_swap(deps, uuid.uuid4(), plan, required_wei=5, safe_t="0x", asset="0x")  # type: ignore[arg-type]
        )

    assert result is plan
    assert "gas_shortage_swap_disabled" in caplog.text
