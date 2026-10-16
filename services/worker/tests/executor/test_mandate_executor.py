from __future__ import annotations

import asyncio
from typing import Any

from web3 import Web3

from treasurypilot_worker.executor.plan_loader import mandate_executor

MODULE = "0x" + "a2" * 20
PLAN_EXECUTOR = "0x" + "9b" * 20


class FakeRpc:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def call(self, method: str, params: Any) -> str:
        self.calls.append((method, params))
        words = [0] * 10  # version .. supply; the executor is word 4
        data = b"".join(w.to_bytes(32, "big") for w in words)
        data = data[: 4 * 32] + bytes(12) + bytes.fromhex(PLAN_EXECUTOR[2:]) + data[5 * 32 :]
        return "0x" + data.hex()


def test_mandate_executor_reads_the_executor_word_of_mandate() -> None:
    rpc = FakeRpc()

    assert asyncio.run(mandate_executor(rpc, MODULE)) == PLAN_EXECUTOR  # type: ignore[arg-type]
    method, (call, block) = rpc.calls[0]
    assert (method, call["to"], block) == ("eth_call", MODULE, "latest")
    assert call["data"] == "0x" + bytes(Web3.keccak(text="mandate()")[:4]).hex()
