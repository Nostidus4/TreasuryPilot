"""Unknown-operation resolution from chain evidence against PostgreSQL (RCV-002)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_worker.executor.outbox import execute_step
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.recovery.resolve import resolve_operation

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
        self.in_mempool = False
        self.step_used = False
        self.next_nonce = 0

    async def call(self, method: str, params: Sequence[Any]) -> Any:
        return {
            "eth_getTransactionReceipt": self.receipt,
            "eth_getTransactionByHash": {"hash": "0x1"} if self.in_mempool else None,
            "eth_blockNumber": "0x64",
            "eth_call": "0x" + "00" * 31 + ("01" if self.step_used else "00"),
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
) -> tuple[Any, ...]:
    """Register an in-flight operation, resolve it, return (resolution, op, items, step_id)."""

    step_id = uuid.uuid4().bytes * 2
    operation_id = uuid.uuid4()
    pool = await create_worker_pool(url, min_size=1, max_size=2)
    try:
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
        await pool.execute(
            "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, from_address, "
            "status, submitted_at) VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6::transaction_status, $7)",
            operation_id,
            CHAIN_ID,
            tx_hash or uuid.uuid4().bytes * 2,
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
            "SELECT evidence_resolved, status FROM review_items WHERE type = 'UNCERTAIN_TX'"
        )
        return resolution, op, items, step_id
    finally:
        await pool.close()


def test_step_used_on_chain_confirms_without_resubmission(database_url: str) -> None:
    rpc = FakeRpc()
    rpc.step_used = True
    resolution, op, _, _ = asyncio.run(_run(database_url, rpc))
    assert (resolution, op["status"]) == ("Confirmed", "Confirmed")


def test_receipt_or_mempool_is_left_to_the_tracker(database_url: str) -> None:
    rpc = FakeRpc()
    rpc.receipt = {"status": "0x1"}
    assert asyncio.run(_run(database_url, rpc))[0] == "Receipt"
    rpc = FakeRpc()
    rpc.in_mempool = True
    resolution, op, _, _ = asyncio.run(_run(database_url, rpc))
    assert (resolution, op["status"]) == ("Pending", "Unknown")


def test_never_broadcast_is_replayed_with_the_same_step_id(database_url: str) -> None:
    rpc = FakeRpc()
    resolution, op, _, step_id = asyncio.run(_run(database_url, rpc, tx_hash=b"\x00" * 32))
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
    resolution, op, items, _ = asyncio.run(_run(database_url, rpc, age=31))
    assert (resolution, op["status"]) == ("Escalated", "Unknown")
    assert [i["status"] for i in items] == ["Open"]
    # Later chain evidence resolves the operation and unlocks the item's acknowledgment.
    rpc.step_used = True
    _, _, items, _ = asyncio.run(_run(database_url, rpc))
    assert items[0]["evidence_resolved"] is True
