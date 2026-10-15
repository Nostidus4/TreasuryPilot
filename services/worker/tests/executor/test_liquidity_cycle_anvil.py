"""EXE-014 on Anvil: the liquidity cycle supplies and withdraws on the real module and Aave mock.

Needs PostgreSQL (TP_TEST_DATABASE_URL), an Anvil with the demo stack from ``deploy-local.sh``
(TP_TEST_ANVIL_URL, ``deployments/31337.json``: ``TreasuryPilotModule``, ``MockAavePool``, the
``MockAToken``, Safe T).

Real: the migrated database; the execution cycle claiming the liquidity plan; ``plan_liquidity``
(decision, validation, attestation); ``load_plan`` / ``plan_run``; the sequencer, outbox and
tracker; on Anvil the deployed module's ``supply`` / ``withdraw``, the mock pool and aToken, and
the module's own caps and Safe T floor.
Stubbed: the signer service (the executor account sends through Anvil's unlocked
``eth_sendTransaction`` with the module's ``(stepId, amount)`` ABI, no attestation checks) and the
pre-step gate. The planning snapshot is stored, not read from the chain, except that the aToken
balance is read from Anvil; its Safe T balance is the figure the scenario needs (the on-chain
balance only has to satisfy the module's floor). The Aave fork test is out of scope (external RPC).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_worker.executor.plan_loader import load_plan, plan_run
from treasurypilot_worker.executor.sequencer import sequence_plan
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.planner.context import load_liquidity_context
from treasurypilot_worker.planner.liquidity import plan_liquidity
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
_liq = _load(
    "exe014_liquidity_fixtures", _TESTS / "planner" / "test_liquidity_cycle_integration.py"
)
_seq = _load("exe014_sequencer_fixtures", Path(__file__).with_name("test_sequencer_integration.py"))
_trk = _load("exe014_tracker_fixtures", _TESTS / "test_tracker_integration.py")
import scenario_steps as steps  # noqa: E402

SUPPLY, WITHDRAW = 4, 5


def _unavailable(reason: str) -> None:
    """Skip locally, but fail in the CI step so a missing prerequisite cannot pass silently."""
    if os.environ.get("TP_REQUIRE_INTEGRATION"):
        pytest.fail(f"EXE-014 Anvil prerequisite missing in CI: {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        _unavailable("TP_TEST_DATABASE_URL is required for the liquidity Anvil test")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(_liq.API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_liq.API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        yield url
    finally:
        # liquidity rows are evidence: 0085 refuses to downgrade over them, so reset the schema
        import asyncio

        async def reset() -> None:
            pool = await create_worker_pool(url, min_size=1, max_size=1)
            await pool.execute(
                "DROP SCHEMA IF EXISTS signer CASCADE; DROP SCHEMA public CASCADE; CREATE SCHEMA public"
            )
            await pool.close()

        asyncio.run(reset())


def _chain(anvil: str) -> steps.Chain:
    manifest = _ROOT / "deployments" / "31337.json"
    if not manifest.exists() or "TP_TEST_ANVIL_URL" not in os.environ:
        _unavailable("the liquidity Anvil test needs TP_TEST_ANVIL_URL and a deploy-local.sh run")
    return steps.Chain(
        {
            "rpc_url": anvil,
            "manifest": json.loads(manifest.read_text()),
            "transactions": [],
            "run_id": "exe014",
        }
    )


class ModuleSigner:
    """Signer stand-in: sends the planned step to the deployed module as ``(stepId, amount)``."""

    def __init__(self, c: steps.Chain) -> None:
        self.c = c
        self.calls: list[tuple[str, int]] = []

    async def sign_and_send(self, request: dict[str, Any]) -> dict[str, Any]:
        step = request["plan"]["steps"][request["stepSeq"]]
        name = {SUPPLY: "supply", WITHDRAW: "withdraw"}[step["action"]]
        receipt = self.c.send(
            steps.EXECUTOR,
            self.c.module,
            f"{name}(bytes32,uint256)",
            ["bytes32", "uint256"],
            [bytes.fromhex(step["stepId"][2:]), int(step["amount"])],
        )
        self.calls.append((name, int(step["amount"])))
        tx_hash = receipt["transactionHash"]
        nonce = steps.rpc(self.c.url, "eth_getTransactionByHash", [tx_hash])["nonce"]
        return {"txHash": tx_hash, "nonce": int(nonce, 16), "from": steps.EXECUTOR}


async def _plan_and_run(
    pool: Any, database_url: str, anvil: str, c: steps.Chain, world: Any, snapshot: Any
) -> tuple[Any, ModuleSigner]:
    """One execution cycle -> plan_liquidity -> sequencer + tracker against the chain."""

    result, _, liquidity = await _liq._cycle(pool, world)
    assert result.started and len(liquidity) == 1
    (plan_id,) = liquidity
    deps = _liq._deps(pool, database_url, world, snapshot)
    outcome = await plan_liquidity(pool, plan_id, deps)
    assert outcome is not None and outcome.status == "Attested"

    await pool.execute(
        "UPDATE chains SET rpc_urls = $2::jsonb WHERE chain_id = $1", 31337, json.dumps([anvil])
    )
    loaded = await load_plan(pool, plan_id)
    assert loaded is not None and loaded.request_id is None
    inputs = await load_liquidity_context(pool, loaded.treasury_id, executor=_liq.EXECUTOR)
    run = plan_run(loaded, inputs, {"feeCapWei": 1})

    signer, gate, client = ModuleSigner(c), _seq.FakeGate(), _trk._client(anvil)
    final = None
    for _ in range(6):  # one round to send, one to confirm, plus a final pass
        final = await sequence_plan(pool, signer, run, gate, verifier=_seq._Passed())  # type: ignore[arg-type]
        if final.status in ("Completed", "Failed", "Blocked"):
            break
        _trk._mine(anvil, 4)
        await track_transactions(database_url, client_factory=lambda _urls: client)
    assert final is not None and final.status == "Completed", final
    return plan_id, signer


@_liq.pooled
async def test_d2_surplus_is_supplied_to_aave_with_the_reserve_intact(
    pool: Any, database_url: str
) -> None:
    anvil = os.environ.get("TP_TEST_ANVIL_URL", "")
    c = _chain(anvil)
    snapshot_id = steps.rpc(anvil, "evm_snapshot", [])
    try:
        world = await _liq._seed(pool, [(1_000, 20)])  # an invoice outside the 24 h window
        cash = c.balance(c.treasury)
        a_before = c.uint(c.atoken, "balanceOf(address)", ["address"], [c.treasury])
        chain = _liq._chain(world, safe=100_000, a_token=a_before)

        plan_id, signer = await _plan_and_run(pool, database_url, anvil, c, world, chain)

        # min(idle 99_000, the mandate's 5_000 per request): capped, reserve of 1_000 kept
        assert signer.calls == [("supply", 5_000)]
        assert c.balance(c.treasury) == cash - 5_000
        assert c.balance(c.treasury) >= 1000 * 10**6  # the module's Safe T buffer holds
        assert c.uint(c.atoken, "balanceOf(address)", ["address"], [c.treasury]) == (
            a_before + 5_000
        )
        op = await pool.fetchrow(
            "SELECT request_id, kind, status FROM operations WHERE treasury_id = $1", world.treasury
        )
        assert (op["request_id"], op["kind"], op["status"]) == (None, "SUPPLY", "Confirmed")
        assert plan["request_id"] is None and plan["status"] == "Completed"
        steps.rpc(anvil, "evm_revert", [snapshot_id])


@_liq.pooled
async def test_d3_new_invoice_triggers_a_withdraw_from_aave_before_payment(
    pool: Any, database_url: str
) -> None:
    anvil = os.environ.get("TP_TEST_ANVIL_URL", "")
    c = _chain(anvil)
    snapshot_id = steps.rpc(anvil, "evm_snapshot", [])
    try:
        # Idle cash was parked in Aave earlier (the supply is real, on the module).
        c.send(
            steps.EXECUTOR,
            c.module,
            "supply(bytes32,uint256)",
            ["bytes32", "uint256"],
            [b"\x0d" * 32, 5_000],
        )
        a_parked = c.uint(c.atoken, "balanceOf(address)", ["address"], [c.treasury])
        assert a_parked >= 5_000
        # A new 2_500 invoice (due in 20 days) with only 1_000 left in Safe T: deficit 1_500,
        # withdrawn with the 5 % margin of BR-032.
        world = await _liq._seed(pool, [(2_500, 20)])
        chain = _liq._chain(world, safe=1_000, a_token=a_parked)
        cash = c.balance(c.treasury)

        plan_id, signer = await _plan_and_run(pool, database_url, anvil, c, world, chain)

        assert signer.calls == [("withdraw", 1_575)]
        assert c.balance(c.treasury) == cash + 1_575  # the cash is back in Safe T
        assert c.uint(c.atoken, "balanceOf(address)", ["address"], [c.treasury]) == (
            a_parked - 1_575
        )
        op = await pool.fetchrow(
            "SELECT request_id, kind, status FROM operations WHERE treasury_id = $1", world.treasury
        )
        assert (op["request_id"], op["kind"], op["status"]) == (None, "WITHDRAW", "Confirmed")
    finally:
        steps.rpc(anvil, "evm_revert", [snapshot_id])
