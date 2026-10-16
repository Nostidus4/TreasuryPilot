"""AT-04: a gas shortage adds a TEST ROUTER swap and the plan completes on Anvil (EXE-011, F-064).

Needs PostgreSQL (TP_TEST_DATABASE_URL), an Anvil with the demo stack from ``deploy-local.sh``
(TP_TEST_ANVIL_URL, ``deployments/31337.json``) and ``forge build`` artifacts (``contracts/out``).

Real: the migrated database; the planner pipeline (gas-shortage detection, swap sizing, the
persisted ``plan_steps`` row with ``venue``, attestation, calldata encoding); the sequencer, outbox
and tracker; on Anvil the deployed ``TreasuryPilotModule`` (``configureSwap``, ``swapForGas``,
``refill``, ``pay``) and a deployed ``TestRouter``. The gas balance and the router quote are read
from the chain.
Stubbed: the signer service (the executor account sends through Anvil's unlocked ``eth_sendTransaction``;
no attestation, mandate or fee checks) and the pre-step gate. The planned world uses placeholder
module/Safe addresses, so the SWAP calldata the planner encoded (stepId, amountIn, minOut) is sent
to the deployed module, and REFILL/PAY are sent with an approval signed for the deployed module.
The TestRouter pays ERC20 only, so the executor is re-funded with native gas by the test.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_core.engine import GasQuote
from treasurypilot_worker.executor.plan_loader import load_plan, plan_run
from treasurypilot_worker.executor.sequencer import sequence_plan
from treasurypilot_worker.planner.context import load_inputs
from treasurypilot_worker.planner.gas import GasSwapDeps
from treasurypilot_worker.planner.pipeline import plan_request
from treasurypilot_worker.tracker.track import track_transactions

_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_ROOT / "infra" / "scripts"))


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_TESTS = Path(__file__).parents[1]
_pipe = _load("at04_pipeline_fixtures", _TESTS / "planner" / "test_pipeline_integration.py")
_seq = _load("at04_sequencer_fixtures", Path(__file__).with_name("test_sequencer_integration.py"))
_trk = _load("at04_tracker_fixtures", _TESTS / "test_tracker_integration.py")
import scenario_steps as steps  # noqa: E402

USDC = 10**6


def _unavailable(reason: str) -> None:
    """Skip locally, but fail in the AT-04 CI step so a missing prerequisite cannot pass silently."""
    if os.environ.get("TP_REQUIRE_INTEGRATION"):
        pytest.fail(f"AT-04 prerequisite missing in CI: {reason}")
    pytest.skip(reason)


EXECUTOR = steps.EXECUTOR


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        _unavailable("TP_TEST_DATABASE_URL is required for AT-04")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(_pipe.API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_pipe.API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        yield url
    finally:
        command.downgrade(config, "base")


def _artifact(name: str) -> str:
    path = _ROOT / "contracts" / "out" / f"{name}.sol" / f"{name}.json"
    if not path.exists():
        _unavailable(f"forge build the contracts first ({path})")
    return str(json.loads(path.read_text())["bytecode"]["object"])


def _chain(anvil: str) -> steps.Chain:
    manifest = _ROOT / "deployments" / "31337.json"
    if not manifest.exists() or "TP_TEST_ANVIL_URL" not in os.environ:
        _unavailable("AT-04 needs TP_TEST_ANVIL_URL and a deploy-local.sh deployment")
    return steps.Chain(
        {
            "rpc_url": anvil,
            "manifest": json.loads(manifest.read_text()),
            "transactions": [],
            "run_id": "at04",
        }
    )


def _receipt(c: steps.Chain, tx_hash: str) -> dict[str, Any]:
    for _ in range(50):  # Anvil may mine a moment after the send returns
        if (receipt := steps.rpc(c.url, "eth_getTransactionReceipt", [tx_hash])) is not None:
            return receipt  # type: ignore[no-any-return]
        time.sleep(0.2)
    raise AssertionError(f"{tx_hash} was never mined")


def _deploy(c: steps.Chain, bytecode: str, args: bytes = b"") -> str:
    tx = steps.rpc(
        c.url, "eth_sendTransaction", [{"from": steps.OWNER, "data": bytecode + args.hex()}]
    )
    return str(_receipt(c, tx)["contractAddress"])


class ModuleSigner:
    """Signer stand-in: the executor sends each step to the deployed module (see module docstring)."""

    def __init__(self, c: steps.Chain, approval: tuple[Any, ...], refill: int) -> None:
        self.c, self.approval, self.refill, self.calls = c, approval, refill, 0

    async def sign_and_send(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        c = self.c
        seq = request["stepSeq"]
        assert seq in (0, 1, 2), f"unexpected step {seq}"
        if seq == 0:  # SWAP: the calldata the planner and worker encoded
            tx = {"from": EXECUTOR, "to": c.module, "data": request["payload"]["data"]}
            tx_hash = steps.rpc(c.url, "eth_sendTransaction", [tx])
            receipt = _receipt(c, tx_hash)
        elif seq == 1:
            receipt = c.refill(self.approval, "at04-refill", self.refill)
        else:
            receipt = c.pay(self.approval, "at04-pay")
        assert receipt["status"] == "0x1"
        tx_hash = receipt["transactionHash"]
        nonce = steps.rpc(c.url, "eth_getTransactionByHash", [tx_hash])["nonce"]
        return {"txHash": tx_hash, "nonce": int(nonce, 16), "from": EXECUTOR}


@_pipe.pooled
async def test_gas_shortage_swap_on_the_test_router_completes_the_plan(
    pool: Any, database_url: str
) -> None:
    anvil = os.environ.get("TP_TEST_ANVIL_URL", "")
    c = _chain(anvil)
    snapshot = steps.rpc(anvil, "evm_snapshot", [])
    try:
        await _scenario(pool, database_url, anvil, c)
    finally:
        steps.rpc(anvil, "evm_revert", [snapshot])


async def _scenario(pool: Any, database_url: str, anvil: str, c: steps.Chain) -> None:
    # --- chain: TestRouter pair, configured on the real module by its owner Safe -------------
    output = _deploy(c, _artifact("TestUSDC"))
    router = _deploy(
        c,
        _artifact("TestRouter"),
        bytes.fromhex(
            "".join(f"{int(v, 16):064x}" for v in (c.token, output)) + f"{2:064x}{1:064x}"
        ),
    )
    c.send(steps.OWNER, output, "mint(address,uint256)", ["address", "uint256"], [router, 10**12])
    c.owner(
        "configureSwap(address,address,(uint128,uint128))",
        ["address", "address", "(uint128,uint128)"],
        [router, output, (100 * USDC, 150 * USDC)],
    )
    num = c.uint(router, "numerator()", [], [])
    den = c.uint(router, "denominator()", [], [])
    c.cooled()

    # --- planning: the executor's native balance is read from Anvil, below the plan's fee -----
    steps.rpc(anvil, "anvil_setBalance", [EXECUTOR, hex(500)])

    async def native_balance(_treasury: Any) -> int:
        return int(steps.rpc(anvil, "eth_getBalance", [EXECUTOR, "latest"]), 16)

    async def quote(_treasury: Any, _module: str) -> GasQuote:
        return GasQuote(router=router, token_out=output, numerator=num, denominator=den)

    world = await _pipe._seed(pool)
    _, claimed = await _pipe._cycle(pool, world)
    (plan_id,) = claimed
    deps = _pipe._deps(
        pool, database_url, world, gas_swap=GasSwapDeps(native_balance, quote, 100, 10**9)
    )
    outcome = await plan_request(pool, plan_id, deps)
    assert outcome is not None and outcome.status == "Attested"

    rows = await pool.fetch(
        "SELECT action, amount, min_out, venue, to_address FROM plan_steps "
        "WHERE plan_id = $1 ORDER BY seq",
        plan_id,
    )
    assert len(rows) == 3 and rows[0]["venue"] == "TEST_ROUTER"  # SWAP, REFILL, PAY
    assert bytes(rows[0]["to_address"]) == bytes.fromhex(router[2:])
    amount_in, min_out = int(rows[0]["amount"]), int(rows[0]["min_out"])
    assert min_out >= 2_500  # the swap's own gas is in the sizing
    assert all(r["venue"] is None for r in rows[1:])

    # --- execution: the sequencer drives SWAP -> REFILL -> PAY, the tracker confirms ----------
    await pool.execute(
        "UPDATE chains SET rpc_urls = $2::jsonb WHERE chain_id = $1", 31337, json.dumps([anvil])
    )
    loaded = await load_plan(pool, plan_id)
    assert loaded is not None
    inputs = await load_inputs(pool, loaded.plan, world.treasury, executor=_pipe.EXECUTOR)
    run = plan_run(loaded, inputs, {"feeCapWei": 1}, loaded.plan.treasury)
    assert [s.kind for s in run.steps] == ["SWAP", "REFILL", "PAY"]

    steps.rpc(anvil, "anvil_setBalance", [EXECUTOR, hex(10**20)])  # TestRouter pays no native gas
    payment = 800 * USDC
    approval = c.approval("at04", 1, payment)
    refill = c.refill_amount(payment)
    payee_before = c.balance(steps.PAYEE)
    treasury_before, out_before = (
        c.balance(c.treasury),
        c.uint(output, "balanceOf(address)", ["address"], [c.treasury]),
    )
    signer, gate, client = ModuleSigner(c, approval, refill), _seq.FakeGate(), _trk._client(anvil)
    result = None
    for _ in range(8):  # bounded: SWAP, REFILL, PAY need one round each plus a final pass
        result = await sequence_plan(pool, signer, run, gate, verifier=_seq._Passed())  # type: ignore[arg-type]
        if result.status in ("Completed", "Failed", "Blocked"):
            break
        _trk._mine(anvil, 4)
        await track_transactions(database_url, client_factory=lambda _urls: client)

    assert result.status == "Completed", result
    assert signer.calls == 3
    # SWAP on the real module + TestRouter: exact input, output at the router's rate.
    assert c.uint(output, "balanceOf(address)", ["address"], [c.treasury]) - out_before == (
        amount_in * num // den
    )
    assert c.balance(c.treasury) == treasury_before - amount_in - refill
    assert c.uint(c.module, "stepUsed(bytes32)", ["bytes32"], [run.steps[0].step_id])
    assert c.balance(steps.PAYEE) - payee_before == payment and c.request_paid(approval)

    # --- records ---------------------------------------------------------------------------
    ops = await pool.fetch(
        "SELECT kind, status FROM operations WHERE request_id = $1 ORDER BY created_at",
        run.request_id,
    )
    assert [(str(r["kind"]), str(r["status"])) for r in ops] == [
        ("SWAP", "Confirmed"),
        ("REFILL", "Confirmed"),
        ("PAY", "Confirmed"),
    ]
    request_status = await pool.fetchval(
        "SELECT status FROM payment_requests WHERE id = $1", run.request_id
    )
    assert request_status == "Paid"
    swap_step = await pool.fetchrow(
        "SELECT p.venue FROM plan_steps p JOIN operations o ON o.plan_step_id = p.id "
        "WHERE o.request_id = $1 AND o.kind = 'SWAP'",
        run.request_id,
    )
    assert swap_step is not None and swap_step["venue"] == "TEST_ROUTER"
