"""AGT-011 against real Postgres: the draft is attached to the exception record."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_worker.agent.exception_draft import (
    DraftOutcome,
    ExceptionFacts,
    attach_draft,
    template_draft,
)

API_ROOT = Path(__file__).resolve().parents[3] / "services" / "api"
_USER = uuid.UUID("00000000-0000-7000-8000-000000000001")
_ORG = uuid.UUID("00000000-0000-7000-8000-000000000010")
_OTHER_ORG = uuid.UUID("00000000-0000-7000-8000-000000000011")
_ASSET = uuid.UUID("00000000-0000-7000-8000-000000000030")
_TREASURY = uuid.UUID("00000000-0000-7000-8000-000000000040")
_FACTS = ExceptionFacts(
    amount="12,500", cap="10,000", excess="2,500", daily_used="4,000", daily_remaining_after="7,500"
)


async def _run(url: str, sql: str, *args: object) -> list[asyncpg.Record]:
    connection = await asyncpg.connect(url)
    try:
        return list(await connection.fetch(sql, *args))
    finally:
        await connection.close()


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for exception draft integration tests")
    alembic_url = os.environ["TP_TEST_DATABASE_URL"]
    url = alembic_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", alembic_url.replace("%", "%%"))
    command.upgrade(config, "head")
    for statement in [
        f"INSERT INTO users (id, email) VALUES ('{_USER}', 'draft@example.com')",
        f"INSERT INTO organizations (id, name) VALUES ('{_ORG}', 'Draft test')",
        "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
        "VALUES (11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', '[\"https://rpc\"]')",
        "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
        f"VALUES ('{_ASSET}', 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
        "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
        f"VALUES ('{_TREASURY}', '{_ORG}', 11155111, '{_ASSET}')",
    ]:
        asyncio.run(_run(url, statement))
    try:
        yield url
    finally:
        asyncio.run(_run(url, "TRUNCATE exceptions, payment_requests CASCADE"))
        command.downgrade(config, "base")


def _exception(url: str) -> uuid.UUID:
    request_id, exception_id = uuid.uuid4(), uuid.uuid4()
    asyncio.run(
        _run(
            url,
            "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, asset_id, source, "
            "status, created_by, last_edited_by, onchain_request_id) VALUES ($1, $2, $3, "
            "11155111, $4, 'UPLOAD', 'Draft', $5, $5, decode(repeat('ab', 32), 'hex'))",
            request_id,
            _ORG,
            _TREASURY,
            _ASSET,
            _USER,
        )
    )
    asyncio.run(
        _run(
            url,
            "INSERT INTO exceptions (id, org_id, treasury_id, request_id, mandate_onchain_version, "
            "amount, payee, expiry) VALUES ($1, $2, $3, $4, 1, 12500, decode(repeat('22', 20), "
            "'hex'), now() + interval '72 hours')",
            exception_id,
            _ORG,
            _TREASURY,
            request_id,
        )
    )
    return exception_id


def test_template_draft_is_attached_to_the_exception_record(database_url: str) -> None:
    exception_id = _exception(database_url)
    outcome = DraftOutcome(template_draft(_FACTS), "TEMPLATE", None)

    assert attach_draft(exception_id, _ORG, outcome, database_url=database_url)

    (row,) = asyncio.run(
        _run(
            database_url, "SELECT draft, draft_ai_call_id FROM exceptions WHERE id=$1", exception_id
        )
    )
    stored = json.loads(row["draft"])
    assert stored["source"] == "TEMPLATE" and row["draft_ai_call_id"] is None
    assert stored["draft"]["summary"] == outcome.draft.summary


def test_another_organisations_exception_is_not_touched(database_url: str) -> None:
    exception_id = _exception(database_url)
    outcome = DraftOutcome(template_draft(_FACTS), "TEMPLATE", None)

    assert not attach_draft(exception_id, _OTHER_ORG, outcome, database_url=database_url)
