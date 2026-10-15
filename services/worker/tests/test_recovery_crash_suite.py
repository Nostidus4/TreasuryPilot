"""Crash suite: the executor dies at a seeded point and the step is still paid exactly once (RCV-007).

Each iteration dies at one boundary around the signer call and the DB write, then "restarts": the
startup scan (RCV-001/002), the executor again, the tracker, the executor again. Two kinds of death:

* in process: ``Crash`` (a BaseException) leaves ``sequence_plan`` and the pool is dropped;
* real process death: a child process runs ``execute_step`` and calls ``os._exit`` at the point.

The signer stand-in keeps the real signer's order (reserve, record raw tx, broadcast) on the real
``SignerStore``, so it replays by (attestation nonce, step id) like production. The assertions do
not rely on that replay: they also pin the signer call count, ``operations.attempts`` and the
``transactions`` rows, so a regression in the worker's own guard (``execute_step`` returning early
for a non-NotSubmitted operation) fails the suite. The seed (TP_CRASH_SEED, default below) shuffles
a schedule with fixed coverage and is printed, so a failing schedule can be replayed.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import random
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_worker.executor.outbox import StepExecution, execute_step
from treasurypilot_worker.executor.sequencer import PlanRun, sequence_plan
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.recovery.scan import scan_in_flight
from treasurypilot_worker.tracker.track import track_transactions


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_TESTS = Path(__file__).parent
_seq = _load("crash_seq_fixtures", _TESTS / "executor" / "test_sequencer_integration.py")
_trk = _load("crash_trk_fixtures", _TESTS / "test_tracker_integration.py")
_sup = _load("crash_support", _TESTS / "crash_support.py")
anvil_url = _trk.anvil_url  # fixture: TP_TEST_ANVIL_URL or a local anvil

SEED = int(os.environ.get("TP_CRASH_SEED", "169"))
POINTS = (
    "before_signer",  # operation row committed, signer never called
    "after_reserve",  # nonce reserved under (attestation nonce, step id), nothing signed
    "after_sign",  # raw tx persisted by the signer, nothing broadcast
    "after_broadcast",  # tx mined, hash never reached the worker's DB
    "mid_commit",  # transactions row inserted, status update not yet: rolled back
    "after_submit_commit",  # Submitted committed; worker dies before the tracker confirms and Paid
)
RUNS_PER_POINT = 4
SUBPROCESS_POINTS = ("after_sign", "after_broadcast", "mid_commit", "after_submit_commit")
# After a crash the restarted worker reaches the signer once, except when Submitted already
# committed: then the worker's own guard must keep it away from the signer entirely.
RESTART_CALLS = {point: 1 for point in POINTS} | {"after_submit_commit": 0}
# Right after the death, before any restart: (operation status, transactions rows, mined PAYs).
POST_CRASH = {
    "before_signer": ("NotSubmitted", 0, 0),
    "after_reserve": ("NotSubmitted", 0, 0),
    "after_sign": ("NotSubmitted", 0, 0),
    "after_broadcast": ("NotSubmitted", 0, 1),
    "mid_commit": ("NotSubmitted", 0, 1),
    "after_submit_commit": ("Submitted", 1, 1),
}


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the crash suite")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(_seq.API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_seq.API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_seq._seed(url))
        yield url
    finally:
        command.downgrade(config, "base")


def _mined(anvil: str, start: int, recipient: str, value: int) -> list[dict[str, Any]]:
    found = []
    for number in range(start + 1, int(_trk._rpc(anvil, "eth_blockNumber"), 16) + 1):
        block = _trk._rpc(anvil, "eth_getBlockByNumber", [hex(number), True])
        found += [
            tx
            for tx in block["transactions"]
            if (tx["to"] or "").lower() == recipient and int(tx["value"], 16) == value
        ]
    return found


async def _db(url: str, sql: str, *args: Any) -> list[Any]:
    pool = await create_worker_pool(url, min_size=1, max_size=1)
    try:
        return list(await pool.fetch(sql, *args))
    finally:
        await pool.close()


async def _state(url: str, run: PlanRun) -> tuple[str, int, list[Any]]:
    ops = await _db(
        url, "SELECT status, attempts FROM operations WHERE request_id = $1", run.request_id
    )
    assert len(ops) == 1, ops
    txs = await _db(
        url,
        "SELECT t.tx_hash, t.nonce FROM transactions t JOIN operations o ON o.id = t.operation_id "
        "WHERE o.request_id = $1",
        run.request_id,
    )
    return ops[0]["status"], ops[0]["attempts"], txs


async def _crash_in_process(url: str, anvil: str, run: PlanRun, point: str) -> None:
    hook = _sup.Hook(point)
    pool = await create_worker_pool(url, min_size=1, max_size=2)
    try:
        async with _sup.signer_store(url) as store:
            signer = _sup.StoreSigner(store, anvil, run.request_id, hook)
            arg = _sup.CrashPool(pool, hook)
            await sequence_plan(arg, signer, run, _seq.FakeGate(), verifier=_seq._Passed())  # type: ignore[arg-type]
            hook("after_submit_commit")
    finally:
        await pool.close()  # connection loss: whatever was not committed is gone


def _crash_in_child(url: str, anvil: str, run: PlanRun, point: str) -> None:
    step = run.steps[0]
    config = {
        "point": point,
        "database_url": url,
        "anvil_url": anvil,
        "treasury_id": str(step.treasury_id),
        "request_id": str(step.request_id),
        "plan_step_id": str(step.plan_step_id),
        "step_id": step.step_id.hex(),
        "kind": step.kind,
        "chain_id": step.chain_id,
        "sign_request": step.sign_request,
    }
    child = subprocess.run(
        [sys.executable, str(_TESTS / "crash_support.py"), json.dumps(config)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert child.returncode == _sup.EXIT_CODE, (child.returncode, child.stderr[-2000:])


async def _iteration(url: str, anvil: str, point: str, n: int, *, child: bool) -> None:
    run = await _seq._new_run(url, kinds=("PAY",))
    recipient = "0x" + run.request_id.bytes[:4].hex() + "00" * 16
    value = 1000 + n
    step = run.steps[0]
    run = PlanRun(
        run.plan_id,
        run.request_id,
        (
            StepExecution(
                **{
                    **step.__dict__,
                    "sign_request": {
                        **step.sign_request,
                        "payload": {"to": recipient, "value": value},
                    },
                }
            ),
        ),
        run.valid_until,
    )
    start = int(_trk._rpc(anvil, "eth_blockNumber"), 16)

    if child:
        await asyncio.to_thread(_crash_in_child, url, anvil, run, point)
    else:
        with pytest.raises(_sup.Crash):
            await _crash_in_process(url, anvil, run, point)

    status, attempts, txs = await _state(url, run)
    expected_status, expected_txs, expected_mined = POST_CRASH[point]
    assert (status, len(txs), attempts) == (expected_status, expected_txs, 1)
    assert len(_mined(anvil, start, recipient, value)) == expected_mined

    # Restart: startup scan, the executor on the same plan, the tracker, the executor again.
    client = _trk._client(anvil)
    pool = await create_worker_pool(url, min_size=1, max_size=2)
    try:
        await scan_in_flight(pool, client_factory=lambda _urls: client)
        async with _sup.signer_store(url) as store:
            signer = _sup.StoreSigner(store, anvil, run.request_id, _sup.Hook(None))
            gate, verifier = _seq.FakeGate(), _seq._Passed()
            if point == "after_submit_commit":
                # A redelivered job calls the executor directly, past the sequencer's own check.
                redelivered = await execute_step(pool, signer, run.steps[0])
                assert redelivered.status == "Submitted", redelivered
            await sequence_plan(pool, signer, run, gate, verifier=verifier)  # type: ignore[arg-type]
            _trk._mine(anvil, 4)
            await track_transactions(url, client_factory=lambda _urls: client)
            result = await sequence_plan(pool, signer, run, gate, verifier=verifier)  # type: ignore[arg-type]
            # A duplicate job on the Confirmed operation must not reach a signer at all.
            probe = _sup.StoreSigner(store, anvil, run.request_id, _sup.Hook(None))
            await execute_step(pool, probe, run.steps[0])
            assert probe.calls == 0, "execute_step called the signer for a Confirmed operation"
    finally:
        await pool.close()

    # The worker's own idempotency, independent of the signer's replay.
    assert signer.calls == RESTART_CALLS[point], f"restart reached the signer {signer.calls}x"
    status, attempts, txs = await _state(url, run)
    mined = _mined(anvil, start, recipient, value)
    assert len(mined) == 1, f"{len(mined)} PAY transfers mined"
    assert int(_trk._rpc(anvil, "eth_getBalance", [recipient, "latest"]), 16) == value
    assert len(txs) == 1, f"{len(txs)} transactions rows"
    assert "0x" + bytes(txs[0]["tx_hash"]).hex() == mined[0]["hash"]
    assert txs[0]["nonce"] == int(mined[0]["nonce"], 16)
    assert attempts == (1 if point == "after_submit_commit" else 2), attempts
    # The signer persisted the bytes it broadcast: one reservation, its hash is the mined hash.
    uses = await _db(
        url,
        "SELECT tx_hash, transaction_nonce FROM signer.attestation_uses WHERE step_id = $1",
        step.step_id,
    )
    assert [(u["tx_hash"], int(u["transaction_nonce"])) for u in uses] == [
        (mined[0]["hash"], int(mined[0]["nonce"], 16))
    ]
    assert result.status == "Completed", result
    assert status == "Confirmed"
    paid = await _db(url, "SELECT status FROM payment_requests WHERE id = $1", run.request_id)
    assert [r["status"] for r in paid] == ["Paid"]


def test_executor_crash_never_double_pays(database_url: str, anvil_url: str) -> None:
    rng = random.Random(SEED)
    schedule = list(POINTS) * RUNS_PER_POINT  # fixed coverage; only the order is seeded
    rng.shuffle(schedule)
    print(f"crash suite seed={SEED} schedule={schedule}")
    for n, point in enumerate(schedule):
        try:
            asyncio.run(_iteration(database_url, anvil_url, point, n, child=False))
        except Exception as error:
            raise AssertionError(
                f"iteration {n} crash point {point} (seed {SEED}): {error}"
            ) from error


def test_process_death_never_double_pays(database_url: str, anvil_url: str) -> None:
    """A killed child process (``os._exit``): real connection loss, no ``finally`` blocks run."""
    for n, point in enumerate(SUBPROCESS_POINTS):
        try:
            asyncio.run(_iteration(database_url, anvil_url, point, 100 + n, child=True))
        except Exception as error:
            raise AssertionError(f"process death at {point}: {error}") from error
