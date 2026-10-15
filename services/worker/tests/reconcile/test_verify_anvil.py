"""REC-001 on a real Anvil chain: real Multicall3 reads pinned by block hash, plus PostgreSQL.

The token and the module are tiny hand-assembled contracts (no compiler needed): the token is an
ERC-20 core (balanceOf, transfer with the standard Transfer event); the module's pay(to, amount)
sets the step/request/usedToday flags and moves the token out of itself, as Safe T would.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from web3 import AsyncHTTPProvider, Web3

from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import Action, PlanStep
from treasurypilot_worker.chain.rpc import RpcClient, RpcProvider
from treasurypilot_worker.executor.sequencer import sequence_plan
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.reconcile.verify import _TRANSFER_TOPIC, PostConditionVerifier

# Tests run in importlib mode, so the sibling module is loaded by path.
_spec = importlib.util.spec_from_file_location(
    "sequencer_fixtures", Path(__file__).parents[1] / "executor" / "test_sequencer_integration.py"
)
assert _spec and _spec.loader
_seq = importlib.util.module_from_spec(_spec)
sys.modules["sequencer_fixtures"] = _seq
_spec.loader.exec_module(_seq)
database_url = _seq.database_url

CHAIN_ID = _seq.CHAIN_ID
MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"
MULTICALL3_CODE = (
    (Path(__file__).parents[1] / "chain" / "multicall3.runtime.hex").read_text().strip()
)
REQUEST = b"\x07" * 32
PAYEE = "0x" + "77" * 20
PAY_SELECTOR = Web3.keccak(text="pay(address,uint256)")[:4].hex()


def _rpc(url: str, method: str, params: list[Any] | None = None) -> Any:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}
    ).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.load(response)
    assert "error" not in payload, payload
    return payload["result"]


@pytest.fixture(scope="module")
def anvil_url() -> Iterator[str]:
    if "TP_TEST_ANVIL_URL" in os.environ:
        yield os.environ["TP_TEST_ANVIL_URL"]
        return
    if shutil.which("anvil") is None:
        pytest.skip("anvil is required for the post-condition integration tests")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    process = subprocess.Popen(
        ["anvil", "--silent", "--port", str(port), "--chain-id", str(CHAIN_ID)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                _rpc(url, "eth_chainId")
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("anvil did not start")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=5)


def _token_code() -> str:
    """balanceOf(a) = storage[a]; transfer(to, v) moves from msg.sender and emits Transfer."""

    transfer_dest = "5b"
    transfer = (
        "602435"  # v
        "803354033355"  # storage[caller] -= v
        "80600435540160043555"  # storage[to] += v
        "600052"  # memory[0] = v
        f"60043533 7f{_TRANSFER_TOPIC[2:]} 6020 6000 a3"  # LOG3(Transfer, from, to)
        "6001600052 60206000f3"
    )
    balance = "600435 54 600052 60206000f3"
    head = "60003560e01c 63a9059cbb 14"
    prefix = (head + "6000 57").replace(" ", "")  # PUSH1 <dest> JUMPI, dest patched below
    body = balance.replace(" ", "")
    dest = (len(prefix) + len(body)) // 2
    return (head + f"60{dest:02x}57" + body + transfer_dest + transfer).replace(" ", "")


def _module_code(token: str) -> str:
    """Views return storage[selector]; pay(to, v) sets the flags and calls token.transfer."""

    flags = ""
    for signature in ("stepUsed(bytes32)", "requestPaid(bytes32)"):
        flags += f"6001 63{Web3.keccak(text=signature)[:4].hex()} 55"
    for signature in ("usedToday(uint8)", "usedToday(uint8,address)"):
        flags += f"602435 63{Web3.keccak(text=signature)[:4].hex()} 55"
    call = (
        f"7fa9059cbb{'00' * 28} 6000 52 6040 6004 6004 37"  # transfer(to, v) calldata
        f"6000 6000 6044 6000 6000 73{token[2:]} 5a f1"
    )
    view = "60003560e01c 54 600052 60206000f3"
    head = f"60003560e01c 63{PAY_SELECTOR} 14"
    dest = (len((head + "6000 57").replace(" ", "")) + len(view.replace(" ", ""))) // 2
    code = (head + f"60{dest:02x}57" + view + "5b" + flags + call).replace(" ", "")
    fail = len(code) // 2 + 5  # offset of the JUMPDEST after ISZERO PUSH1 x JUMPI STOP
    return code + f"1560{fail:02x}5700" + "5b60006000fd"  # a failed transfer reverts the pay


def _address() -> str:
    return "0x" + uuid.uuid4().bytes.hex() + "00000000"


def _deploy(url: str, balance: int) -> tuple[str, str]:
    token, module = _address(), _address()
    _rpc(url, "anvil_setCode", [MULTICALL3, MULTICALL3_CODE])
    _rpc(url, "anvil_setCode", [token, "0x" + _token_code()])
    _rpc(url, "anvil_setCode", [module, "0x" + _module_code(token)])
    _set_balance(url, token, module, balance)
    return token, module


def _set_balance(url: str, token: str, holder: str, amount: int) -> None:
    _rpc(url, "anvil_setStorageAt", [token, "0x" + holder[2:].rjust(64, "0"), f"0x{amount:064x}"])


def _send(url: str, sender: str, to: str, data: str) -> str:
    return str(
        _rpc(
            url, "eth_sendTransaction", [{"from": sender, "to": to, "data": data, "gas": "0x30d40"}]
        )
    )


def _pay_data(to: str, amount: int) -> str:
    return "0x" + PAY_SELECTOR + to[2:].rjust(64, "0") + f"{amount:064x}"


def _transfer_data(to: str, amount: int) -> str:
    return "0xa9059cbb" + to[2:].rjust(64, "0") + f"{amount:064x}"


def _client(url: str) -> RpcClient:
    provider = AsyncHTTPProvider(url, exception_retry_configuration=None)
    return RpcClient([RpcProvider("primary", provider)])


async def _verify(
    url: str, database: str, token: str, module: str, tx_hash: str, amount: int = 1000
) -> tuple[Any, Any]:
    """Run the sequencer after the real tx is mined: it verifies step 0 before sending step 1."""

    run, signer, gate = await _seq._new_run(database), _seq.FakeSigner(), _seq.FakeGate()
    plan_step = PlanStep(
        seq=0,
        step_id=run.steps[0].step_id,
        action=Action.PAY,
        from_wallet=module,
        to=PAYEE,
        asset=token,
        amount=BaseUnits(amount),
    )
    steps = {s.step_id: plan_step.model_copy(update={"step_id": s.step_id}) for s in run.steps}
    pool = await create_worker_pool(database, min_size=1, max_size=2)
    try:
        verifier = PostConditionVerifier(pool, _client(url), steps, REQUEST, module)
        await sequence_plan(pool, signer, run, gate, verifier=verifier)  # step 0 sent
        receipt = _rpc(url, "eth_getTransactionReceipt", [tx_hash])
        assert receipt["status"] == "0x1"
        await pool.execute(
            "UPDATE transactions SET status = 'Confirmed', block_number = $2, tx_hash = $3, "
            "confirmed_at = now() WHERE operation_id = (SELECT id FROM operations "
            "WHERE step_id = $1)",
            run.steps[0].step_id,
            int(receipt["blockNumber"], 16),
            bytes.fromhex(tx_hash[2:]),
        )
        await pool.execute(
            "UPDATE operations SET status = 'Confirmed' WHERE step_id = $1", run.steps[0].step_id
        )
        result = await sequence_plan(pool, signer, run, gate, verifier=verifier)
        return result, (signer, run)
    finally:
        await pool.close()


def _verification(database: str, run: Any) -> Any:
    rows = asyncio.run(
        _seq._sql(
            database,
            "SELECT v.* FROM verifications v JOIN operations o ON o.id = v.operation_id "
            "WHERE o.step_id = $1",
            run.steps[0].step_id,
        )
    )
    assert len(rows) == 1
    return rows[0]


def test_normal_pay_on_anvil_is_passed_and_unlocks_the_next_step(
    database_url: str, anvil_url: str
) -> None:
    token, module = _deploy(anvil_url, 5000)
    sender = _rpc(anvil_url, "eth_accounts")[0]
    tx = _send(anvil_url, sender, module, _pay_data(PAYEE, 1000))

    result, (signer, run) = asyncio.run(_verify(anvil_url, database_url, token, module, tx))

    row = _verification(database_url, run)
    assert json.loads(row["diffs"]) == {} and row["result"] == "PASSED"
    assert json.loads(row["expected"])[f"balance:{PAYEE}"] == 1000
    assert json.loads(row["observed"])[f"balance:{module}"] == -1000
    assert signer.calls == 2 and result.status == "Waiting"  # the next step was released


def test_concurrent_transfer_in_the_same_block_is_not_a_discrepancy(
    database_url: str, anvil_url: str
) -> None:
    token, module = _deploy(anvil_url, 5000)
    sender, other = _rpc(anvil_url, "eth_accounts")[:2]
    _set_balance(anvil_url, token, other, 400)
    _rpc(anvil_url, "evm_setAutomine", [False])
    try:
        tx = _send(anvil_url, sender, module, _pay_data(PAYEE, 1000))
        _send(anvil_url, other, token, _transfer_data(PAYEE, 400))  # inflow to our payee
        _rpc(anvil_url, "evm_mine")
    finally:
        _rpc(anvil_url, "evm_setAutomine", [True])
    receipt = _rpc(anvil_url, "eth_getTransactionReceipt", [tx])
    logs = _rpc(anvil_url, "eth_getLogs", [{"blockHash": receipt["blockHash"]}])
    assert len({log["transactionHash"] for log in logs}) == 2  # really the same block

    _, (_, run) = asyncio.run(_verify(anvil_url, database_url, token, module, tx))

    row = _verification(database_url, run)
    assert row["result"] == "PASSED"
    assert json.loads(row["observed"])[f"balance:{PAYEE}"] == 1000  # the 400 is subtracted


def test_unexpected_amount_on_anvil_is_a_discrepancy_with_review_and_breaker(
    database_url: str, anvil_url: str
) -> None:
    token, module = _deploy(anvil_url, 5000)
    sender = _rpc(anvil_url, "eth_accounts")[0]
    tx = _send(anvil_url, sender, module, _pay_data(PAYEE, 900))  # the plan says 1000

    result, (signer, run) = asyncio.run(_verify(anvil_url, database_url, token, module, tx))

    assert (result.status, result.code) == ("PartiallyCompleted", "POST_CONDITION_DISCREPANCY")
    assert signer.calls == 1  # the next step was not sent
    row = _verification(database_url, run)
    assert row["result"] == "DISCREPANCY"
    assert json.loads(row["diffs"])[f"balance:{PAYEE}"] == {"expected": 1000, "observed": 900}
    assert json.loads(row["diffs"])[f"balance:{module}"] == {"expected": -1000, "observed": -900}
    items = asyncio.run(
        _seq._sql(
            database_url,
            "SELECT type FROM review_items WHERE request_id = $1",
            run.request_id,
        )
    )
    assert [i["type"] for i in items] == ["DISCREPANCY"]
    signals = asyncio.run(
        _seq._sql(
            database_url,
            "SELECT signal_type FROM chain_safety_signals WHERE verification_id = $1",
            row["id"],
        )
    )
    assert [s["signal_type"] for s in signals] == ["CIRCUIT_BREAKER"]
