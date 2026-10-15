"""REC-001 on a real Anvil chain: real Multicall3, real compiled contracts, plus PostgreSQL.

TestUSDC, MockAavePool and MockAToken are the contracts/src ones. TreasuryPilotModule needs a Safe
and EIP-712 approvals, so the module is contracts/test/helpers/ReconcileModuleStandIn.sol: real
Solidity that holds the funds and keeps the module's step/request/usedToday read surface.
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
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from eth_abi import encode
from web3 import AsyncHTTPProvider, Web3

from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import Action, PlanStep
from treasurypilot_worker.chain.rpc import RpcClient, RpcProvider
from treasurypilot_worker.executor.sequencer import sequence_plan
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.reconcile.verify import PostConditionVerifier

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
CONTRACTS = Path(__file__).parents[4] / "contracts"
_USDC = ("src/test-assets/TestUSDC.sol", "TestUSDC")
_POOL = ("src/test-assets/MockAavePool.sol", "MockAavePool")
_MODULE = ("test/helpers/ReconcileModuleStandIn.sol", "ReconcileModuleStandIn")
_SOURCES = [source for source, _ in (_USDC, _POOL, _MODULE)]


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
        _unavailable("anvil is required for the post-condition integration tests")
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


def _unavailable(reason: str) -> None:
    """A missing tool must not silently skip these tests in CI."""

    if os.environ.get("CI"):
        pytest.fail(f"{reason} (CI is set, so this must not be skipped)")
    pytest.skip(reason)


@pytest.fixture(scope="module", autouse=True)
def _require_database() -> None:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        _unavailable("TP_TEST_DATABASE_URL is required for the post-condition integration tests")


def _artifact(source: str, name: str) -> str:
    """Creation bytecode of a contracts/ artifact, running `forge build` if it is missing."""

    path = CONTRACTS / "out" / f"{Path(source).name}" / f"{name}.json"
    if not path.exists():
        if shutil.which("forge") is None:
            _unavailable("forge is required to compile the real contracts")
        result = subprocess.run(
            ["forge", "build", *_SOURCES], cwd=CONTRACTS, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr
    return str(json.loads(path.read_text())["bytecode"]["object"])


def _data(signature: str, types: list[str], *args: Any) -> str:
    return "0x" + (Web3.keccak(text=signature)[:4] + encode(types, args)).hex()


def _receipt(url: str, tx_hash: str) -> Any:
    for _ in range(50):  # automine seals right away, but the receipt can lag the send by a moment
        if receipt := _rpc(url, "eth_getTransactionReceipt", [tx_hash]):
            return receipt
        time.sleep(0.1)
    pytest.fail(f"no receipt for {tx_hash}")


def _deploy_contract(url: str, creation: str, types: list[str], *args: Any) -> str:
    sender = _rpc(url, "eth_accounts")[0]
    code = creation + encode(types, args).hex()
    tx = _rpc(url, "eth_sendTransaction", [{"from": sender, "data": code, "gas": "0x1e8480"}])
    return str(_receipt(url, tx)["contractAddress"])


@dataclass(frozen=True)
class Chain:
    token: str
    pool: str
    atoken: str
    module: str


def _deploy(url: str, balance: int) -> Chain:
    """Real TestUSDC, MockAavePool (+ MockAToken) and the module stand-in, funded with ``balance``."""

    _rpc(url, "anvil_setCode", [MULTICALL3, MULTICALL3_CODE])
    token = _deploy_contract(url, _artifact(*_USDC), [])
    pool = _deploy_contract(url, _artifact(*_POOL), ["address"], token)
    atoken = (
        "0x" + _rpc(url, "eth_call", [{"to": pool, "data": _data("aToken()", [])}, "latest"])[-40:]
    )
    module = _deploy_contract(
        url, _artifact(*_MODULE), ["address", "address", "address"], token, pool, atoken
    )
    chain = Chain(token, pool, atoken, module)
    _mint(url, chain, module, balance)
    return chain


def _mint(url: str, chain: Chain, to: str, amount: int) -> None:
    _send(url, chain.token, _data("mint(address,uint256)", ["address", "uint256"], to, amount))


def _send(url: str, to: str, data: str, sender: str | None = None, mined: bool = True) -> str:
    sender = sender or _rpc(url, "eth_accounts")[0]
    tx = _rpc(
        url, "eth_sendTransaction", [{"from": sender, "to": to, "data": data, "gas": "0x7a120"}]
    )
    if mined:
        _receipt(url, str(tx))
    return str(tx)


def _pay_data(to: str, amount: int, step_id: bytes) -> str:
    return _data(
        "pay(address,uint256,bytes32,bytes32)",
        ["address", "uint256", "bytes32", "bytes32"],
        to,
        amount,
        step_id,
        REQUEST,
    )


def _module_data(name: str, amount: int, step_id: bytes) -> str:
    return _data(f"{name}(bytes32,uint256)", ["bytes32", "uint256"], step_id, amount)


def _client(url: str) -> RpcClient:
    provider = AsyncHTTPProvider(url, exception_retry_configuration=None)
    return RpcClient([RpcProvider("primary", provider)])


async def _verify(
    url: str, database: str, run: Any, chain: Chain, plan_step: PlanStep, tx_hash: str
) -> tuple[Any, Any]:
    """Run the sequencer after the real tx is mined: it verifies step 0 before sending step 1."""

    signer, gate = _seq.FakeSigner(), _seq.FakeGate()
    steps = {s.step_id: plan_step.model_copy(update={"step_id": s.step_id}) for s in run.steps}
    pool = await create_worker_pool(database, min_size=1, max_size=2)
    try:
        verifier = PostConditionVerifier(pool, _client(url), steps, REQUEST, chain.module)
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
        return result, signer
    finally:
        await pool.close()


def _step(run: Any, chain: Chain, action: Action, amount: int) -> PlanStep:
    to = {Action.PAY: PAYEE, Action.SUPPLY: chain.pool, Action.WITHDRAW: chain.module}[action]
    return PlanStep(
        seq=0,
        step_id=run.steps[0].step_id,
        action=action,
        from_wallet=chain.pool if action is Action.WITHDRAW else chain.module,
        to=to,
        asset=chain.token,
        amount=BaseUnits(amount),
    )


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


def _pay_on_chain(url: str, database: str, chain: Chain, sent: int, planned: int = 1000) -> Any:
    """Send pay() for ``sent`` against a plan of ``planned``; return (run, result, signer)."""

    run = asyncio.run(_seq._new_run(database))
    tx = _send(url, chain.module, _pay_data(PAYEE, sent, run.steps[0].step_id))
    plan = _step(run, chain, Action.PAY, planned)
    result, signer = asyncio.run(_verify(url, database, run, chain, plan, tx))
    return run, result, signer


def test_normal_pay_on_anvil_is_passed_and_unlocks_the_next_step(
    database_url: str, anvil_url: str
) -> None:
    chain = _deploy(anvil_url, 5000)

    run, result, signer = _pay_on_chain(anvil_url, database_url, chain, 1000)

    row = _verification(database_url, run)
    assert json.loads(row["diffs"]) == {} and row["result"] == "PASSED"
    assert json.loads(row["expected"])[f"balance:{PAYEE}"] == 1000
    assert json.loads(row["observed"])[f"balance:{chain.module}"] == -1000
    assert json.loads(row["observed"])["used_today"] == 1000
    assert signer.calls == 2 and result.status == "Waiting"  # the next step was released


def test_concurrent_transfer_in_the_same_block_is_not_a_discrepancy(
    database_url: str, anvil_url: str
) -> None:
    chain = _deploy(anvil_url, 5000)
    other = _rpc(anvil_url, "eth_accounts")[1]
    _mint(anvil_url, chain, other, 400)
    run = asyncio.run(_seq._new_run(database_url))
    # Automine off so both txs are mined together by one evm_mine; always switched back on.
    _rpc(anvil_url, "evm_setAutomine", [False])
    try:
        tx = _send(
            anvil_url, chain.module, _pay_data(PAYEE, 1000, run.steps[0].step_id), mined=False
        )
        transfer = _data("transfer(address,uint256)", ["address", "uint256"], PAYEE, 400)
        _send(anvil_url, chain.token, transfer, sender=other, mined=False)  # inflow to our payee
        _rpc(anvil_url, "evm_mine")
    finally:
        _rpc(anvil_url, "evm_setAutomine", [True])
    receipt = _rpc(anvil_url, "eth_getTransactionReceipt", [tx])
    logs = _rpc(anvil_url, "eth_getLogs", [{"blockHash": receipt["blockHash"]}])
    assert len({log["transactionHash"] for log in logs}) == 2  # really the same block

    plan = _step(run, chain, Action.PAY, 1000)
    asyncio.run(_verify(anvil_url, database_url, run, chain, plan, tx))

    row = _verification(database_url, run)
    assert row["result"] == "PASSED"
    assert json.loads(row["observed"])[f"balance:{PAYEE}"] == 1000  # the 400 is subtracted


def test_unexpected_amount_on_anvil_is_a_discrepancy_with_review_and_breaker(
    database_url: str, anvil_url: str
) -> None:
    chain = _deploy(anvil_url, 5000)

    run, result, signer = _pay_on_chain(anvil_url, database_url, chain, sent=900)  # plan: 1000

    assert (result.status, result.code) == ("PartiallyCompleted", "POST_CONDITION_DISCREPANCY")
    assert signer.calls == 1  # the next step was not sent
    row = _verification(database_url, run)
    assert row["result"] == "DISCREPANCY"
    assert json.loads(row["diffs"])[f"balance:{PAYEE}"] == {"expected": 1000, "observed": 900}
    assert json.loads(row["diffs"])[f"balance:{chain.module}"] == {
        "expected": -1000,
        "observed": -900,
    }
    items = asyncio.run(
        _seq._sql(
            database_url, "SELECT type FROM review_items WHERE request_id = $1", run.request_id
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


def _aave_step(url: str, database: str, chain: Chain, action: Action, amount: int) -> Any:
    run = asyncio.run(_seq._new_run(database))
    name = "supply" if action is Action.SUPPLY else "withdraw"
    tx = _send(url, chain.module, _module_data(name, amount, run.steps[0].step_id))
    plan = _step(run, chain, action, amount)
    asyncio.run(_verify(url, database, run, chain, plan, tx))
    return _verification(database, run)


def _atoken_balance(url: str, chain: Chain) -> int:
    data = _data("balanceOf(address)", ["address"], chain.module)
    return int(_rpc(url, "eth_call", [{"to": chain.atoken, "data": data}, "latest"]), 16)


def test_supply_on_anvil_with_atoken_rounding_is_passed(database_url: str, anvil_url: str) -> None:
    chain = _deploy(anvil_url, 5000)
    # The pool mints one aToken wei short, as Aave's index rounding can: still within tolerance.
    _send(
        anvil_url,
        chain.pool,
        _data(
            "setMintAccounting(uint128,bool,uint256,uint256)",
            ["uint128", "bool", "uint256", "uint256"],
            10**27,
            False,
            1,
            0,
        ),
    )

    row = _aave_step(anvil_url, database_url, chain, Action.SUPPLY, 1000)

    assert row["result"] == "PASSED" and json.loads(row["diffs"]) == {}
    assert _atoken_balance(anvil_url, chain) == 999
    assert json.loads(row["expected"])[f"atoken:{chain.module}"] == 1000
    assert json.loads(row["observed"])[f"atoken:{chain.module}"] == 999
    assert json.loads(row["observed"])[f"balance:{chain.module}"] == -1000


def test_withdraw_on_anvil_is_passed(database_url: str, anvil_url: str) -> None:
    chain = _deploy(anvil_url, 5000)
    _send(anvil_url, chain.module, _module_data("supply", 2000, b"\x09" * 32))  # earlier block

    row = _aave_step(anvil_url, database_url, chain, Action.WITHDRAW, 1000)

    assert row["result"] == "PASSED" and json.loads(row["diffs"]) == {}
    assert json.loads(row["observed"])[f"balance:{chain.module}"] == 1000
    assert json.loads(row["observed"])[f"atoken:{chain.module}"] == -1000
    assert _atoken_balance(anvil_url, chain) == 1000
