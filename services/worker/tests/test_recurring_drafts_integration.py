from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from treasurypilot_api.invoices.requests import _hashes, _snapshot
from treasurypilot_worker.invoices.recurring import generate_due_recurring_drafts
from treasurypilot_worker.locks import create_worker_pool

API_ROOT = Path(__file__).parents[2] / "api"
_USER = uuid.UUID("00000000-0000-7000-8000-000000000001")
_EDITOR = uuid.UUID("00000000-0000-7000-8000-000000000002")
_ORG = uuid.UUID("00000000-0000-7000-8000-000000000010")
_ASSET = uuid.UUID("00000000-0000-7000-8000-000000000030")
_TREASURY = uuid.UUID("00000000-0000-7000-8000-000000000040")
_VENDOR = uuid.UUID("00000000-0000-7000-8000-000000000050")
_PAYEE = uuid.UUID("00000000-0000-7000-8000-000000000060")
_SCHEDULE = uuid.UUID("00000000-0000-7000-8000-000000000070")


async def _seed(database_url: str) -> None:
    engine = create_async_engine(database_url)
    statements = [
        f"INSERT INTO users (id, email) VALUES ('{_USER}', 'recurring@example.com')",
        f"INSERT INTO users (id, email) VALUES ('{_EDITOR}', 'template-editor@example.com')",
        f"INSERT INTO organizations (id, name) VALUES ('{_ORG}', 'Recurring test')",
        "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
        "VALUES (11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', '[\"https://rpc\"]')",
        "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
        f"VALUES ('{_ASSET}', 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
        "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
        f"VALUES ('{_TREASURY}', '{_ORG}', 11155111, '{_ASSET}')",
        "INSERT INTO vendors (id, org_id, name, normalized_ref) "
        f"VALUES ('{_VENDOR}', '{_ORG}', 'Vendor', 'vendor')",
        "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
        f"VALUES ('{_PAYEE}', '{_TREASURY}', '{_ORG}', '{_VENDOR}', 'Main', "
        "decode(repeat('22', 20), 'hex'), 'Proposed')",
        "INSERT INTO recurring_payment_schedules "
        "(id, org_id, treasury_id, chain_id, vendor_id, payee_id, asset_id, invoice_no_template, "
        "amount, cadence, interval, period_index, start_date, next_period, end_date, "
        "due_days_after_issue, created_by, last_edited_by) VALUES "
        f"('{_SCHEDULE}', '{_ORG}', '{_TREASURY}', 11155111, '{_VENDOR}', '{_PAYEE}', "
        f"'{_ASSET}', 'RENT-{{period}}', 123456, 'MONTHLY', 1, 0, '2026-10-01', "
        "'2026-10-01', '2026-12-01', 30, "
        f"'{_USER}', '{_EDITOR}')",
    ]
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


async def _purge_recurring(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            # TRUNCATE skips the append-only row triggers on request_revisions.
            await connection.execute(
                text(
                    "TRUNCATE recurring_payment_periods, recurring_payment_schedules, payment_requests CASCADE"
                )
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for recurring generation integration tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(url))
        yield url
    finally:
        asyncio.run(_purge_recurring(url))  # the 0027 downgrade cannot keep RECURRING rows
        command.downgrade(config, "base")


def test_recurring_job_creates_one_unapproved_draft_per_period(database_url: str) -> None:
    async def scenario() -> None:
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        try:
            async with pool.acquire() as connection:
                first = await generate_due_recurring_drafts(connection, today=date(2026, 10, 14))
                retry = await generate_due_recurring_drafts(connection, today=date(2026, 10, 14))
                assert first == {"generated": 1, "errors": 0}
                assert retry == {"generated": 0, "errors": 0}
                rows = await connection.fetch(
                    "SELECT id, invoice_no, amount, source, status, current_revision, fingerprint, invoice_hash, created_by, last_edited_by "
                    "FROM payment_requests WHERE treasury_id=$1",
                    _TREASURY,
                )
                assert len(rows) == 1
                request = rows[0]
                assert request["invoice_no"] == "RENT-2026-10-01"
                assert int(request["amount"]) == 123456
                assert request["source"] == "RECURRING"
                assert request["status"] == "Draft"
                assert request["current_revision"] == 1
                assert request["created_by"] == _USER
                assert request["last_edited_by"] == _EDITOR
                assert len(request["fingerprint"]) == len(request["invoice_hash"]) == 32
                # The worker re-implements request creation; it must match the API's helpers.
                full = await connection.fetchrow(
                    "SELECT * FROM payment_requests WHERE id=$1", request["id"]
                )
                stored = await connection.fetchval(
                    "SELECT snapshot FROM request_revisions WHERE request_id=$1", request["id"]
                )
                stored = json.loads(stored) if isinstance(stored, str) else stored
                api_row = SimpleNamespace(**dict(full))
                assert stored == _snapshot(api_row)  # type: ignore[arg-type]
                assert (
                    _hashes(api_row, "vendor", bytes.fromhex("11" * 20)) == request["fingerprint"]
                )  # type: ignore[arg-type]
                assert api_row.invoice_hash == request["invoice_hash"]
                assert await connection.fetchval("SELECT count(*) FROM approvals") == 0
                assert await connection.fetchval("SELECT count(*) FROM request_revisions") == 1
                assert (
                    await connection.fetchval(
                        "SELECT count(*) FROM recurring_payment_periods WHERE status='Generated'"
                    )
                    == 1
                )
                next_period = await connection.fetchval(
                    "SELECT next_period FROM recurring_payment_schedules WHERE id=$1", _SCHEDULE
                )
                assert next_period == date(2026, 11, 1)
        finally:
            await pool.close()

    asyncio.run(scenario())


async def _add_schedule(
    connection: object, schedule_id: uuid.UUID, template: str, *, amount: int = 123456
) -> None:
    await connection.execute(  # type: ignore[attr-defined]
        "INSERT INTO recurring_payment_schedules "
        "(id, org_id, treasury_id, chain_id, vendor_id, payee_id, asset_id, invoice_no_template, "
        "amount, cadence, interval, period_index, start_date, next_period, due_days_after_issue, "
        "created_by, last_edited_by) VALUES ($1,$2,$3,11155111,$4,$5,$6,$7,$8,'MONTHLY',1,0,"
        "'2026-10-01','2026-10-01',30,$9,$9)",
        schedule_id,
        _ORG,
        _TREASURY,
        _VENDOR,
        _PAYEE,
        _ASSET,
        template,
        amount,
        _USER,
    )


_STATE = "SELECT status, next_period, pause_reason, period_index FROM recurring_payment_schedules WHERE id=$1"


def test_existing_period_row_does_not_strand_the_schedule(database_url: str) -> None:
    schedule_id = uuid.uuid4()

    async def scenario() -> None:
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        try:
            async with pool.acquire() as connection:
                await _add_schedule(connection, schedule_id, "SKIPPED-{period}")
                await connection.execute(
                    "INSERT INTO recurring_payment_periods "
                    "(id, schedule_id, period_date, status, skipped_by, skipped_at) "
                    "VALUES ($1,$2,'2026-10-01','Skipped',$3,now())",
                    uuid.uuid4(),
                    schedule_id,
                    _USER,
                )
                result = await generate_due_recurring_drafts(connection, today=date(2026, 10, 14))
                assert result["errors"] == 0
                state = await connection.fetchrow(_STATE, schedule_id)
                assert (state["status"], state["next_period"]) == ("Active", date(2026, 11, 1))
                assert (
                    await connection.fetchval(
                        "SELECT count(*) FROM payment_requests WHERE invoice_no='SKIPPED-2026-10-01'"
                    )
                    == 0
                )
        finally:
            await pool.close()

    asyncio.run(scenario())


def test_duplicate_fingerprint_fails_one_period_without_pausing_the_schedule(
    database_url: str,
) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()

    async def scenario() -> None:
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        try:
            async with pool.acquire() as connection:
                await _add_schedule(connection, first, "DUP-{period}")
                await generate_due_recurring_drafts(connection, today=date(2026, 10, 14))
                await _add_schedule(connection, second, "DUP-{period}")
                result = await generate_due_recurring_drafts(connection, today=date(2026, 10, 14))
                assert result["errors"] == 0
                state = await connection.fetchrow(_STATE, second)
                assert (state["status"], state["next_period"]) == ("Active", date(2026, 11, 1))
                period = await connection.fetchrow(
                    "SELECT status, reason, request_id FROM recurring_payment_periods "
                    "WHERE schedule_id=$1",
                    second,
                )
                assert period["status"] == "Failed"
                assert "duplicates active request" in period["reason"]
                assert period["request_id"] is None
        finally:
            await pool.close()

    asyncio.run(scenario())


def test_any_database_error_pauses_the_schedule_with_a_reason(database_url: str) -> None:
    schedule_id = uuid.uuid4()

    async def scenario() -> None:
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        try:
            async with pool.acquire() as connection:
                await connection.execute(
                    "CREATE FUNCTION tp_test_boom() RETURNS trigger LANGUAGE plpgsql AS "
                    "$$ BEGIN IF NEW.invoice_no LIKE 'BOOM-%' THEN "
                    "RAISE EXCEPTION 'boom'; END IF; RETURN NEW; END $$"
                )
                await connection.execute(
                    "CREATE TRIGGER tp_test_boom BEFORE INSERT ON payment_requests "
                    "FOR EACH ROW EXECUTE FUNCTION tp_test_boom()"
                )
                try:
                    await _add_schedule(connection, schedule_id, "BOOM-{period}")
                    result = await generate_due_recurring_drafts(
                        connection, today=date(2026, 10, 14)
                    )
                    assert result["errors"] == 1
                    state = await connection.fetchrow(_STATE, schedule_id)
                    assert state["status"] == "Paused"
                    assert "boom" in state["pause_reason"]
                    # A second run no longer picks it up, so it cannot fail every night.
                    again = await generate_due_recurring_drafts(
                        connection, today=date(2026, 10, 14)
                    )
                    assert again["errors"] == 0
                finally:
                    await connection.execute("DROP TRIGGER tp_test_boom ON payment_requests")
                    await connection.execute("DROP FUNCTION tp_test_boom()")
        finally:
            await pool.close()

    asyncio.run(scenario())
