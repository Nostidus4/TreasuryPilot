from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

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
