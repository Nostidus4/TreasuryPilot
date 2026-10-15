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
from treasurypilot_worker.executor.outbox import SignerRefused, execute_step
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.recovery.resolve import (
    _REQUEST_PAID,
    _STEP_USED,
    TRACE_WINDOW,
    resolve_operation,
)
from treasurypilot_worker.recovery.scan import scan_in_flight
from treasurypilot_worker.tracker.track import track_transactions
from treasurypilot_worker.trigger.cycles import _read_gates

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
        self.secondary_receipt: dict[str, str] | None = None
        self.receipts: dict[str, dict[str, str]] = {}  # by tx hash, wins over `receipt`
        self.in_mempool: bool = False
        self.step_used: bool = False
        self.request_paid: bool = False
        self.next_nonce: int = 0
        self.nonce_block: int = 90  # the block whose transaction used the nonce
        self.block_txs: list[dict[str, str]] = []
        self.head: int = 100
        self.fail: str | None = None
        self.step_used_raw: str | None = None

    async def receipt_anywhere(self, tx_hash: str) -> Any:
        if self.fail == "secondary":
            raise RpcResponseError(-32000, "boom")
        return await self.call("eth_getTransactionReceipt", [tx_hash]) or self.secondary_receipt

    async def call(self, method: str, params: Sequence[Any]) -> Any:
        if method == self.fail:
            raise RpcResponseError(-32000, "boom")
        if method == "eth_getTransactionReceipt":
            return self.receipts.get(params[0], self.receipt)
        if method == "eth_getTransactionCount":  # historical counts rise at `nonce_block`
            at = params[1]
            return hex(self.next_nonce if at == "latest" or int(at, 16) >= self.nonce_block else 0)
        if method == "eth_call":
            selector = params[0]["data"][:10]
            flag = self.request_paid if selector == "0x" + _REQUEST_PAID.hex() else self.step_used
            return self.step_used_raw or "0x" + "00" * 31 + ("01" if flag else "00")
        return {
            "eth_getTransactionByHash": {"hash": "0x1"} if self.in_mempool else None,
            "eth_blockNumber": hex(self.head),
            "eth_getBlockByNumber": {"transactions": self.block_txs},
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
    step_id: bytes | None = None,
    module: bytes | None = MODULE,
    request_id: bytes | None = None,
    sender: bytes = SENDER,
) -> tuple[Any, ...]:
    """Register an in-flight operation, resolve it, return (resolution, op, items, step_id)."""

    step_id = step_id or uuid.uuid4().bytes * 2
    operation_id = uuid.uuid4()
    pool = await create_worker_pool(url, min_size=1, max_size=2)
    try:
        await pool.execute("UPDATE treasuries SET module_address = $1", module)
        await pool.execute("UPDATE payment_requests SET onchain_request_id = $1", request_id)
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
                sender,
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
    rpc = FakeRpc()
    rpc.step_used = True  # would confirm if it were read
    resolution, op, *_ = asyncio.run(_run(database_url, rpc, age=2, module=None))
    assert (resolution, op["status"]) == ("Unclear", "Unknown")


def test_request_paid_on_chain_confirms_a_pay_step(database_url: str) -> None:
    rpc = FakeRpc()
    rpc.request_paid = True  # stepUsed is false: a replacement paid the request under another step
    resolution, op, _, _, txs, _ = asyncio.run(_run(database_url, rpc, request_id=b"\x07" * 32))
    assert (resolution, op["status"], [t["status"] for t in txs]) == (
        "Confirmed",
        "Confirmed",
        ["Dropped"],
    )
    # Without an on-chain request id there is nothing to look up: the flag is not read.
    resolution, op, *_ = asyncio.run(_run(database_url, rpc, age=2))
    assert (resolution, op["status"]) == ("Unclear", "Unknown")


def test_secondary_provider_receipt_is_left_to_the_tracker(database_url: str) -> None:
    rpc = FakeRpc()
    rpc.secondary_receipt = {"status": "0x0"}  # the primary lags; a reverted receipt still counts
    resolution, op, *_ = asyncio.run(_run(database_url, rpc, age=31))
    assert (resolution, op["status"]) == ("Receipt", "Unknown")
    # A secondary that cannot answer is not "no receipt": nothing is decided on the silence.
    rpc = FakeRpc()
    rpc.fail = "secondary"
    resolution, op, *_ = asyncio.run(_run(database_url, rpc, age=31))
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


async def _replay(url: str, step_id: bytes, refuse: str | None = None) -> str:
    """Run the executor again for `step_id`; returns the operation status afterwards."""

    pool = await create_worker_pool(url, min_size=1, max_size=1)
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
        if refuse:
            signer.fail_with = SignerRefused(refuse)
        try:
            await execute_step(pool, signer, step)
        except SignerRefused:
            pass
        return str(await pool.fetchval("SELECT status FROM operations WHERE step_id = $1", step_id))
    finally:
        await pool.close()


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

    assert asyncio.run(_replay(database_url, step_id)) == "Submitted"


def test_replay_refused_as_attestation_expired_ends_abandoned(database_url: str) -> None:
    resolution, _, _, step_id, *_ = asyncio.run(
        _run(database_url, FakeRpc(), tx_hash=b"\x01" * 32, status="Pending", age=20)
    )
    assert resolution == "NeverBroadcast"
    assert asyncio.run(_replay(database_url, step_id, refuse="ATTESTATION_EXPIRED")) == "Abandoned"


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


def _consumed(status: str, *, nonce_block: int = 90) -> FakeRpc:
    """The executor nonce 5 was used at `nonce_block` by a transaction that is not ours."""

    rpc = FakeRpc()
    rpc.next_nonce = 6
    rpc.nonce_block = nonce_block
    rpc.block_txs = [
        {"from": "0x" + "cd" * 20, "nonce": "0x5", "hash": "0x" + "ee" * 32},  # other sender
        {"from": "0x" + SENDER.hex(), "nonce": "0x5", "hash": "0x" + "ff" * 32},
    ]
    rpc.receipts["0x" + "ff" * 32] = {"status": status}
    return rpc


def test_consumed_nonce_traced_to_a_reverted_transaction_is_reverted(database_url: str) -> None:
    resolution, op, items, _, txs, events = asyncio.run(
        _run(database_url, _consumed("0x0"), age=20)
    )
    assert (resolution, op["status"]) == ("Reverted", "Reverted")
    assert op["last_error"] == "NONCE_CONSUMED_BY 0x" + "ff" * 32
    assert [t["status"] for t in txs] == ["Dropped"] and events == 1


def test_consumed_nonce_traced_to_an_unrelated_success_is_abandoned(database_url: str) -> None:
    resolution, op, *_ = asyncio.run(_run(database_url, _consumed("0x1"), age=20))
    assert (resolution, op["status"]) == ("Abandoned", "Abandoned")


def test_nonce_trace_is_bounded_and_waits_for_confirmations(database_url: str) -> None:
    # Used in the last two blocks: not final yet, so not classified.
    rpc = _consumed("0x1", nonce_block=99)
    assert asyncio.run(_run(database_url, rpc, age=20))[0] == "Unclear"
    # Older than the window: left to the 30 minute escalation, not guessed.
    rpc = _consumed("0x1", nonce_block=1)
    rpc.head = TRACE_WINDOW + 50
    assert asyncio.run(_run(database_url, rpc, age=31))[0] == "Escalated"
    # The block does not contain the transaction (inconsistent provider): never guessed.
    rpc = _consumed("0x1")
    rpc.block_txs = []
    assert asyncio.run(_run(database_url, rpc, age=31))[0] == "Escalated"


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


def _provider(url: str) -> RpcProvider:
    return RpcProvider("primary", AsyncHTTPProvider(url, exception_retry_configuration=None))


def _client(url: str) -> RpcClient:
    return RpcClient([_provider(url)])


def _word(value: bytes) -> str:
    return "7f" + value.ljust(32, b"\0").hex()


def _deploy_module(
    url: str, *, step_id: bytes | None = None, request: bytes | None = None
) -> bytes:
    """Deploy a tiny contract: stepUsed(id) is true only for `step_id`, requestPaid(id) only for
    `request`; any other selector or id reads false. Proves the selectors and the id encoding."""

    def flag(selector: bytes, key: bytes | None) -> str:
        if key is None:
            return "6000"  # PUSH1 0
        # CALLDATALOAD(0)>>224 == selector AND CALLDATALOAD(4) == key
        return f"600035 60e01c 63{selector.hex()} 14 600435 {_word(key)} 14 16".replace(" ", "")

    body = flag(_STEP_USED, step_id) + flag(_REQUEST_PAID, request) + "17"  # OR
    runtime = body + "60005260206000f3"  # MSTORE(0) RETURN(0, 32)
    size = len(runtime) // 2
    init = f"61{size:04x}80600c6000396000f3"  # copy the runtime (offset 12) and return it
    sender = _chain(url, "eth_accounts")[0]
    sent = _chain(url, "eth_sendTransaction", [{"from": sender, "data": "0x" + init + runtime}])
    for _ in range(4):  # the flags are read CONFIRMATIONS blocks deep; also settles automine
        _chain(url, "evm_mine")
    address = _chain(url, "eth_getTransactionReceipt", [sent])["contractAddress"]
    return bytes.fromhex(address[2:])


def _fresh_sender(url: str) -> tuple[bytes, int]:
    """A funded impersonated executor with no history, and its next nonce."""

    sender = uuid.uuid4().bytes + bytes(4)
    _chain(url, "anvil_setBalance", ["0x" + sender.hex(), hex(10**18)])
    _chain(url, "anvil_impersonateAccount", ["0x" + sender.hex()])
    return sender, 0


def _send_from(url: str, sender: bytes, **tx: str) -> str:
    return str(_chain(url, "eth_sendTransaction", [{"from": "0x" + sender.hex(), **tx}]))


def test_anvil_receipt_is_left_to_the_tracker(database_url: str, anvil_url: str) -> None:
    # The step flag is true as well: a receipt must take precedence over it.
    step_id = uuid.uuid4().bytes * 2
    module = _deploy_module(anvil_url, step_id=step_id)
    mined = _chain(anvil_url, "eth_sendTransaction", [{
        "from": _chain(anvil_url, "eth_accounts")[0], "to": "0x" + "22" * 20, "value": "0x1"
    }])  # fmt: skip
    resolution, op, *_ = asyncio.run(
        _run(
            database_url,
            _client(anvil_url),  # type: ignore[arg-type]
            tx_hash=bytes.fromhex(mined[2:]),
            step_id=step_id,
            module=module,
        )
    )
    assert (resolution, op["status"]) == ("Receipt", "Unknown")


def test_anvil_reverted_receipt_is_reverted_by_the_tracker(
    database_url: str, anvil_url: str
) -> None:
    # PUSH1 0 PUSH1 0 REVERT
    _chain(anvil_url, "anvil_setCode", ["0x" + "0d" * 20, "0x60006000fd"])
    reverted = _chain(anvil_url, "eth_sendTransaction", [{
        "from": _chain(anvil_url, "eth_accounts")[0], "to": "0x" + "0d" * 20, "gas": "0x30000"
    }])  # fmt: skip
    for _ in range(3):
        _chain(anvil_url, "evm_mine")
    assert _chain(anvil_url, "eth_getTransactionReceipt", [reverted])["status"] == "0x0"

    async def scenario() -> tuple[Any, Any]:
        resolution, op, *_ = await _run(
            database_url,
            _client(anvil_url),  # type: ignore[arg-type]
            tx_hash=bytes.fromhex(reverted[2:]),
            sender=bytes.fromhex(_chain(anvil_url, "eth_accounts")[0][2:]),
            nonce=int(_chain(anvil_url, "eth_getTransactionByHash", [reverted])["nonce"], 16),
        )
        # The resolver leaves the receipt to the tracker, which moves the Unknown operation on.
        client = RpcClient([_provider(anvil_url), _provider(anvil_url)])
        await track_transactions(database_url, client_factory=lambda _urls: client)
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        try:
            return resolution, await pool.fetchval(
                "SELECT o.status FROM operations o JOIN transactions t ON t.operation_id = o.id "
                "WHERE t.tx_hash = $1",
                bytes.fromhex(reverted[2:]),
            )
        finally:
            await pool.close()

    assert asyncio.run(scenario()) == ("Receipt", "Reverted")


def test_anvil_step_used_confirms_without_resubmission(database_url: str, anvil_url: str) -> None:
    step_id = uuid.uuid4().bytes * 2
    module = _deploy_module(anvil_url, step_id=step_id)
    resolution, op, _, _, txs, _ = asyncio.run(
        _run(database_url, _client(anvil_url), step_id=step_id, module=module)  # type: ignore[arg-type]
    )
    assert (resolution, op["status"], [t["status"] for t in txs]) == (
        "Confirmed",
        "Confirmed",
        ["Dropped"],
    )
    # A module that marks another step used (or only the same id under requestPaid) says nothing.
    step_id = uuid.uuid4().bytes * 2
    other = _deploy_module(anvil_url, step_id=uuid.uuid4().bytes * 2, request=step_id)
    resolution, op, *_ = asyncio.run(
        _run(database_url, _client(anvil_url), step_id=step_id, module=other, age=2)  # type: ignore[arg-type]
    )
    assert (resolution, op["status"]) == ("Unclear", "Unknown")


def test_anvil_request_paid_confirms_a_pay_step(database_url: str, anvil_url: str) -> None:
    request = uuid.uuid4().bytes * 2
    module = _deploy_module(anvil_url, request=request)
    resolution, op, *_ = asyncio.run(
        _run(database_url, _client(anvil_url), module=module, request_id=request)  # type: ignore[arg-type]
    )
    assert (resolution, op["status"]) == ("Confirmed", "Confirmed")


def test_anvil_never_broadcast_returns_to_not_submitted(database_url: str, anvil_url: str) -> None:
    module = _deploy_module(anvil_url)
    sender, nonce = _fresh_sender(anvil_url)
    step_id = uuid.uuid4().bytes * 2
    resolution, op, *_ = asyncio.run(
        _run(
            database_url,
            _client(anvil_url),  # type: ignore[arg-type]
            nonce=nonce,
            sender=sender,
            step_id=step_id,
            module=module,
        )
    )
    assert (resolution, op["status"], op["last_error"]) == (
        "NeverBroadcast",
        "NotSubmitted",
        "NEVER_BROADCAST",
    )
    # The executor then replays the same step id (one operation, no duplicate).
    assert asyncio.run(_replay(database_url, step_id)) == "Submitted"
    assert asyncio.run(_operations_with_step(database_url, step_id)) == 1


async def _operations_with_step(url: str, step_id: bytes) -> int:
    pool = await create_worker_pool(url, min_size=1, max_size=1)
    try:
        return int(
            await pool.fetchval("SELECT count(*) FROM operations WHERE step_id = $1", step_id)
        )
    finally:
        await pool.close()


def test_anvil_consumed_nonce_is_traced_to_its_block(database_url: str, anvil_url: str) -> None:
    module = _deploy_module(anvil_url)
    for reverts, expected in ((False, "Abandoned"), (True, "Reverted")):
        sender, nonce = _fresh_sender(anvil_url)
        target = "0x" + "0d" * 20 if reverts else "0x" + "22" * 20
        _chain(anvil_url, "anvil_setCode", ["0x" + "0d" * 20, "0x60006000fd"])
        _send_from(anvil_url, sender, to="0x" + "22" * 20, value="0x1")  # nonce 0
        _send_from(anvil_url, sender, to=target, gas="0x30000")  # nonce 1: the one we trace
        _send_from(anvil_url, sender, to="0x" + "22" * 20, value="0x1")  # nonce 2
        for _ in range(4):
            _chain(anvil_url, "evm_mine")
        resolution, op, _, _, txs, _ = asyncio.run(
            _run(
                database_url,
                _client(anvil_url),  # type: ignore[arg-type]
                nonce=1,
                sender=sender,
                module=module,
                age=20,
            )
        )
        assert (resolution, op["status"]) == (expected, expected)
        assert op["last_error"].startswith("NONCE_CONSUMED_BY 0x") and len(txs) == 1


def test_anvil_consumed_nonce_without_evidence_escalates(database_url: str, anvil_url: str) -> None:
    module = _deploy_module(anvil_url)
    sender, _ = _fresh_sender(anvil_url)
    # Mined in the newest block: not CONFIRMATIONS deep, so it cannot be classified yet.
    _send_from(anvil_url, sender, to="0x" + "22" * 20, value="0x1")
    resolution, op, items, *_ = asyncio.run(
        _run(database_url, _client(anvil_url), nonce=0, sender=sender, module=module, age=31)  # type: ignore[arg-type]
    )
    assert (resolution, op["status"]) == ("Escalated", "Unknown")
    assert [i["status"] for i in items] == ["Open"]
    # The treasury stays blocked: the execution cycle's gate sees the Unknown operation.
    assert asyncio.run(_blocked(database_url)) is True


async def _blocked(url: str) -> bool:
    pool = await create_worker_pool(url, min_size=1, max_size=1)
    try:
        async with pool.acquire() as connection:
            state = await _read_gates(connection, _TREASURY, now=NOW)
        assert state is not None
        return state.unknown_operation
    finally:
        await pool.close()
