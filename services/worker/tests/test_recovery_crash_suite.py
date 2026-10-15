"""Crash suite: the executor dies at a seeded point and the step is still paid exactly once (RCV-007).

Each iteration crashes the in-process worker (``Crash`` propagates out of ``sequence_plan`` and the
pool is dropped, so open transactions roll back as in a real process death) at one boundary around
the signer call and the DB write. The "restart" then runs the startup scan (RCV-001/002), the
executor again (the signer replays by step id) and the tracker, and the test asserts on Anvil that
exactly one PAY transfer was mined and the request is Paid. The seed comes from TP_CRASH_SEED
(default below) and is printed, so a failing schedule can be replayed.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import random
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from eth_account import Account
from web3 import Web3

from treasurypilot_worker.executor.outbox import SignerClient, StepExecution
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
anvil_url = _trk.anvil_url  # fixture: TP_TEST_ANVIL_URL or a local anvil

ITERATIONS = 20
SEED = int(os.environ.get("TP_CRASH_SEED", "169"))
# Anvil's well-known dev account 0 (_trk.SENDER); the stand-in signer signs with its key.
_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
POINTS = (
    "before_signer",  # operation row committed, signer never called
    "after_sign",  # signer reserved and signed, nothing broadcast
    "after_broadcast",  # tx mined, hash never reached the DB
    "mid_commit",  # transactions row inserted, status update not yet: rolled back
    "after_commit",  # everything committed, worker dies before returning
)


class Crash(BaseException):
    """The worker process dies here (BaseException so no ``except Exception`` can swallow it)."""


class AnvilSigner:
    """Signer stand-in: reserves by step id, signs once, replays the same raw tx on every retry."""

    def __init__(self, url: str) -> None:
        self.url, self.crash_at, self.calls = url, None, 0
        self.reserved: dict[str, tuple[str, str]] = {}  # step id -> (raw, hash)

    async def sign_and_send(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.crash_at == "before_signer":
            raise Crash
        key = request["plan"]["steps"][request["stepSeq"]]["stepId"]
        if key not in self.reserved:
            payload = request["payload"]
            signed = Account.sign_transaction(
                {
                    "to": Web3.to_checksum_address(payload["to"]),
                    "value": int(payload["value"]),
                    "gas": 21000,
                    "gasPrice": int(
                        await asyncio.to_thread(_trk._rpc, self.url, "eth_gasPrice"), 16
                    ),
                    "nonce": int(
                        await asyncio.to_thread(
                            _trk._rpc, self.url, "eth_getTransactionCount", [_trk.SENDER, "pending"]
                        ),
                        16,
                    ),
                    "chainId": _trk.CHAIN_ID,
                },
                _KEY,
            )
            self.reserved[key] = (signed.raw_transaction.to_0x_hex(), signed.hash.to_0x_hex())
        raw, tx_hash = self.reserved[key]
        if self.crash_at == "after_sign":
            raise Crash
        try:  # a replay of an already mined raw tx is rejected by the node: that is the point
            await asyncio.to_thread(_trk._rpc, self.url, "eth_sendRawTransaction", [raw])
        except AssertionError:
            pass
        if self.crash_at == "after_broadcast":
            raise Crash
        tx = await asyncio.to_thread(_trk._rpc, self.url, "eth_getTransactionByHash", [tx_hash])
        return {"txHash": tx_hash, "nonce": int(tx["nonce"], 16), "from": _trk.SENDER}


class _CrashConnection:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def execute(self, query: str, *args: Any) -> Any:
        if "SET status = 'Submitted'" in query:
            raise Crash
        return await self._inner.execute(query, *args)


class _CrashPool:
    """Dies inside the second outbox transaction, after the transactions row was inserted."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_CrashConnection]:
        async with self._inner.acquire() as connection:
            yield _CrashConnection(connection)


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


async def _sequence(url: str, signer: SignerClient, run: PlanRun, point: str | None) -> Any:
    pool = await create_worker_pool(url, min_size=1, max_size=2)
    try:
        arg = _CrashPool(pool) if point == "mid_commit" else pool
        result = await sequence_plan(arg, signer, run, _seq.FakeGate(), verifier=_seq._Passed())  # type: ignore[arg-type]
        if point == "after_commit":
            raise Crash
        return result
    finally:
        await pool.close()  # connection loss: whatever was not committed is gone


async def _iteration(url: str, anvil: str, point: str, n: int) -> None:
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
    signer = AnvilSigner(anvil)
    start = int(_trk._rpc(anvil, "eth_blockNumber"), 16)

    signer.crash_at = point
    with pytest.raises(Crash):
        await _sequence(url, signer, run, point)

    # Restart: startup scan, then the executor runs the same plan again, then the tracker.
    signer.crash_at = None
    client = _trk._client(anvil)
    pool = await create_worker_pool(url, min_size=1, max_size=2)
    try:
        await scan_in_flight(pool, client_factory=lambda _urls: client)
    finally:
        await pool.close()
    await _sequence(url, signer, run, None)
    _trk._mine(anvil, 4)
    await track_transactions(url, client_factory=lambda _urls: client)
    result = await _sequence(url, signer, run, None)

    paid = 0
    for number in range(start + 1, int(_trk._rpc(anvil, "eth_blockNumber"), 16) + 1):
        block = _trk._rpc(anvil, "eth_getBlockByNumber", [hex(number), True])
        paid += sum(
            1
            for tx in block["transactions"]
            if (tx["to"] or "").lower() == recipient and int(tx["value"], 16) == value
        )
    assert paid == 1, f"{paid} PAY transfers mined"
    assert int(_trk._rpc(anvil, "eth_getBalance", [recipient, "latest"]), 16) == value
    assert result.status == "Completed", result
    pool = await create_worker_pool(url, min_size=1, max_size=1)
    try:
        status = await pool.fetchval(
            "SELECT status FROM payment_requests WHERE id = $1", run.request_id
        )
        ops = await pool.fetch(
            "SELECT status FROM operations WHERE request_id = $1", run.request_id
        )
    finally:
        await pool.close()
    assert status == "Paid"
    assert [o["status"] for o in ops] == ["Confirmed"]


def test_executor_crash_never_double_pays(database_url: str, anvil_url: str) -> None:
    rng = random.Random(SEED)
    schedule = list(POINTS) * (ITERATIONS // len(POINTS))  # every boundary 4 times, seeded order
    rng.shuffle(schedule)
    print(f"crash suite seed={SEED} schedule={schedule}")
    for n, point in enumerate(schedule):
        try:
            asyncio.run(_iteration(database_url, anvil_url, point, n))
        except Exception as error:
            raise AssertionError(
                f"iteration {n} crash point {point} (seed {SEED}): {error}"
            ) from error
