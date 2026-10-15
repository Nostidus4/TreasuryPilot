"""Expected/observed computation of REC-001 against a fake Multicall3 chain."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from eth_abi import decode, encode
from web3 import Web3

from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import Action, PlanStep
from treasurypilot_worker.chain.rpc import RpcError
from treasurypilot_worker.reconcile.verify import compute, expected_effects

ASSET = "0x" + "a1" * 20
MODULE = "0x" + "b2" * 20
ATOKEN = "0x" + "c3" * 20
SAFE_T, OP, PAYEE, OTHER = ("0x" + c * 20 for c in ("01", "02", "03", "04"))
REQUEST = b"\x07" * 32
OWN_TX = "0x" + "ee" * 32
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
B = 100

_SIGS = {
    "balanceOf(address)": ("uint256", "bal"),
    "stepUsed(bytes32)": ("bool", "stepUsed"),
    "usedToday(uint8)": ("uint256", "usedToday"),
    "requestPaid(bytes32)": ("bool", "requestPaid"),
    "refilledFor(bytes32,address)": ("bool", "refilledFor"),
    "aToken()": ("address", "aToken"),
}
_BY_SELECTOR = {bytes(Web3.keccak(text=s)[:4]): s for s in _SIGS}


def step(action: Action, from_wallet: str, to: str, amount: int = 1000) -> PlanStep:
    return PlanStep(
        seq=0,
        step_id=b"\x09" * 32,
        action=action,
        from_wallet=from_wallet,
        to=to,
        asset=ASSET,
        amount=BaseUnits(amount),
    )


class FakeChain:
    """Answers eth_getBlockByNumber, Multicall3 aggregate3 and eth_getLogs from a state table."""

    def __init__(self) -> None:
        self.state: dict[tuple[Any, ...], Any] = {}  # (block, name, *args) -> value
        self.logs: dict[int, list[dict[str, Any]]] = {}
        self.down = False
        self.receipt_block: int | None = None  # block our tx receipt claims (None: B)

    def set(self, block: int, name: str, *args: Any, value: Any) -> None:
        self.state[(block, name, *(a.lower() if isinstance(a, str) else a for a in args))] = value

    def transfer(self, block: int, sender: str, receiver: str, value: int, tx: str) -> None:
        self.logs.setdefault(block, []).append(
            {
                "transactionHash": tx,
                "topics": [
                    TRANSFER,
                    "0x" + sender[2:].rjust(64, "0"),
                    "0x" + receiver[2:].rjust(64, "0"),
                ],
                "data": hex(value),
            }
        )

    @staticmethod
    def hash_of(number: int) -> str:
        return "0x" + number.to_bytes(32, "big").hex()

    async def call(self, method: str, params: list[Any], **_: Any) -> Any:
        if self.down:
            raise RpcError("down")
        if method == "eth_getBlockByNumber":
            number = int(params[0], 16)
            return {
                "hash": self.hash_of(number),
                "parentHash": self.hash_of(number - 1),
                "number": params[0],
            }
        if method == "eth_getTransactionReceipt":
            return {"blockHash": self.hash_of(self.receipt_block or B)}
        if method == "eth_getLogs":
            return self.logs.get(
                int.from_bytes(bytes.fromhex(params[0]["blockHash"][2:]), "big"), []
            )
        assert method == "eth_call"
        block = int.from_bytes(bytes.fromhex(params[1]["blockHash"][2:]), "big")
        data = bytes.fromhex(params[0]["data"][2:])[4:]
        ((calls,),) = (decode(["(address,bool,bytes)[]"], data),)
        results = []
        for to, _, calldata in calls:
            signature = _BY_SELECTOR[calldata[:4]]
            types = [t for t in signature[signature.index("(") + 1 : -1].split(",") if t]
            args = decode(types, calldata[4:])
            name = _SIGS[signature][1]
            key = (
                block,
                name,
                *(
                    "0x" + a.hex()
                    if isinstance(a, bytes)
                    else a.lower()
                    if isinstance(a, str)
                    else a
                    for a in args
                ),
            )
            if name == "bal":
                key = (block, "bal", to.lower(), args[0].lower())
            value = self.state.get(key, 0)
            if name == "aToken":
                value = ATOKEN
            output = _SIGS[signature][0]
            results.append((True, encode([output], [bool(value) if output == "bool" else value])))
        return "0x" + encode(["(bool,bytes)[]"], [results]).hex()

    async def call_with_provider(self, method: str, params: list[Any], **kw: Any) -> Any:
        return "fake", await self.call(method, params, **kw)


def pay_chain(step_id: bytes = b"\x09" * 32, payee_gets: int = 1000) -> FakeChain:
    chain = FakeChain()
    chain.set(B - 1, "bal", ASSET, OP, value=5000)
    chain.set(B, "bal", ASSET, OP, value=4000)
    chain.set(B, "bal", ASSET, PAYEE, value=payee_gets)
    chain.set(B, "usedToday", 1, value=1000)
    chain.set(B, "requestPaid", "0x" + REQUEST.hex(), value=True)
    chain.set(B, "stepUsed", "0x" + step_id.hex(), value=True)
    return chain


def run(chain: FakeChain, plan_step: PlanStep) -> Any:
    return asyncio.run(compute(chain, plan_step, REQUEST, MODULE, B, OWN_TX))  # type: ignore[arg-type]


def test_expected_effects_per_step_type() -> None:
    assert expected_effects(step(Action.PAY, OP, PAYEE)) == {
        f"balance:{OP}": -1000,
        f"balance:{PAYEE}": 1000,
        "used_today": 1000,
        "request_paid": 1,
        "step_used": 1,
    }
    refill = expected_effects(step(Action.REFILL, SAFE_T, OP))
    assert refill["refilled_for"] == 1 and refill[f"balance:{OP}"] == 1000
    assert expected_effects(step(Action.SUPPLY, SAFE_T, ATOKEN)) == {
        f"balance:{SAFE_T}": -1000,
        f"atoken:{SAFE_T}": 1000,
        "step_used": 1,
    }
    assert expected_effects(step(Action.WITHDRAW, ATOKEN, SAFE_T)) == {
        f"balance:{SAFE_T}": 1000,
        f"atoken:{SAFE_T}": -1000,
        "step_used": 1,
    }


def test_normal_pay_passes() -> None:
    result = run(pay_chain(), step(Action.PAY, OP, PAYEE))
    assert result.result == "PASSED" and result.diffs == {}
    assert result.observed[f"balance:{PAYEE}"] == 1000


def test_concurrent_inflow_in_the_same_block_is_subtracted() -> None:
    chain = pay_chain()
    chain.set(B, "bal", ASSET, OP, value=4500)  # +500 from someone else in block B
    chain.transfer(B, OTHER, OP, 500, "0x" + "dd" * 32)
    chain.transfer(B, OP, PAYEE, 1000, OWN_TX)  # our own transfer is not subtracted
    assert run(chain, step(Action.PAY, OP, PAYEE)).result == "PASSED"


def test_concurrent_outflow_and_mixed_flows_are_subtracted() -> None:
    chain = pay_chain()
    chain.set(B, "bal", ASSET, OP, value=3700)  # -500 out, +200 in from other txs
    chain.transfer(B, OP, OTHER, 500, "0x" + "dd" * 32)
    chain.transfer(B, OTHER, OP, 200, "0x" + "de" * 32)
    assert run(chain, step(Action.PAY, OP, PAYEE)).result == "PASSED"


def test_used_today_is_a_floor_so_a_day_rollover_passes() -> None:
    chain = pay_chain()
    chain.set(B - 1, "usedToday", 1, value=9000)  # yesterday's counter, reset at B
    assert run(chain, step(Action.PAY, OP, PAYEE)).result == "PASSED"
    chain.set(B, "usedToday", 1, value=999)
    assert run(chain, step(Action.PAY, OP, PAYEE)).diffs == {
        "used_today": {"expected": 1000, "observed": 999}
    }


def test_reorg_or_removed_log_raises_instead_of_a_verdict() -> None:
    chain = pay_chain()
    chain.receipt_block = B + 1  # our tx moved to another block
    with pytest.raises(RpcError, match="reorg"):
        run(chain, step(Action.PAY, OP, PAYEE))
    chain = pay_chain()
    chain.logs[B] = [{**chain_log(), "removed": True}]
    with pytest.raises(RpcError, match="reorg"):
        run(chain, step(Action.PAY, OP, PAYEE))


def chain_log() -> dict[str, Any]:
    scratch = FakeChain()
    scratch.transfer(B, OTHER, OP, 1, "0x" + "dd" * 32)
    return scratch.logs[B][0]


def test_withdraw_end_to_end_with_interest_in_bound() -> None:
    chain = FakeChain()
    chain.set(B - 1, "bal", ASSET, SAFE_T, value=0)
    chain.set(B, "bal", ASSET, SAFE_T, value=1000)
    chain.set(B - 1, "bal", ATOKEN, SAFE_T, value=10**12)
    chain.set(B, "bal", ATOKEN, SAFE_T, value=10**12 - 1000 + 500_000)  # accrued, < 1e-6 * 1e12
    chain.set(B, "stepUsed", "0x" + (b"\x09" * 32).hex(), value=True)
    withdraw = step(Action.WITHDRAW, ATOKEN, SAFE_T)
    assert run(chain, withdraw).result == "PASSED"
    chain.set(B, "bal", ATOKEN, SAFE_T, value=10**12 - 1000 + 2_000_000)
    assert run(chain, withdraw).result == "DISCREPANCY"
    chain.set(B, "bal", ATOKEN, SAFE_T, value=10**12 - 1000 - 3)  # interest never lowers it
    assert run(chain, withdraw).result == "DISCREPANCY"


def test_unexpected_balance_is_a_discrepancy_with_both_values() -> None:
    result = run(pay_chain(payee_gets=900), step(Action.PAY, OP, PAYEE))
    assert result.result == "DISCREPANCY"
    assert result.diffs == {f"balance:{PAYEE}": {"expected": 1000, "observed": 900}}


def test_supply_allows_atoken_rounding_but_not_more() -> None:
    def chain(minted: int) -> FakeChain:
        c = FakeChain()
        c.set(B - 1, "bal", ASSET, SAFE_T, value=5000)
        c.set(B, "bal", ASSET, SAFE_T, value=4000)
        c.set(B, "bal", ATOKEN, SAFE_T, value=minted)
        c.set(B, "stepUsed", "0x" + (b"\x09" * 32).hex(), value=True)
        return c

    supply = step(Action.SUPPLY, SAFE_T, ATOKEN)
    assert run(chain(1001), supply).result == "PASSED"
    assert run(chain(1010), supply).result == "DISCREPANCY"


def test_read_failure_raises_instead_of_guessing() -> None:
    chain = pay_chain()
    chain.down = True
    with pytest.raises(RpcError):
        run(chain, step(Action.PAY, OP, PAYEE))
