"""EXE-L02 (F-065): signed swap quotes against the real ``SignedQuoteSwapAdapter`` on Anvil.

Needs an Anvil with the demo stack from ``deploy-local.sh`` (TP_TEST_ANVIL_URL,
``deployments/31337.json``) and ``forge build`` artifacts (``contracts/out``). No database.

Real: the deployed ``TreasuryPilotModule`` (``configureSwap``, ``swapForGas``), the deployed
``SignedQuoteSwapAdapter`` and ``MockSwapVenue``; the worker's ``SwapQuoteGuard`` (fetch, off-chain
verification, ``submitQuote`` staging transaction), the Python EIP-712 digest checked against the
adapter's ``quoteDigest``. Stubbed: the signer service (the executor account sends through Anvil's
unlocked ``eth_sendTransaction``) and the plan database (the guard reads a sign-request dict).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from eth_abi import encode
from eth_account import Account
from eth_hash.auto import keccak

from treasurypilot_core.engine.swap_quote import (
    QuotePolicy,
    QuoteRejected,
    quote_digest,
    submit_quote_calldata,
)
from treasurypilot_worker.executor.swap_quotes import (
    FakeQuoteSource,
    QuoteRequest,
    SwapQuoteGuard,
)

_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_ROOT / "infra" / "scripts"))
import scenario_steps as steps  # noqa: E402

USDC = 10**6
SIGNER_KEY = "0x" + "a1" * 32
FORGER_KEY = "0x" + "b2" * 32
TTL = 600


def _unavailable(reason: str) -> None:
    """Skip locally, but fail in the CI step so a missing prerequisite cannot pass silently."""
    if os.environ.get("TP_REQUIRE_INTEGRATION"):
        pytest.fail(f"swap adapter Anvil prerequisite missing in CI: {reason}")
    pytest.skip(reason)


def _artifact(name: str) -> str:
    path = _ROOT / "contracts" / "out" / f"{name}.sol" / f"{name}.json"
    if not path.exists():
        _unavailable(f"forge build the contracts first ({path})")
    return str(json.loads(path.read_text())["bytecode"]["object"])


def _receipt(url: str, tx_hash: str) -> dict[str, Any]:
    for _ in range(50):
        if (receipt := steps.rpc(url, "eth_getTransactionReceipt", [tx_hash])) is not None:
            return receipt  # type: ignore[no-any-return]
        time.sleep(0.2)
    raise AssertionError(f"{tx_hash} was never mined")


def _deploy(c: steps.Chain, name: str, args: bytes = b"") -> str:
    tx = steps.rpc(
        c.url, "eth_sendTransaction", [{"from": steps.OWNER, "data": _artifact(name) + args.hex()}]
    )
    return str(_receipt(c.url, tx)["contractAddress"])


def _send(c: steps.Chain, sender: str, to: str, data: bytes) -> dict[str, Any]:
    tx = steps.rpc(
        c.url, "eth_sendTransaction", [{"from": sender, "to": to, "data": "0x" + data.hex()}]
    )
    return _receipt(c.url, tx)


def _selector(signature: str, types: list[str], args: list[Any]) -> bytes:
    return keccak(signature.encode())[:4] + encode(types, args)


@pytest.fixture
def chain() -> Any:
    anvil = os.environ.get("TP_TEST_ANVIL_URL")
    manifest = _ROOT / "deployments" / "31337.json"
    if not anvil or not manifest.exists():
        _unavailable("needs TP_TEST_ANVIL_URL and a deploy-local.sh deployment")
    assert anvil
    c = steps.Chain(
        {
            "rpc_url": anvil,
            "manifest": json.loads(manifest.read_text()),
            "transactions": [],
            "run_id": "exe-l02",
        }
    )
    snapshot = steps.rpc(anvil, "evm_snapshot", [])
    try:
        yield c
    finally:
        steps.rpc(anvil, "evm_revert", [snapshot])


class World:
    """The adapter, its venue and the guard wired to the demo module."""

    def __init__(self, c: steps.Chain, signer_key: str = SIGNER_KEY) -> None:
        self.c = c
        self.signer = Account.from_key(SIGNER_KEY).address
        self.output = _deploy(c, "TestUSDC")
        self.venue = _deploy(
            c, "MockSwapVenue", encode(["address", "address"], [c.token, self.output])
        )
        c.send(
            steps.OWNER,
            self.output,
            "mint(address,uint256)",
            ["address", "uint256"],
            [self.venue, 10**12],
        )
        self.adapter = _deploy(
            c,
            "SignedQuoteSwapAdapter",
            encode(
                ["address", "address", "uint64", "address[]", "address[]"],
                [c.module, self.output, TTL, [self.signer], [self.venue]],
            ),
        )
        c.owner(
            "configureSwap(address,address,(uint128,uint128))",
            ["address", "address", "(uint128,uint128)"],
            [self.adapter, self.output, (100 * USDC, 150 * USDC)],
        )
        c.cooled()  # the new swap router is Active only after the cooling period
        self.policy = QuotePolicy(
            chain_id=31337,
            adapter=self.adapter,
            safe_t=c.treasury,
            token_in=c.token,
            token_out=self.output,
            signers=(self.signer,),
            venues=(self.venue,),
            max_ttl_seconds=TTL,
        )
        self.source = FakeQuoteSource(
            signer_key,
            self.venue,
            lambda request: _selector(
                "swapExact(uint256,address)",
                ["uint256", "address"],
                [request.amount_in, self.adapter],
            ),
            now=c.now,
            ttl_seconds=300,
        )

    async def stage(self, to: str, data: bytes) -> None:
        receipt = _send(self.c, steps.OUTSIDER, to, data)  # submitQuote is permissionless
        assert receipt["status"] == "0x1"

    def guard(self) -> SwapQuoteGuard:
        return SwapQuoteGuard(self.source, self.policy, self.stage, now=self.c.now)

    def step(self, step_id: bytes, amount_in: int, min_out: int) -> Any:
        sid = "0x" + step_id.hex()
        plan = {
            "steps": [{"stepId": sid, "amount": amount_in}],
            "swaps": {sid: {"minOut": min_out, "venue": "SIGNED_QUOTE"}},
        }

        class _Step:
            kind = "SWAP"
            sign_request = {"plan": plan, "stepSeq": 0}

        return _Step()

    def swap_for_gas(self, step_id: bytes, amount_in: int, min_out: int) -> dict[str, Any]:
        data = _selector(
            "swapForGas(bytes32,uint256,uint256)",
            ["bytes32", "uint256", "uint256"],
            [step_id, amount_in, min_out],
        )
        return _send(self.c, steps.EXECUTOR, self.c.module, data)

    def swap_reverts(self, step_id: bytes, amount_in: int, min_out: int) -> bool:
        data = _selector(
            "swapForGas(bytes32,uint256,uint256)",
            ["bytes32", "uint256", "uint256"],
            [step_id, amount_in, min_out],
        )
        try:
            steps.rpc(
                self.c.url,
                "eth_call",
                [
                    {"from": steps.EXECUTOR, "to": self.c.module, "data": "0x" + data.hex()},
                    "latest",
                ],
            )
        except RuntimeError:
            return True
        return False


def test_verified_quote_is_staged_and_the_swap_completes_through_the_module(
    chain: steps.Chain,
) -> None:
    w, c = World(chain), chain
    step_id, amount_in, min_out = keccak(b"exe-l02-happy"), 10 * USDC, 15 * USDC
    cash = c.balance(c.treasury)
    out_before = c.uint(w.output, "balanceOf(address)", ["address"], [c.treasury])

    asyncio.run(w.guard()(w.step(step_id, amount_in, min_out)))
    receipt = w.swap_for_gas(step_id, amount_in, min_out)

    assert receipt["status"] == "0x1"
    assert c.balance(c.treasury) == cash - amount_in  # exact input, integer base units
    received = c.uint(w.output, "balanceOf(address)", ["address"], [c.treasury]) - out_before
    assert received == amount_in * 2  # the venue's rate; the signed floor is the plan's minOut
    assert c.uint(c.module, "stepUsed(bytes32)", ["bytes32"], [step_id])


def test_python_digest_equals_the_adapters_quote_digest(chain: steps.Chain) -> None:
    w = World(chain)
    fetched = asyncio.run(w.source.fetch(_request(w, 5 * USDC, 9 * USDC)))
    q = fetched.quote
    onchain = chain.call(
        w.adapter,
        "quoteDigest((address,address,address,address,uint256,uint256,address,bytes32,uint64,uint256))",
        ["(address,address,address,address,uint256,uint256,address,bytes32,uint64,uint256)"],
        [
            (
                q.taker, q.recipient, q.token_in, q.token_out, q.amount_in, q.min_amount_out,
                q.venue, bytes.fromhex(q.route_hash[2:]), q.expiry, q.nonce,
            )
        ],
    )  # fmt: skip
    assert onchain == quote_digest(q, chain_id=31337, adapter=w.adapter)


def _request(w: World, amount_in: int, min_out: int) -> Any:
    return QuoteRequest(31337, w.adapter, w.c.treasury, w.c.token, w.output, amount_in, min_out)


def test_a_forged_quote_stops_the_plan_and_nothing_is_staged_or_swapped(chain: steps.Chain) -> None:
    w, c = World(chain), chain
    w.source = FakeQuoteSource(  # a key the adapter does not know
        FORGER_KEY, w.venue, w.source._route_for, now=c.now, ttl_seconds=300
    )
    step_id, amount_in = keccak(b"exe-l02-forged"), 10 * USDC
    cash = c.balance(c.treasury)

    with pytest.raises(QuoteRejected) as raised:
        asyncio.run(w.guard()(w.step(step_id, amount_in, 15 * USDC)))

    assert raised.value.code == "SWAP_QUOTE_FORGED"
    assert w.swap_reverts(step_id, amount_in, 15 * USDC)  # no staged quote: the chain refuses too
    assert c.balance(c.treasury) == cash

    # The same forged quote submitted straight to the adapter is refused on chain as well.
    forged = asyncio.run(w.source.fetch(_request(w, amount_in, 15 * USDC)))
    data = submit_quote_calldata(forged.quote, forged.route, forged.signature)
    with pytest.raises(RuntimeError, match=keccak(b"SignerNotAllowed()")[:4].hex()):
        steps.rpc(
            c.url,
            "eth_call",
            [{"from": steps.OUTSIDER, "to": w.adapter, "data": "0x" + data.hex()}, "latest"],
        )


def test_a_stale_quote_is_stopped_off_chain_and_reverts_on_chain(chain: steps.Chain) -> None:
    w, c = World(chain), chain
    step_id, amount_in, min_out = keccak(b"exe-l02-stale"), 10 * USDC, 15 * USDC

    # Staged while valid, then it ages out before the executor swaps: the adapter reverts.
    asyncio.run(w.guard()(w.step(step_id, amount_in, min_out)))
    c.warp(301)
    assert w.swap_reverts(step_id, amount_in, min_out)

    # A quote that is already stale when the worker sees it never reaches the chain.
    w.source = FakeQuoteSource(SIGNER_KEY, w.venue, w.source._route_for, now=c.now, ttl_seconds=-5)
    with pytest.raises(QuoteRejected) as raised:
        asyncio.run(w.guard()(w.step(keccak(b"exe-l02-stale-2"), amount_in, min_out)))
    assert raised.value.code == "SWAP_QUOTE_EXPIRED"


def test_quote_for_another_amount_cannot_be_used(chain: steps.Chain) -> None:
    w = World(chain)
    step_id = keccak(b"exe-l02-amount")
    asyncio.run(w.guard()(w.step(step_id, 10 * USDC, 15 * USDC)))
    assert w.swap_reverts(step_id, 11 * USDC, 15 * USDC)  # staged quote is for 10, not 11
    assert not w.swap_reverts(step_id, 10 * USDC, 15 * USDC)
