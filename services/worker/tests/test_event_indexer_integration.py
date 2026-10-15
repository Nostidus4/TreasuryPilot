"""Event indexer against a real Anvil chain and PostgreSQL (CHR-005).

Anvil hosts tiny hand-assembled contracts that emit a log with the topics and data they are
called with, standing in for the module and the Safe at exact addresses.
"""

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
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from eth_abi import encode
from eth_utils import keccak
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from web3 import AsyncHTTPProvider

from treasurypilot_worker.chain.event_handlers import HandlerRegistry, IndexedEvent
from treasurypilot_worker.chain.events import EVENTS, MODULE, SAFE_EXEC
from treasurypilot_worker.chain.indexer import index_events
from treasurypilot_worker.chain.rpc import RpcClient, RpcProvider, SafeConfig
from treasurypilot_worker.locks import create_worker_pool

API_ROOT = Path(__file__).parents[2] / "api"
CHAIN_ID = 31337
SENDER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
MODULE_ADDR = "0x" + "aa" * 20
SAFE_ADDR = "0x" + "bb" * 20
OTHER_ADDR = "0x" + "cc" * 20
PAYEE_ADDR = "0x" + "22" * 20
OTHER_PAYEE_ADDR = "0x" + "23" * 20
REQUEST_ID = bytes.fromhex("07" * 32)
SAFE_TX_HASH = bytes.fromhex("5a" * 32)
IMPLEMENTATION = "0x" + "e1" * 20
FALLBACK = "0x" + "e2" * 20
GUARD = "0x" + "99" * 20
_ID = "00000000-0000-7000-8000-0000000000{:02d}"
ORG, ASSET, TREASURY, VENDOR, PAYEE, OTHER_PAYEE = (_ID.format(n) for n in (10, 30, 40, 50, 60, 61))
REQUEST, USER, WALLET, EXCEPTION, GOVERNANCE = (_ID.format(n) for n in (70, 71, 72, 73, 74))


def _rpc(url: str, method: str, params: Sequence[object] = ()) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    assert "error" not in payload, payload
    return payload["result"]


# One chain per test: a fresh database re-reads every log still on a shared chain.
@pytest.fixture
def anvil_url() -> Iterator[str]:
    if "TP_TEST_ANVIL_URL" in os.environ:
        yield os.environ["TP_TEST_ANVIL_URL"]
        return
    if shutil.which("anvil") is None:
        pytest.skip("anvil is required for the event indexer integration tests")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    process = subprocess.Popen(
        [
            "anvil",
            "--silent",
            "--port",
            str(port),
            "--chain-id",
            str(CHAIN_ID),
        ],
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


def _emitter(topics: int) -> str:
    """Runtime code that LOGs calldata[32*topics:] with the first ``topics`` words as topics."""

    code = b"".join(bytes([0x60, 32 * i, 0x35]) for i in reversed(range(topics)))
    code += bytes([0x60, 32 * topics, 0x36, 0x03])  # size = calldatasize - 32 * topics
    code += bytes([0x80, 0x60, 32 * topics, 0x60, 0x00, 0x37])  # copy the data to memory
    code += bytes([0x60, 0x00, 0xA0 + topics, 0x00])  # LOGn(0, size, topics...)
    return "0x" + code.hex()


def _emit(url: str, address: str, event: str, *topics: bytes, data: bytes = b"") -> str:
    """Emit ``event`` (a declared name) from ``address``; topics after topic0 are padded."""

    topic0 = next(
        bytes.fromhex(topic0[2:]) for topic0, abi in EVENTS_ALL.items() if abi.name == event
    )
    words = [topic0, *(topic.rjust(32, b"\0") for topic in topics)]
    _rpc(url, "anvil_setCode", [address, _emitter(len(words))])
    sent = _rpc(
        url,
        "eth_sendTransaction",
        [{"from": SENDER, "to": address, "data": "0x" + (b"".join(words) + data).hex()}],
    )
    # Mined at once: the next emit swaps this address's code.
    _mine(url)
    return str(sent)


EVENTS_ALL = {topic0: abi for abis in EVENTS.values() for topic0, abi in abis.items()}


def _mine(url: str, blocks: int = 1) -> None:
    _rpc(url, "anvil_mine", [hex(blocks)])


def _addr(value: str) -> bytes:
    return bytes.fromhex(value[2:])


async def _seed(database_url: str) -> None:
    engine = create_async_engine(database_url)
    statements = [
        f"INSERT INTO organizations (id, name) VALUES ('{ORG}', 'Indexer test')",
        f"INSERT INTO users (id, email) VALUES ('{USER}', 'owner@example.com')",
        "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
        f"VALUES ({CHAIN_ID}, 'Anvil', true, 3, 'https://explorer.invalid', '[\"http://rpc\"]')",
        "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
        f"VALUES ('{ASSET}', {CHAIN_ID}, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
        "INSERT INTO treasuries (id, org_id, chain_id, asset_id, module_address) "
        f"VALUES ('{TREASURY}', '{ORG}', {CHAIN_ID}, '{ASSET}', decode('{MODULE_ADDR[2:]}', 'hex'))",
        "INSERT INTO treasury_wallets (id, org_id, treasury_id, chain_id, role, label, "
        f"safe_address, owners, threshold) VALUES ('{WALLET}', '{ORG}', '{TREASURY}', "
        f"{CHAIN_ID}, 'SOURCE', 'Source', decode('{SAFE_ADDR[2:]}', 'hex'), "
        f"'[\"{SENDER}\"]'::jsonb, 1)",
        "INSERT INTO vendors (id, org_id, name, normalized_ref) "
        f"VALUES ('{VENDOR}', '{ORG}', 'Vendor', 'vendor')",
        *(
            "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status, "
            "oob_verified_by, oob_verified_at, oob_method, oob_note) VALUES "
            f"('{payee}', '{TREASURY}', '{ORG}', '{VENDOR}', 'Payee', "
            f"decode('{address[2:]}', 'hex'), 'AwaitingOwner', '{USER}', now(), 'PHONE', 'called')"
            for payee, address in ((PAYEE, PAYEE_ADDR), (OTHER_PAYEE, OTHER_PAYEE_ADDR))
        ),
        "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, "
        "invoice_no, issue_date, due_at, amount, asset_id, onchain_request_id, cancel_onchain) "
        f"VALUES ('{REQUEST}', '{ORG}', '{TREASURY}', {CHAIN_ID}, '{VENDOR}', '{PAYEE}', "
        f"'IDX-001', '2026-10-01', '2026-10-31', 1000, '{ASSET}', "
        f"decode('{REQUEST_ID.hex()}', 'hex'), 'Pending')",
        "INSERT INTO exceptions (id, org_id, treasury_id, request_id, mandate_onchain_version, "
        "amount, payee, expiry, status) VALUES "
        f"('{EXCEPTION}', '{ORG}', '{TREASURY}', '{REQUEST}', 1, 1000, "
        f"decode('{PAYEE_ADDR[2:]}', 'hex'), now() + interval '1 day', 'Proposed')",
        "INSERT INTO governance_txs (id, org_id, treasury_id, chain_id, safe_address, purpose, "
        'calls, "to", value, data, operation, safe_nonce, safe_tx_hash, threshold, '
        "owners_snapshot, status) VALUES "
        f"('{GOVERNANCE}', '{ORG}', '{TREASURY}', {CHAIN_ID}, decode('{SAFE_ADDR[2:]}', 'hex'), "
        f"'PAYEE_ADD', '[]'::jsonb, decode('{MODULE_ADDR[2:]}', 'hex'), 0, '\\x', 0, 0, "
        f"decode('{SAFE_TX_HASH.hex()}', 'hex'), 1, "
        f"ARRAY[decode('{SENDER[2:].lower()}', 'hex')], 'Submitted')",
        *(
            "INSERT INTO deployments (id, chain_id, name, address, code_hash, version) VALUES "
            f"('{uuid.uuid4()}', {CHAIN_ID}, '{name}', decode('{address[2:]}', 'hex'), "
            f"decode(repeat('00', 32), 'hex'), '1.0.0')"
            for name, address in (
                ("TREASURY_MODULE_IMPLEMENTATION", IMPLEMENTATION),
                ("SAFE_FALLBACK_HANDLER", FALLBACK),
            )
        ),
    ]
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the event indexer integration tests")
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


class Client(RpcClient):
    """Real Anvil reads; ``safe_config`` is scripted because the Safe here is an emitter."""

    def __init__(self, url: str, guard: str | None = None) -> None:
        super().__init__(
            [RpcProvider("anvil", AsyncHTTPProvider(url, exception_retry_configuration=None))]
        )  # type: ignore[arg-type]
        self.guard = guard
        self.methods: list[str] = []

    async def call(self, method: str, params: Sequence[Any]) -> Any:
        self.methods.append(method)
        return await super().call(method, params)

    async def safe_config(self, safe: str) -> SafeConfig:
        block = await self.call("eth_getBlockByNumber", ["latest", False])
        module = MODULE_ADDR
        return SafeConfig(
            block_number=int(block["number"], 16),
            block_hash=block["hash"],
            owners=(SENDER.lower(),),
            threshold=1,
            modules=(module,),
            guard=self.guard,
            fallback_handler=FALLBACK,
            nonce=0,
            module_implementations=(IMPLEMENTATION,),
        )


async def _index(url: str, database_url: str, **kwargs: Any) -> tuple[dict[str, int], Client]:
    client = Client(url, kwargs.pop("guard", None))
    result = await index_events(database_url, client_factory=lambda _urls: client, **kwargs)
    return result, client


async def _one(database_url: str, query: str, *args: Any) -> Any:
    pool = await create_worker_pool(database_url, min_size=1, max_size=1)
    try:
        return await pool.fetchrow(query, *args)
    finally:
        await pool.close()


def _address_topic(address: str) -> bytes:
    return _addr(address)


def test_module_and_safe_events_update_application_state(anvil_url: str, database_url: str) -> None:
    activation = int(time.time()) + 3600
    exception_expiry = int(
        asyncio.run(
            _one(
                database_url,
                "SELECT floor(extract(epoch FROM expiry))::bigint AS expiry FROM exceptions",
            )
        )["expiry"]
    )
    _emit(
        anvil_url,
        MODULE_ADDR,
        "PayeeAdded",
        _address_topic(PAYEE_ADDR),
        data=encode(["uint64"], [activation]),
    )
    _emit(anvil_url, MODULE_ADDR, "Paused", _address_topic(SENDER))
    _emit(
        anvil_url,
        MODULE_ADDR,
        "ExceptionGranted",
        REQUEST_ID,
        data=encode(
            ["uint128", "address", "uint64", "uint64"],
            [1000, PAYEE_ADDR, exception_expiry, 1],
        ),
    )
    cancel = _emit(anvil_url, MODULE_ADDR, "RequestCancelled", REQUEST_ID, _address_topic(SENDER))
    _emit(
        anvil_url,
        MODULE_ADDR,
        "Supplied",
        b"\x01" * 32,
        data=encode(["uint256", "uint256"], [5_000_000, 20_000]),
    )
    _emit(
        anvil_url,
        MODULE_ADDR,
        "Withdrawn",
        b"\x02" * 32,
        data=encode(["uint256", "uint256"], [1, 20_000]),
    )
    execution = _emit(
        anvil_url, SAFE_ADDR, "ExecutionSuccess", SAFE_TX_HASH, data=encode(["uint256"], [0])
    )
    _mine(anvil_url)

    result, _ = asyncio.run(_index(anvil_url, database_url))

    assert result == {"changed": 7}
    assert (
        asyncio.run(
            _one(
                database_url,
                "SELECT status::text, active_from FROM payees WHERE id = $1",
                uuid.UUID(PAYEE),
            )
        )["status"]
        == "Cooling"
    )
    pause = asyncio.run(
        _one(database_url, "SELECT paused, onchain_status::text AS s FROM backend_pause")
    )
    assert (pause["paused"], pause["s"]) == (True, "Effective")
    assert (
        asyncio.run(_one(database_url, "SELECT status::text AS s FROM exceptions"))["s"]
        == "Granted"
    )
    request = asyncio.run(
        _one(database_url, "SELECT cancel_onchain, cancel_tx_hash FROM payment_requests")
    )
    assert request["cancel_onchain"] == "Confirmed"
    assert bytes(request["cancel_tx_hash"]) == _addr(cancel)
    governance = asyncio.run(
        _one(database_url, "SELECT status::text AS s, exec_tx_hash FROM governance_txs")
    )
    assert governance["s"] == "Executed"
    assert bytes(governance["exec_tx_hash"]) == _addr(execution)
    names = asyncio.run(
        _one(
            database_url,
            "SELECT array_agg(event_name ORDER BY event_name) AS n FROM observed_events",
        )
    )["n"]
    assert names == [
        "ExceptionGranted",
        "ExecutionSuccess",
        "Paused",
        "PayeeAdded",
        "RequestCancelled",
        "Supplied",
        "Withdrawn",
    ]
    supplied = asyncio.run(
        _one(
            database_url,
            "SELECT payload::text AS p FROM observed_events WHERE event_name = 'Supplied'",
        )
    )["p"]
    assert json.loads(supplied) == {"stepId": "0x" + "01" * 32, "amount": "5000000", "day": "20000"}


def test_exception_revocation_consumption_and_mandate_invalidation(
    anvil_url: str, database_url: str
) -> None:
    expiry = int(
        asyncio.run(
            _one(
                database_url,
                "SELECT floor(extract(epoch FROM expiry))::bigint AS expiry FROM exceptions",
            )
        )["expiry"]
    )
    _emit(
        anvil_url,
        MODULE_ADDR,
        "ExceptionGranted",
        REQUEST_ID,
        data=encode(["uint128", "address", "uint64", "uint64"], [1000, PAYEE_ADDR, expiry, 1]),
    )
    asyncio.run(_index(anvil_url, database_url))
    assert (
        asyncio.run(_one(database_url, "SELECT status::text AS s FROM exceptions"))["s"]
        == "Granted"
    )

    _emit(anvil_url, MODULE_ADDR, "ExceptionRevoked", REQUEST_ID)
    asyncio.run(_index(anvil_url, database_url))
    assert (
        asyncio.run(_one(database_url, "SELECT status::text AS s FROM exceptions"))["s"]
        == "Revoked"
    )

    asyncio.run(
        _one(
            database_url,
            "UPDATE exceptions SET status = 'Granted' WHERE id = $1 RETURNING id",
            uuid.UUID(EXCEPTION),
        )
    )
    _emit(
        anvil_url,
        MODULE_ADDR,
        "PaymentExecuted",
        REQUEST_ID,
        b"\x01" * 32,
        b"\x02" * 32,
        data=encode(
            ["address", "address", "uint256", "uint256", "bool", "bool"],
            [SENDER, PAYEE_ADDR, 1000, 20_000, True, False],
        ),
    )
    asyncio.run(_index(anvil_url, database_url))
    assert (
        asyncio.run(_one(database_url, "SELECT status::text AS s FROM exceptions"))["s"]
        == "Consumed"
    )

    asyncio.run(
        _one(
            database_url,
            "UPDATE exceptions SET status = 'Granted' WHERE id = $1 RETURNING id",
            uuid.UUID(EXCEPTION),
        )
    )
    _emit(
        anvil_url, MODULE_ADDR, "MandateConfigured", data=encode(["uint64", "uint64"], [2, expiry])
    )
    asyncio.run(_index(anvil_url, database_url))
    assert (
        asyncio.run(_one(database_url, "SELECT status::text AS s FROM exceptions"))["s"]
        == "Invalidated"
    )


def test_rereading_the_same_range_creates_no_duplicates_or_repeat_effects(
    anvil_url: str, database_url: str
) -> None:
    _emit(anvil_url, MODULE_ADDR, "Paused", _address_topic(SENDER))
    _mine(anvil_url)
    first, _ = asyncio.run(_index(anvil_url, database_url))
    version = asyncio.run(_one(database_url, "SELECT version FROM backend_pause"))["version"]

    second, _ = asyncio.run(_index(anvil_url, database_url))

    assert (first["changed"], second["changed"]) == (1, 0)
    assert asyncio.run(_one(database_url, "SELECT count(*) AS n FROM observed_events"))["n"] == 1
    assert (
        asyncio.run(_one(database_url, "SELECT version FROM backend_pause"))["version"] == version
    )


def test_logs_from_an_unrelated_contract_with_the_same_topics_are_ignored(
    anvil_url: str, database_url: str
) -> None:
    _emit(
        anvil_url,
        OTHER_ADDR,
        "PayeeAdded",
        _address_topic(OTHER_PAYEE_ADDR),
        data=encode(["uint64"], [int(time.time()) + 3600]),
    )
    _emit(anvil_url, OTHER_ADDR, "RequestCancelled", REQUEST_ID, _address_topic(SENDER))
    # A real module event makes sure the run finds the module and has something to compare.
    _emit(anvil_url, MODULE_ADDR, "Resumed")
    _mine(anvil_url)

    result, _ = asyncio.run(_index(anvil_url, database_url))

    assert result == {"changed": 1}
    assert (
        asyncio.run(
            _one(
                database_url,
                "SELECT status::text AS s FROM payees WHERE id = $1",
                uuid.UUID(OTHER_PAYEE),
            )
        )["s"]
        == "AwaitingOwner"
    )
    assert (
        asyncio.run(_one(database_url, "SELECT cancel_onchain FROM payment_requests"))[
            "cancel_onchain"
        ]
        == "Pending"
    )


def test_changed_guard_recomputes_coverage(anvil_url: str, database_url: str) -> None:
    _emit(anvil_url, MODULE_ADDR, "Resumed")  # gives the module a deployment block
    _mine(anvil_url)
    asyncio.run(_index(anvil_url, database_url, guard=GUARD))
    before = asyncio.run(_one(database_url, "SELECT coverage::text AS c FROM treasuries"))["c"]
    _emit(anvil_url, SAFE_ADDR, "ChangedGuard", _address_topic(GUARD))
    _mine(anvil_url)

    result, _ = asyncio.run(_index(anvil_url, database_url, guard=GUARD))

    treasury = asyncio.run(
        _one(
            database_url, "SELECT coverage::text AS c, coverage_details::text AS d FROM treasuries"
        )
    )
    assert (before, treasury["c"]) == ("UNKNOWN", "PARTIAL")
    assert "an unexpected guard is enabled" in treasury["d"]
    assert result == {"changed": 1}


def test_catches_up_across_2000_block_chunks(anvil_url: str, database_url: str) -> None:
    # Anvil keeps no deep history for the deployment-block search, so start at block 0.
    asyncio.run(
        _one(
            database_url,
            "INSERT INTO index_cursors (treasury_id, stream, last_block) "
            "SELECT $1, s, 0 FROM unnest(enum_range(NULL::index_stream)) s RETURNING 1",
            uuid.UUID(TREASURY),
        )
    )
    _mine(anvil_url, 10)
    _emit(anvil_url, MODULE_ADDR, "Paused", _address_topic(SENDER))
    _mine(anvil_url, 4500)
    _emit(anvil_url, MODULE_ADDR, "Resumed")
    _mine(anvil_url)

    result, client = asyncio.run(_index(anvil_url, database_url))

    assert result == {"changed": 2}
    # 4,500+ blocks need three chunks of at most 2,000.
    assert client.methods.count("eth_getLogs") >= 3
    assert asyncio.run(_one(database_url, "SELECT paused FROM backend_pause"))["paused"] is False


def test_a_reorged_out_log_is_marked_removed_and_subscribers_hear_about_it(
    anvil_url: str, database_url: str
) -> None:
    _emit(anvil_url, MODULE_ADDR, "Resumed")
    _mine(anvil_url)
    snapshot = _rpc(anvil_url, "evm_snapshot")
    _emit(anvil_url, MODULE_ADDR, "Paused", _address_topic(SENDER))
    _mine(anvil_url)
    heard: list[IndexedEvent] = []

    async def record(_connection: Any, event: IndexedEvent) -> None:
        heard.append(event)

    custom = HandlerRegistry()
    custom.on_event(MODULE, "Paused", record, include_removed=True)
    asyncio.run(_index(anvil_url, database_url, handlers=custom))
    assert [(event.name, event.removed) for event in heard] == [("Paused", False)]

    assert _rpc(anvil_url, "evm_revert", [snapshot])
    _mine(anvil_url, 3)
    result, _ = asyncio.run(_index(anvil_url, database_url, handlers=custom))

    assert result == {"changed": 1}
    assert [(event.name, event.removed) for event in heard] == [("Paused", False), ("Paused", True)]
    assert (
        asyncio.run(
            _one(database_url, "SELECT removed FROM observed_events WHERE event_name = 'Paused'")
        )["removed"]
        is True
    )


def test_event_signatures_match_the_published_topics() -> None:
    # 0x442e... is Safe's well-known ExecutionSuccess(bytes32,uint256) topic.
    assert "0x442e715f626346e8c54381002da614f62bee8d27386535b2521ec8540898556e" in EVENTS[SAFE_EXEC]
    assert "0x" + keccak(text="Paused(address)").hex() in EVENTS[MODULE]
