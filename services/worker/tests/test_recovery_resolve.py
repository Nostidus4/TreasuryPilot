"""Unknown-operation resolution from chain evidence against PostgreSQL (RCV-002)."""

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
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from web3 import AsyncHTTPProvider

from treasurypilot_worker.chain.rpc import RpcClient, RpcProvider, RpcResponseError
from treasurypilot_worker.executor.outbox import execute_step
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.recovery.resolve import resolve_operation
from treasurypilot_worker.recovery.scan import scan_in_flight

_spec = importlib.util.spec_from_file_location(
    "outbox_fixtures", Path(__file__).parent / "executor" / "test_outbox_integration.py"
)
assert _spec and _spec.loader
_outbox = importlib.util.module_from_spec(_spec)
sys.modules["outbox_fixtures"] = _outbox
_spec.loader.exec_module(_outbox)

API_ROOT = _outbox.API_ROOT
CHAIN_ID = _outbox.CHAIN_ID
_TREASURY = _outbox._TREASURY
_REQUEST = _outbox._REQUEST
MODULE = bytes.fromhex("44" * 20)
SENDER = bytes.fromhex("ab" * 20)
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class FakeRpc:
    """Only the chain facts a test sets; every other read answers "nothing"."""

    def __init__(self) -> None:
        self.receipt: dict[str, str] | None = None
        self.in_mempool: bool = False
        self.step_used: bool = False
        self.next_nonce: int = 0
        self.fail: str | None = None
        self.step_used_raw: str | None = None

    async def call(self, method: str, params: Sequence[Any]) -> Any:
        if method == self.fail:
            raise RpcResponseError(-32000, "boom")
        return {
            "eth_getTransactionReceipt": self.receipt,
            "eth_getTransactionByHash": {"hash": "0x1"} if self.in_mempool else None,
            "eth_blockNumber": "0x64",
            "eth_call": self.step_used_raw
            if self.step_used_raw is not None
            else "0x" + "00" * 31 + ("01" if self.step_used else "00"),
            "eth_getTransactionCount": hex(self.next_nonce),
        }[method]


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the recovery integration tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_outbox._seed(url))
        asyncio.run(_set_module(url))
        yield url
    finally:
        command.downgrade(config, "base")


async def _set_module(url: str) -> None:
    pool = await create_worker_pool(url, min_size=1, max_size=1)
    await pool.execute("UPDATE treasuries SET module_address = $1", MODULE)
    await pool.close()


async def _run(
    url: str,
    rpc: FakeRpc,
    *,
    status: str = "Unknown",
    age: int = 60,
    tx_hash: bytes | None = None,
    nonce: int = 5,
    extra_txs: int = 0,
    reset: bool = True,
) -> tuple[Any, ...]:
    """Register an in-flight operation, resolve it, return (resolution, op, items, step_id)."""

    step_id = uuid.uuid4().bytes * 2
    operation_id = uuid.uuid4()
    pool = await create_worker_pool(url, min_size=1, max_size=2)
    try:
        if reset:  # review items are per request; start each case from a clean queue
            await pool.execute("DELETE FROM review_items WHERE request_id = $1", _REQUEST)
        await pool.execute(
            "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, kind, "
            "payload, idempotency_key, status, attempts) VALUES ($1, $2, $3, $4, $5, 'PAY', "
            "'{}'::jsonb, $6, $7::operation_status, 1)",
            operation_id,
            _TREASURY,
            uuid.uuid4(),
            _REQUEST,
            step_id,
            str(operation_id),
            status,
        )
        for i in range(1 + extra_txs):
            await pool.execute(
                "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, "
                "from_address, status, submitted_at) VALUES (gen_random_uuid(), $1, $2, $3, $4, "
                "$5, $6::transaction_status, $7)",
                operation_id,
                CHAIN_ID,
                (tx_hash if i == 0 and tx_hash else uuid.uuid4().bytes * 2),
                nonce,
                SENDER,
                status,
                NOW - timedelta(minutes=age),
            )
        resolution = await resolve_operation(pool, rpc, operation_id, now=NOW)  # type: ignore[arg-type]
        op = await pool.fetchrow(
            "SELECT status, last_error FROM operations WHERE id = $1", operation_id
        )
        items = await pool.fetch(
            "SELECT evidence_resolved, status, assigned_roles FROM review_items "
            "WHERE type = 'UNCERTAIN_TX' AND request_id = $1",
            _REQUEST,
        )
        txs = await pool.fetch(
            "SELECT status, submitted_at, last_seen_pending_at FROM transactions "
            "WHERE operation_id = $1",
            operation_id,
        )
        events = await pool.fetchval(
            "SELECT count(*) FROM domain_events WHERE entity_id = $1", operation_id
        )
        return resolution, op, items, step_id, txs, events
    finally:
        await pool.close()


def test_step_used_on_chain_confirms_without_resubmission(database_url: str) -> None:
    rpc = FakeRpc()
    rpc.step_used = True
    resolution, op, _, _, txs, events = asyncio.run(_run(database_url, rpc, extra_txs=1))
    assert (resolution, op["status"]) == ("Confirmed", "Confirmed")
    assert [t["status"] for t in txs] == ["Dropped", "Dropped"]
    assert events == 1


def test_without_a_module_the_flag_is_not_read(database_url: str) -> None:
    async def module(value: bytes | None) -> None:
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        await pool.execute("UPDATE treasuries SET module_address = $1", value)
        await pool.close()

    rpc = FakeRpc()
    rpc.step_used = True  # would confirm if it were read
    asyncio.run(module(None))
    try:
        resolution, op, *_ = asyncio.run(_run(database_url, rpc, age=2))
    finally:
        asyncio.run(module(MODULE))
    assert (resolution, op["status"]) == ("Unclear", "Unknown")


def test_rpc_errors_and_empty_answers_never_fall_through(database_url: str) -> None:
    for method in ("eth_call", "eth_getTransactionByHash", "eth_getTransactionCount"):
        rpc = FakeRpc()
        rpc.fail = method
        resolution, op, *_ = asyncio.run(_run(database_url, rpc))
        assert (resolution, op["status"]) == ("Unclear", "Unknown"), method
    rpc = FakeRpc()
    rpc.step_used_raw = "0x"  # no code at the module
    resolution, op, *_ = asyncio.run(_run(database_url, rpc))
    assert (resolution, op["status"]) == ("Unclear", "Unknown")


def test_receipt_or_mempool_is_left_to_the_tracker(database_url: str) -> None:
    rpc = FakeRpc()
    rpc.receipt = {"status": "0x1"}
    assert asyncio.run(_run(database_url, rpc))[0] == "Receipt"
    rpc = FakeRpc()
    rpc.in_mempool = True
    resolution, op, *_ = asyncio.run(_run(database_url, rpc))
    assert (resolution, op["status"]) == ("Pending", "Unknown")


def test_never_broadcast_is_replayed_with_the_same_step_id(database_url: str) -> None:
    rpc = FakeRpc()
    resolution, op, _, step_id, txs, _ = asyncio.run(
        _run(database_url, rpc, tx_hash=b"\x00" * 32, status="Pending", age=20)
    )
    # The aged Pending row restarts as Submitted so the tracker does not re-expire it at once.
    assert [(t["status"], t["submitted_at"]) for t in txs] == [("Submitted", NOW)]
    assert (resolution, op["status"], op["last_error"]) == (
        "NeverBroadcast",
        "NotSubmitted",
        "NEVER_BROADCAST",
    )

    async def replay() -> str:
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        try:
            step = _outbox._step()
            step = type(step)(
                **{
                    **step.__dict__,
                    "step_id": step_id,
                    "sign_request": {
                        **step.sign_request,
                        "plan": {"steps": [{"stepId": "0x" + step_id.hex()}]},
                    },
                }
            )
            signer = _outbox.FakeSigner()
            await execute_step(pool, signer, step)
            return str(
                await pool.fetchval("SELECT status FROM operations WHERE step_id = $1", step_id)
            )
        finally:
            await pool.close()

    assert asyncio.run(replay()) == "Submitted"


def test_young_silence_is_not_never_broadcast(database_url: str) -> None:
    assert asyncio.run(_run(database_url, FakeRpc(), age=2))[0] == "Unclear"


def test_consumed_nonce_without_evidence_escalates_after_30_minutes(database_url: str) -> None:
    rpc = FakeRpc()
    rpc.next_nonce = 6
    assert asyncio.run(_run(database_url, rpc, age=20))[0] == "Unclear"
    resolution, op, items, *_ = asyncio.run(_run(database_url, rpc, age=31))
    assert (resolution, op["status"]) == ("Escalated", "Unknown")
    assert [(i["status"], i["assigned_roles"]) for i in items] == [("Open", ["Operator", "Owner"])]
    # Later chain evidence resolves the operation and unlocks the item's acknowledgment.
    rpc.step_used = True
    items = asyncio.run(_run(database_url, rpc, reset=False))[2]
    assert items[0]["evidence_resolved"] is True


def test_scan_runs_on_worker_start_and_every_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from treasurypilot_worker.celery_app import _scan_on_start, app

    assert app.conf.beat_schedule["scan-in-flight-operations"]["schedule"].total_seconds() == 60
    sent: list[str] = []
    monkeypatch.setattr(app, "send_task", lambda name, **_: sent.append(name))

    def consumer(*names: str) -> Any:
        return SimpleNamespace(
            task_consumer=SimpleNamespace(queues=[SimpleNamespace(name=n) for n in names])
        )

    _scan_on_start(sender=consumer("ai"))
    assert sent == []  # a worker that does not consume the core queue does not send the scan
    _scan_on_start(sender=consumer("core", "ai"))
    assert sent == ["treasurypilot.recovery.scan_in_flight"]


async def _insert_op(
    pool: Any, status: str, *, nonce: int, tx_hash: bytes | None = None
) -> uuid.UUID:
    op = uuid.uuid4()
    await pool.execute(
        "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, "
        "kind, payload, idempotency_key, status, attempts) VALUES ($1, $2, $3, $4, $5, "
        "'PAY', '{}'::jsonb, $6, $7::operation_status, 1)",
        op,
        _TREASURY,
        uuid.uuid4(),
        _REQUEST,
        uuid.uuid4().bytes * 2,
        str(op),
        status,
    )
    await pool.execute(
        "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, "
        "from_address, status, submitted_at) VALUES (gen_random_uuid(), $1, $2, $3, "
        "$4, $5, $6::transaction_status, $7)",
        op,
        CHAIN_ID,
        tx_hash or uuid.uuid4().bytes * 2,
        nonce,
        SENDER,
        status,
        datetime.now(UTC) - timedelta(minutes=20),
    )
    return op


async def _statuses(pool: Any, ops: Sequence[uuid.UUID]) -> list[str]:
    return [
        str(await pool.fetchval("SELECT status FROM operations WHERE id = $1", op)) for op in ops
    ]


async def _clean(pool: Any) -> None:
    await pool.execute("DELETE FROM review_items WHERE request_id = $1", _REQUEST)
    await pool.execute(
        "UPDATE operations SET status = 'Confirmed' WHERE status IN ('Pending', 'Unknown', 'Submitted')"
    )


def test_scan_leaves_unconfirmed_in_flight_and_reports_blocked(database_url: str) -> None:
    async def scan() -> tuple[dict[str, int], list[str], list[str]]:
        pool = await create_worker_pool(database_url, min_size=1, max_size=4)
        try:
            await _clean(pool)
            ops = [await _insert_op(pool, s, nonce=7) for s in ("Pending", "Unknown")]
            rpc = FakeRpc()
            rpc.in_mempool = True  # both stay in flight, the Unknown one keeps its treasury blocked
            result = await scan_in_flight(pool, client_factory=lambda _urls: rpc)  # type: ignore[arg-type]
            blocked = [
                str(r["treasury_id"])
                for r in await pool.fetch(
                    "SELECT treasury_id FROM operations WHERE id = $1", ops[1]
                )
            ]
            return result, await _statuses(pool, ops), blocked
        finally:
            await pool.close()

    result, statuses, blocked = asyncio.run(scan())
    assert statuses == ["Pending", "Unknown"]
    assert result["scanned"] == 2 and result["blocked_treasuries"] == 1
    assert blocked == [str(_TREASURY)]


def test_scan_confirms_from_chain_evidence_and_survives_a_failing_operation(
    database_url: str,
) -> None:
    class FlakyRpc(FakeRpc):
        """Fails with a non-RPC error for one tx hash, answers step-used for the rest."""

        async def call(self, method: str, params: Sequence[Any]) -> Any:
            if method == "eth_getTransactionReceipt" and params[0] == "0x" + "ee" * 32:
                raise RuntimeError("unexpected")
            return await super().call(method, params)

    async def scan() -> list[str]:
        pool = await create_worker_pool(database_url, min_size=1, max_size=4)
        try:
            await _clean(pool)
            bad = await _insert_op(pool, "Unknown", nonce=1, tx_hash=bytes.fromhex("ee" * 32))
            good = await _insert_op(pool, "Unknown", nonce=2)
            rpc = FlakyRpc()
            rpc.step_used = True
            await scan_in_flight(pool, client_factory=lambda _urls: rpc)  # type: ignore[arg-type]
            return await _statuses(pool, [bad, good])
        finally:
            await pool.close()

    statuses = asyncio.run(scan())
    # The failing one is left as it was; the other is still confirmed from stepUsed.
    assert statuses == ["Unknown", "Confirmed"]


def test_second_concurrent_scan_returns_early(database_url: str) -> None:
    async def scan() -> tuple[dict[str, int], dict[str, int]]:
        pool = await create_worker_pool(database_url, min_size=1, max_size=4)
        try:
            await _clean(pool)
            await _insert_op(pool, "Unknown", nonce=3)
            gate = asyncio.Event()

            class SlowRpc(FakeRpc):
                async def call(self, method: str, params: Sequence[Any]) -> Any:
                    gate.set()
                    await asyncio.sleep(0.5)
                    return await super().call(method, params)

            first = asyncio.create_task(
                scan_in_flight(pool, client_factory=lambda _urls: SlowRpc())  # type: ignore[arg-type,return-value]
            )
            await gate.wait()
            second = await scan_in_flight(pool, client_factory=lambda _urls: FakeRpc())  # type: ignore[arg-type]
            return await first, second
        finally:
            await pool.close()

    first, second = asyncio.run(scan())
    assert second == {"scanned": 0, "blocked_treasuries": 0, "skipped": 1}
    assert first["scanned"] == 1 and first["skipped"] == 0


# --- Real Anvil: resolution via receipt, via module flag, via nonce (M12 section 12) ---------


def _chain(url: str, method: str, params: Sequence[Any] = ()) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
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
        pytest.skip("anvil is required for the recovery chain-evidence tests")
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
                _chain(url, "eth_chainId")
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("anvil did not start")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=5)


def _client(url: str) -> RpcClient:
    return RpcClient(
        [RpcProvider("primary", AsyncHTTPProvider(url, exception_retry_configuration=None))]
    )


def _module_returns(url: str, flag: bool) -> None:
    # Stub module: every call (stepUsed included) answers the 32-byte word `flag`.
    _chain(
        url,
        "anvil_setCode",
        ["0x" + MODULE.hex(), "0x60" + ("01" if flag else "00") + "60005260206000f3"],
    )
    for _ in range(4):  # stepUsed is read CONFIRMATIONS blocks deep
        _chain(url, "evm_mine")


def test_anvil_receipt_is_left_to_the_tracker(database_url: str, anvil_url: str) -> None:
    _module_returns(anvil_url, False)
    mined = _chain(anvil_url, "eth_sendTransaction", [{
        "from": _chain(anvil_url, "eth_accounts")[0], "to": "0x" + "22" * 20, "value": "0x1"
    }])  # fmt: skip
    resolution, op, *_ = asyncio.run(
        _run(database_url, _client(anvil_url), tx_hash=bytes.fromhex(mined[2:]))  # type: ignore[arg-type]
    )
    assert (resolution, op["status"]) == ("Receipt", "Unknown")


def test_anvil_step_used_confirms_without_resubmission(database_url: str, anvil_url: str) -> None:
    _module_returns(anvil_url, True)
    resolution, op, _, _, txs, _ = asyncio.run(_run(database_url, _client(anvil_url)))  # type: ignore[arg-type]
    assert (resolution, op["status"], [t["status"] for t in txs]) == (
        "Confirmed",
        "Confirmed",
        ["Dropped"],
    )


def test_anvil_never_broadcast_returns_to_not_submitted(database_url: str, anvil_url: str) -> None:
    _module_returns(anvil_url, False)
    resolution, op, *_ = asyncio.run(_run(database_url, _client(anvil_url), nonce=50))  # type: ignore[arg-type]
    assert (resolution, op["status"], op["last_error"]) == (
        "NeverBroadcast",
        "NotSubmitted",
        "NEVER_BROADCAST",
    )


def test_anvil_consumed_nonce_without_evidence_escalates(database_url: str, anvil_url: str) -> None:
    _module_returns(anvil_url, False)
    sender = "0x" + SENDER.hex()
    _chain(anvil_url, "anvil_setBalance", [sender, hex(10**18)])
    _chain(anvil_url, "anvil_impersonateAccount", [sender])
    _chain(
        anvil_url, "eth_sendTransaction", [{"from": sender, "to": "0x" + "22" * 20, "value": "0x1"}]
    )
    resolution, op, items, *_ = asyncio.run(
        _run(database_url, _client(anvil_url), nonce=0, age=31)  # type: ignore[arg-type]
    )
    assert (resolution, op["status"]) == ("Escalated", "Unknown")
    assert [i["status"] for i in items] == ["Open"]
