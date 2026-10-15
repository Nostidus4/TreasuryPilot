"""Transaction tracker against a real Anvil chain and PostgreSQL (CHR-003)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
import uuid
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from web3 import AsyncHTTPProvider

from treasurypilot_core.ids import uuid7
from treasurypilot_core.policy import PolicyReasonCode, error_selector
from treasurypilot_core.policy.reason_codes import REASON_CODES
from treasurypilot_worker.chain.rpc import RpcClient, RpcProvider
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.tracker import track_transactions

API_ROOT = Path(__file__).parents[2] / "api"
CHAIN_ID = 31337
SENDER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
RECIPIENT = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
_ORG = "00000000-0000-7000-8000-000000000010"
_ASSET = "00000000-0000-7000-8000-000000000030"
_TREASURY = "00000000-0000-7000-8000-000000000040"
_VENDOR = "00000000-0000-7000-8000-000000000050"
_PAYEE = "00000000-0000-7000-8000-000000000060"
_REQUEST = "00000000-0000-7000-8000-000000000070"


def _rpc(url: str, method: str, params: Sequence[object] = ()) -> Any:
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
        pytest.skip("anvil is required for the tracker integration tests")
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


async def _seed(database_url: str) -> None:
    engine = create_async_engine(database_url)
    statements = [
        f"INSERT INTO organizations (id, name) VALUES ('{_ORG}', 'Tracker test')",
        "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
        f"VALUES ({CHAIN_ID}, 'Anvil', true, 3, 'https://explorer.invalid', '[\"http://rpc\"]')",
        "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
        f"VALUES ('{_ASSET}', {CHAIN_ID}, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
        "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
        f"VALUES ('{_TREASURY}', '{_ORG}', {CHAIN_ID}, '{_ASSET}')",
        "INSERT INTO vendors (id, org_id, name, normalized_ref) "
        f"VALUES ('{_VENDOR}', '{_ORG}', 'Vendor', 'vendor')",
        "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
        f"VALUES ('{_PAYEE}', '{_TREASURY}', '{_ORG}', '{_VENDOR}', 'Main', "
        "decode(repeat('22', 20), 'hex'), 'Proposed')",
        "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, "
        "invoice_no, issue_date, due_at, amount, asset_id) VALUES "
        f"('{_REQUEST}', '{_ORG}', '{_TREASURY}', {CHAIN_ID}, '{_VENDOR}', '{_PAYEE}', "
        f"'TRK-001', '2026-10-01', '2026-10-31', 1000, '{_ASSET}')",
    ]
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the tracker integration tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(url))
        yield url
    finally:
        command.downgrade(config, "base")


class Lying:
    """A secondary provider that reports a different block hash for every receipt."""

    def __init__(self, inner: AsyncHTTPProvider) -> None:
        self.inner = inner

    async def make_request(self, method: Any, params: Any) -> Mapping[str, Any]:
        response = dict(await self.inner.make_request(method, params))
        if method == "eth_getTransactionReceipt" and response.get("result"):
            response["result"] = {**response["result"], "blockHash": "0x" + "ab" * 32}
        if method == "eth_getBlockByNumber" and response.get("result"):
            response["result"] = {**response["result"], "hash": "0x" + "ab" * 32}
        return response


def _client(url: str, *, secondary_lies: bool = False) -> RpcClient:
    primary = AsyncHTTPProvider(url, exception_retry_configuration=None)
    secondary = AsyncHTTPProvider(url, exception_retry_configuration=None)
    return RpcClient(
        [
            RpcProvider("primary", primary),
            RpcProvider("secondary", Lying(secondary) if secondary_lies else secondary),  # type: ignore[arg-type]
        ]
    )


def _send(url: str, **fields: object) -> str:
    tx = {"from": SENDER, "to": RECIPIENT, "value": "0x1", **fields}
    return str(_rpc(url, "eth_sendTransaction", [tx]))


def _mine(url: str, blocks: int = 1) -> None:
    for _ in range(blocks):
        _rpc(url, "evm_mine")


async def _register(
    database_url: str, tx_hash: str, nonce: int, *, operation: str | None = None, **overrides: Any
) -> tuple[str, str]:
    """Insert an operation (unless given) and a Submitted transaction row; return both ids."""

    pool = await create_worker_pool(database_url, min_size=1, max_size=1)
    try:
        operation_id = operation or str(uuid.uuid4())
        if operation is None:
            await pool.execute(
                "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, "
                "kind, payload, idempotency_key, status) VALUES ($1, $2, $3, $4, $5, 'PAY', "
                "'{}'::jsonb, $6, 'Submitted')",
                uuid.UUID(operation_id),
                uuid.UUID(_TREASURY),
                uuid.uuid4(),
                uuid.UUID(_REQUEST),
                uuid.uuid4().bytes * 2,
                operation_id,
            )
        tx_id = uuid.uuid4()
        await pool.execute(
            "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, from_address, "
            "submitted_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
            tx_id,
            uuid.UUID(operation_id),
            CHAIN_ID,
            bytes.fromhex(tx_hash.removeprefix("0x")),
            nonce,
            bytes.fromhex(SENDER.removeprefix("0x")),
            overrides.get("submitted_at", datetime.now(UTC)),
        )
        return str(tx_id), operation_id
    finally:
        await pool.close()


async def _track(database_url: str, client: RpcClient, now: datetime | None = None) -> None:
    await track_transactions(database_url, client_factory=lambda _urls: client, now=now)


async def _fetch(database_url: str, sql: str, *args: Any) -> Any:
    pool = await create_worker_pool(database_url, min_size=1, max_size=1)
    try:
        return await pool.fetchrow(sql, *args)
    finally:
        await pool.close()


async def _tx(database_url: str, tx_id: str) -> Any:
    return await _fetch(database_url, "SELECT * FROM transactions WHERE id = $1", uuid.UUID(tx_id))


async def _operation_status(database_url: str, operation_id: str) -> str:
    row = await _fetch(
        database_url, "SELECT status FROM operations WHERE id = $1", uuid.UUID(operation_id)
    )
    return str(row["status"])


async def _gas_ledger(database_url: str, transaction_id: str) -> Any:
    return await _fetch(
        database_url,
        "SELECT payer, payer_address, fee_wei, reverted, day FROM gas_ledger "
        "WHERE transaction_id = $1",
        uuid.UUID(transaction_id),
    )


async def _stream_cursor(database_url: str) -> uuid.UUID:
    """Insert the newest event an SSE client could already have seen; return its id."""
    pool = await create_worker_pool(database_url, min_size=1, max_size=1)
    try:
        cursor = uuid7()
        await pool.execute(
            "INSERT INTO domain_events (id, org_id, treasury_id, type, entity_type, entity_id, "
            "payload) SELECT $1, org_id, id, 'Cursor', 'treasury', id, '{}'::jsonb "
            "FROM treasuries WHERE id = $2",
            cursor,
            uuid.UUID(_TREASURY),
        )
        return cursor
    finally:
        await pool.close()


async def _operation_events(database_url: str, operation_id: str) -> list[Any]:
    pool = await create_worker_pool(database_url, min_size=1, max_size=1)
    try:
        return await pool.fetch(
            "SELECT id, type, entity_type, entity_id, treasury_id, "
            "jsonb_typeof(payload) AS payload_type, payload FROM domain_events "
            "WHERE entity_id = $1 ORDER BY created_at, id",
            uuid.UUID(operation_id),
        )
    finally:
        await pool.close()


def _nonce(url: str) -> int:
    return int(_rpc(url, "eth_getTransactionCount", [SENDER, "latest"]), 16)


def test_confirmed_only_at_three_confirmations_with_matching_crosscheck(
    anvil_url: str, database_url: str
) -> None:
    async def scenario() -> None:
        nonce = _nonce(anvil_url)
        tx_hash = _send(anvil_url, nonce=hex(nonce))
        tx_id, operation_id = await _register(database_url, tx_hash, nonce)
        client = _client(anvil_url)
        cursor = await _stream_cursor(database_url)
        await asyncio.sleep(0.01)

        await _track(database_url, client)  # mined in 1 block: 1 confirmation
        row = await _tx(database_url, tx_id)
        assert (row["status"], row["confirmations"]) == ("Pending", 1)
        assert row["block_number"] is not None and row["confirmed_at"] is None
        assert await _operation_status(database_url, operation_id) == "Pending"
        events = await _operation_events(database_url, operation_id)
        assert len(events) == 1
        assert (
            events[0]["type"],
            events[0]["entity_type"],
            events[0]["entity_id"],
            events[0]["treasury_id"],
        ) == (
            "OperationUpdated",
            "operation",
            uuid.UUID(operation_id),
            uuid.UUID(_TREASURY),
        )
        # asyncpg returns JSONB as text by default. Assert storage is an object, then
        # decode the transport value before checking the ids-only event contract.
        assert events[0]["payload_type"] == "object"
        assert json.loads(events[0]["payload"]) == {"operationId": operation_id}

        _mine(anvil_url)
        await _track(database_url, client)  # 2 confirmations
        assert (await _tx(database_url, tx_id))["status"] == "Pending"
        assert len(await _operation_events(database_url, operation_id)) == 2

        _mine(anvil_url)
        await _track(database_url, client)  # 3 confirmations + secondary agrees
        row = await _tx(database_url, tx_id)
        assert (row["status"], row["confirmations"], row["crosscheck"]) == ("Confirmed", 3, "Match")
        receipt = _rpc(anvil_url, "eth_getTransactionReceipt", [tx_hash])
        block = _rpc(anvil_url, "eth_getBlockByNumber", [receipt["blockNumber"], False])
        assert row["block_hash"] == bytes.fromhex(receipt["blockHash"][2:])
        assert row["gas_used"] == int(receipt["gasUsed"], 16)
        assert row["fee_wei"] == int(receipt["gasUsed"], 16) * int(receipt["effectiveGasPrice"], 16)
        # BR-026: the day is attributed from the mined block's timestamp, not the poll time.
        assert row["confirmed_at"] == datetime.fromtimestamp(int(block["timestamp"], 16), UTC)
        ledger = await _gas_ledger(database_url, tx_id)
        assert ledger is not None
        assert ledger["payer"] == "EXECUTOR"
        assert ledger["payer_address"] == row["from_address"]
        assert ledger["fee_wei"] == row["fee_wei"]
        assert ledger["day"] == row["confirmed_at"].date()
        assert await _operation_status(database_url, operation_id) == "Confirmed"
        assert len(await _operation_events(database_url, operation_id)) == 3

        # A stale operation row is repaired even when the transaction itself did not
        # change; subscribers still receive an operation event for that state repair.
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        try:
            await pool.execute(
                "UPDATE operations SET status = 'Submitted' WHERE id = $1",
                uuid.UUID(operation_id),
            )
        finally:
            await pool.close()
        await _track(database_url, client)
        assert await _operation_status(database_url, operation_id) == "Confirmed"
        events = await _operation_events(database_url, operation_id)
        assert len(events) == 4
        # The SSE stream resumes with `id > cursor`, so every tracker event must sort after it.
        assert all(event["id"].version == 7 and event["id"] > cursor for event in events)

    asyncio.run(scenario())


def test_crosscheck_mismatch_never_confirms(anvil_url: str, database_url: str) -> None:
    async def scenario() -> None:
        nonce = _nonce(anvil_url)
        tx_hash = _send(anvil_url, nonce=hex(nonce))
        tx_id, operation_id = await _register(database_url, tx_hash, nonce)
        _mine(anvil_url, 3)

        await _track(database_url, _client(anvil_url, secondary_lies=True))
        row = await _tx(database_url, tx_id)
        assert (row["status"], row["crosscheck"]) == ("Pending", "Mismatch")
        assert row["confirmed_at"] is None
        assert await _operation_status(database_url, operation_id) == "Pending"

        # Once the disagreement is gone the same transaction can confirm.
        await _track(database_url, _client(anvil_url))
        assert (await _tx(database_url, tx_id))["status"] == "Confirmed"

    asyncio.run(scenario())


def test_timeout_without_receipt_or_mempool_entry_is_unknown_never_failed(
    anvil_url: str, database_url: str
) -> None:
    async def scenario() -> None:
        # Never broadcast: neither a receipt nor a mempool entry exists.
        tx_id, operation_id = await _register(
            database_url, "0x" + uuid.uuid4().hex * 2, _nonce(anvil_url) + 500
        )
        client = _client(anvil_url)

        await _track(database_url, client, now=datetime.now(UTC) + timedelta(minutes=9))
        assert (await _tx(database_url, tx_id))["status"] == "Submitted"

        await _track(database_url, client, now=datetime.now(UTC) + timedelta(minutes=11))
        assert (await _tx(database_url, tx_id))["status"] == "Unknown"
        assert await _operation_status(database_url, operation_id) == "Unknown"

    asyncio.run(scenario())


def test_transaction_in_mempool_is_pending_and_not_unknown(
    anvil_url: str, database_url: str
) -> None:
    async def scenario() -> None:
        _rpc(anvil_url, "evm_setAutomine", [False])
        try:
            nonce = _nonce(anvil_url)
            tx_hash = _send(anvil_url, nonce=hex(nonce))
            tx_id, _ = await _register(database_url, tx_hash, nonce)
            await _track(
                database_url, _client(anvil_url), now=datetime.now(UTC) + timedelta(minutes=11)
            )
            assert (await _tx(database_url, tx_id))["status"] == "Pending"
        finally:
            _rpc(anvil_url, "evm_setAutomine", [True])
            _mine(anvil_url)

    asyncio.run(scenario())


def test_replacement_with_the_same_nonce_marks_the_original_dropped_and_links_it(
    anvil_url: str, database_url: str
) -> None:
    async def scenario() -> None:
        _rpc(anvil_url, "evm_setAutomine", [False])
        try:
            nonce = _nonce(anvil_url)
            original = _send(anvil_url, nonce=hex(nonce), maxFeePerGas=hex(2 * 10**9))
            replacement = _send(
                anvil_url, nonce=hex(nonce), value="0x2", maxFeePerGas=hex(10 * 10**9),
                maxPriorityFeePerGas=hex(10**9),
            )  # fmt: skip
            original_id, operation_id = await _register(database_url, original, nonce)
            replacement_id, _ = await _register(
                database_url, replacement, nonce, operation=operation_id
            )
            _mine(anvil_url)
        finally:
            _rpc(anvil_url, "evm_setAutomine", [True])

        await _track(database_url, _client(anvil_url))
        dropped = await _tx(database_url, original_id)
        assert dropped["status"] == "Dropped"
        assert str(dropped["replaced_by_tx_id"]) == replacement_id
        # The operation follows the mined replacement, not the dropped original.
        assert (await _tx(database_url, replacement_id))["status"] == "Pending"
        assert await _operation_status(database_url, operation_id) == "Pending"

    asyncio.run(scenario())


def test_reverted_transaction_stores_the_decoded_revert_selector(
    anvil_url: str, database_url: str
) -> None:
    code, reason = next((c, r) for c, r in REASON_CODES.items() if r.contract_errors)
    selector = error_selector(reason.contract_errors[0])
    reverter = "0x00000000000000000000000000000000000d00d1"
    # PUSH4 selector PUSH1 224 SHL PUSH1 0 MSTORE PUSH1 4 PUSH1 0 REVERT
    runtime = "63" + selector.hex() + "60e01b60005260046000fd"
    _rpc(anvil_url, "anvil_setCode", [reverter, "0x" + runtime])

    async def scenario() -> None:
        nonce = _nonce(anvil_url)
        tx_hash = _send(anvil_url, nonce=hex(nonce), to=reverter, gas=hex(100_000))
        tx_id, operation_id = await _register(database_url, tx_hash, nonce)
        assert _rpc(anvil_url, "eth_getTransactionReceipt", [tx_hash])["status"] == "0x0"
        _mine(anvil_url, 2)

        await _track(database_url, _client(anvil_url))
        row = await _tx(database_url, tx_id)
        assert (row["status"], bytes(row["revert_selector"])) == ("Reverted", selector)
        assert row["fee_wei"] > 0
        ledger = await _gas_ledger(database_url, tx_id)
        assert ledger is not None and ledger["reverted"] is True
        assert await _operation_status(database_url, operation_id) == "Reverted"
        error = (
            await _fetch(
                database_url,
                "SELECT last_error FROM operations WHERE id = $1",
                uuid.UUID(operation_id),
            )
        )["last_error"]
        assert PolicyReasonCode.SIMULATION_REVERTED in error and code in error

    asyncio.run(scenario())


def test_reorg_that_removes_a_confirmed_transaction_demotes_it_to_pending(
    anvil_url: str, database_url: str
) -> None:
    async def scenario() -> None:
        snapshot = _rpc(anvil_url, "evm_snapshot")
        nonce = _nonce(anvil_url)
        tx_hash = _send(anvil_url, nonce=hex(nonce))
        tx_id, operation_id = await _register(database_url, tx_hash, nonce)
        _mine(anvil_url, 2)
        client = _client(anvil_url)
        await _track(database_url, client)
        row = await _tx(database_url, tx_id)
        assert row["status"] == "Confirmed" and row["confirmed_at"] is not None
        assert await _gas_ledger(database_url, tx_id) is not None
        assert await _operation_status(database_url, operation_id) == "Confirmed"

        # Nothing changed on chain: a re-scan leaves the final state alone but keeps counting.
        _mine(anvil_url)
        await _track(database_url, client)
        row = await _tx(database_url, tx_id)
        assert (row["status"], row["confirmations"]) == ("Confirmed", 4)

        assert _rpc(anvil_url, "evm_revert", [snapshot]) is True
        _mine(anvil_url, 4)  # the canonical chain is now longer, without the transaction
        await _track(database_url, client)
        row = await _tx(database_url, tx_id)
        assert row["status"] == "Pending"
        assert row["confirmed_at"] is None
        assert await _gas_ledger(database_url, tx_id) is None
        assert await _operation_status(database_url, operation_id) == "Pending"

    asyncio.run(scenario())


def test_reorg_that_remines_the_transaction_in_another_block_changes_the_block_hash(
    anvil_url: str, database_url: str
) -> None:
    async def scenario() -> None:
        snapshot = _rpc(anvil_url, "evm_snapshot")
        nonce = _nonce(anvil_url)
        fees = {"gas": hex(21_000), "maxFeePerGas": hex(10**10), "maxPriorityFeePerGas": hex(1)}
        tx_hash = _send(anvil_url, nonce=hex(nonce), **fees)
        tx_id, operation_id = await _register(database_url, tx_hash, nonce)
        _mine(anvil_url, 2)
        client = _client(anvil_url)
        await _track(database_url, client)
        before = await _tx(database_url, tx_id)
        assert before["status"] == "Confirmed"

        _rpc(anvil_url, "evm_revert", [snapshot])
        _mine(anvil_url)  # a different block now sits where the old one was
        assert _send(anvil_url, nonce=hex(nonce), **fees) == tx_hash  # same transaction, new block
        await _track(database_url, client)
        after = await _tx(database_url, tx_id)
        assert after["block_hash"] != before["block_hash"]
        assert (after["status"], after["confirmations"]) == ("Pending", 1)
        assert after["confirmed_at"] is None
        assert await _operation_status(database_url, operation_id) == "Pending"

        _mine(anvil_url, 2)  # the new inclusion confirms on its own
        await _track(database_url, client)
        assert (await _tx(database_url, tx_id))["status"] == "Confirmed"
        assert await _operation_status(database_url, operation_id) == "Confirmed"

    asyncio.run(scenario())


def test_transactions_deeper_than_the_reorg_window_are_no_longer_rescanned(
    anvil_url: str, database_url: str
) -> None:
    async def scenario() -> None:
        nonce = _nonce(anvil_url)
        tx_hash = _send(anvil_url, nonce=hex(nonce))
        tx_id, _ = await _register(database_url, tx_hash, nonce)
        _mine(anvil_url, 2)
        client = _client(anvil_url)
        await _track(database_url, client)
        _mine(anvil_url, 64)
        await _track(database_url, client)  # last scan: confirmations now past the window
        frozen = (await _tx(database_url, tx_id))["confirmations"]
        assert frozen >= 64
        _mine(anvil_url)
        await _track(database_url, client)
        assert (await _tx(database_url, tx_id))["confirmations"] == frozen

    asyncio.run(scenario())
