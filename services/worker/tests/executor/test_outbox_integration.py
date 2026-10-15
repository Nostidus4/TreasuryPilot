"""Outbox executor against PostgreSQL with signer fault injection (EXE-007)."""

from __future__ import annotations

import asyncio
import dataclasses
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from treasurypilot_worker.executor.outbox import (
    SignerRefused,
    SignerUnavailable,
    StepExecution,
    TreasuryPaused,
    execute_step,
)
from treasurypilot_worker.locks import create_worker_pool

API_ROOT = Path(__file__).parents[3] / "api"
CHAIN_ID = 31337
_ORG = "00000000-0000-7000-8000-000000000010"
_ASSET = "00000000-0000-7000-8000-000000000030"
_TREASURY = uuid.UUID("00000000-0000-7000-8000-000000000040")
_VENDOR = "00000000-0000-7000-8000-000000000050"
_PAYEE = "00000000-0000-7000-8000-000000000060"
_REQUEST = uuid.UUID("00000000-0000-7000-8000-000000000070")


class Crash(Exception):
    """The worker died after the signer answered but before the hash was persisted."""


class FakeSigner:
    """Replays by step id like the real signer: the same step always yields the same hash."""

    def __init__(self) -> None:
        self.calls = 0
        self.signed: dict[str, dict[str, Any]] = {}
        self.crash_after_reply = False
        self.fail_with: Exception | None = None

    async def sign_and_send(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        key = request["plan"]["steps"][request["stepSeq"]]["stepId"].removeprefix("0x")
        reply = self.signed.setdefault(
            key,
            {"txHash": "0x" + key[:2] * 32, "nonce": len(self.signed), "from": "0x" + "ab" * 20},
        )
        if self.crash_after_reply:
            raise Crash
        return reply


async def _seed(database_url: str) -> None:
    engine = create_async_engine(database_url)
    statements = [
        f"INSERT INTO organizations (id, name) VALUES ('{_ORG}', 'Outbox test')",
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
        f"'OBX-001', '2026-10-01', '2026-10-31', 1000, '{_ASSET}')",
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
        pytest.skip("TP_TEST_DATABASE_URL is required for the outbox integration tests")
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


def _step() -> StepExecution:
    step_id = uuid.uuid4().bytes * 2
    return StepExecution(
        treasury_id=_TREASURY,
        request_id=_REQUEST,
        plan_step_id=uuid.uuid4(),
        step_id=step_id,
        kind="PAY",
        chain_id=CHAIN_ID,
        sign_request={
            "treasuryId": str(_TREASURY),
            "plan": {"steps": [{"stepId": "0x" + step_id.hex()}]},
            "stepSeq": 0,
            "payload": {"to": "0x" + "33" * 20, "data": "0xdeadbeef"},
        },
    )


async def _rows(database_url: str, step: StepExecution) -> tuple[Any, list[Any]]:
    pool = await create_worker_pool(database_url, min_size=1, max_size=1)
    try:
        operation = await pool.fetchrow(
            "SELECT id, status, attempts, last_error FROM operations WHERE step_id = $1",
            step.step_id,
        )
        transactions = await pool.fetch(
            "SELECT tx_hash, nonce, from_address FROM transactions WHERE operation_id = $1",
            operation["id"],
        )
        return operation, transactions
    finally:
        await pool.close()


async def _run(database_url: str, signer: FakeSigner, step: StepExecution) -> Any:
    pool = await create_worker_pool(database_url, min_size=1, max_size=2)
    try:
        return await execute_step(pool, signer, step)
    finally:
        await pool.close()


def test_happy_path_persists_hash_and_skips_signer_on_rerun(database_url: str) -> None:
    signer, step = FakeSigner(), _step()
    first = asyncio.run(_run(database_url, signer, step))
    again = asyncio.run(_run(database_url, signer, step))

    operation, transactions = asyncio.run(_rows(database_url, step))
    assert first.status == "Submitted" and again == first
    assert signer.calls == 1  # re-running a Submitted operation never reaches the signer
    assert operation["status"] == "Submitted" and operation["attempts"] == 1
    assert len(transactions) == 1
    assert "0x" + bytes(transactions[0]["tx_hash"]).hex() == first.tx_hash


def test_crash_after_signer_reply_is_recovered_by_step_id(database_url: str) -> None:
    signer, step = FakeSigner(), _step()
    signer.crash_after_reply = True
    with pytest.raises(Crash):
        asyncio.run(_run(database_url, signer, step))
    operation, transactions = asyncio.run(_rows(database_url, step))
    assert operation["status"] == "NotSubmitted" and operation["attempts"] == 1
    assert transactions == []  # the outbox row survived the crash; no hash was saved

    signer.crash_after_reply = False
    outcome = asyncio.run(_run(database_url, signer, step))
    operation, transactions = asyncio.run(_rows(database_url, step))
    assert operation["status"] == "Submitted" and operation["attempts"] == 2
    assert len(transactions) == 1 and len(signer.signed) == 1  # one transaction, never two
    assert outcome.tx_hash == "0x" + bytes(transactions[0]["tx_hash"]).hex()


def test_signer_refusal_and_outage_keep_operation_retryable(database_url: str) -> None:
    signer, step = FakeSigner(), _step()
    signer.fail_with = SignerRefused("SIMULATION_REVERTED")
    with pytest.raises(SignerRefused):
        asyncio.run(_run(database_url, signer, step))
    operation, _ = asyncio.run(_rows(database_url, step))
    assert (operation["status"], operation["last_error"]) == ("NotSubmitted", "SIMULATION_REVERTED")

    signer.fail_with = SignerUnavailable("TimeoutError")
    with pytest.raises(SignerUnavailable):
        asyncio.run(_run(database_url, signer, step))

    signer.fail_with = None
    asyncio.run(_run(database_url, signer, step))
    operation, transactions = asyncio.run(_rows(database_url, step))
    assert operation["status"] == "Submitted" and operation["last_error"] is None
    assert len(transactions) == 1


def test_terminal_refusal_abandons_and_unknown_refusal_stays_retryable(database_url: str) -> None:
    signer, step = FakeSigner(), _step()
    signer.fail_with = SignerRefused("PAYLOAD_MISMATCH")
    with pytest.raises(SignerRefused):
        asyncio.run(_run(database_url, signer, step))
    operation, _ = asyncio.run(_rows(database_url, step))
    assert (operation["status"], operation["last_error"]) == ("Abandoned", "PAYLOAD_MISMATCH")
    asyncio.run(_run(database_url, signer, step))  # Abandoned is final: the signer is not called
    assert signer.calls == 1

    other = _step()
    signer.fail_with = SignerRefused("SIMULATION_REVERTED")
    with pytest.raises(SignerRefused):
        asyncio.run(_run(database_url, signer, other))
    operation, _ = asyncio.run(_rows(database_url, other))
    assert operation["status"] == "NotSubmitted"


def test_malformed_reply_is_recorded_and_retryable(database_url: str) -> None:
    class Bad(FakeSigner):
        async def sign_and_send(self, request: dict[str, Any]) -> dict[str, Any]:
            return {"txHash": "0x12", "nonce": 1, "from": "0x" + "ab" * 20}

    step = _step()
    with pytest.raises(SignerUnavailable):
        asyncio.run(_run(database_url, Bad(), step))
    operation, transactions = asyncio.run(_rows(database_url, step))
    assert operation["last_error"] == "MALFORMED_SIGNER_RESPONSE" and transactions == []


def test_step_validation_rejects_mismatches(database_url: str) -> None:
    step = _step()
    wrong_id = dataclasses.replace(step, step_id=b"\x01" * 32)
    wrong_kind = dataclasses.replace(step, kind="BOGUS")
    wrong_treasury = dataclasses.replace(
        step, sign_request={**step.sign_request, "treasuryId": str(uuid.uuid4())}
    )
    for bad in (wrong_id, wrong_kind, wrong_treasury):
        with pytest.raises(ValueError):
            asyncio.run(_run(database_url, FakeSigner(), bad))


def test_paused_treasury_creates_no_operation_and_never_reaches_the_signer(
    database_url: str,
) -> None:
    async def set_pause(paused: bool) -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO backend_pause (treasury_id, org_id, paused, reason) "
                        f"VALUES ('{_TREASURY}', '{_ORG}', {paused}, 'test') "
                        "ON CONFLICT (treasury_id) DO UPDATE SET paused = EXCLUDED.paused"
                    )
                )
        finally:
            await engine.dispose()

    signer, step = FakeSigner(), _step()
    asyncio.run(set_pause(True))
    try:
        with pytest.raises(TreasuryPaused):
            asyncio.run(_run(database_url, signer, step))
        assert signer.calls == 0
        pool_rows = asyncio.run(_count_operations(database_url, step))
        assert pool_rows == 0
    finally:
        asyncio.run(set_pause(False))
    assert asyncio.run(_run(database_url, signer, step)).status == "Submitted"


async def _count_operations(database_url: str, step: StepExecution) -> int:
    pool = await create_worker_pool(database_url, min_size=1, max_size=1)
    try:
        return int(
            await pool.fetchval("SELECT count(*) FROM operations WHERE step_id = $1", step.step_id)
        )
    finally:
        await pool.close()
