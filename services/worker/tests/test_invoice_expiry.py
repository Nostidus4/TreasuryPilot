import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_worker.config import Settings, get_settings
from treasurypilot_worker.tasks import EXPIRABLE_REQUEST_STATUSES, _expire_invoice_approvals

API_ROOT = Path(__file__).parents[2] / "api"
ORG = uuid.UUID("00000000-0000-7000-8000-000000000010")


def test_settings_read_compose_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TP_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://compose/db")
    assert Settings().database_url == "postgresql+asyncpg://compose/db"
    monkeypatch.setenv("TP_DATABASE_URL", "postgresql+asyncpg://tp/db")
    assert Settings().database_url == "postgresql+asyncpg://tp/db"


def test_sweep_statuses_match_state_machine_expire_rules() -> None:
    state_machine = pytest.importorskip("treasurypilot_api.invoices.state_machine")
    expected = {
        rule.source.value
        for rule in state_machine._RULES
        if rule.action == state_machine.TransitionAction.EXPIRE
    }
    assert set(EXPIRABLE_REQUEST_STATUSES) == expected


async def _sweep(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = await asyncpg.connect(database_url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Sweep')", ORG)
        await conn.execute(
            "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
            "rpc_urls) VALUES (11155111, 'Sepolia', true, 3, 'https://e.test', '[\"https://r\"]')"
        )
        await conn.execute(
            "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) VALUES "
            "('00000000-0000-7000-8000-000000000030', 11155111, decode(repeat('11', 20), 'hex'), "
            "'USDC', 6, 'Circle')"
        )
        await conn.execute(
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES "
            "('00000000-0000-7000-8000-000000000040', $1, 11155111, "
            "'00000000-0000-7000-8000-000000000030')",
            ORG,
        )
        await conn.execute(
            "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES "
            "('00000000-0000-7000-8000-000000000050', $1, 'V', 'v')",
            ORG,
        )
        await conn.execute(
            "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
            "VALUES ('00000000-0000-7000-8000-000000000060', "
            "'00000000-0000-7000-8000-000000000040', $1, "
            "'00000000-0000-7000-8000-000000000050', 'Main', decode(repeat('22', 20), 'hex'), "
            "'Active')",
            ORG,
        )
        ids = {}
        # (status, approval expires_at): only a lapsed Valid approval on a sweepable request expires.
        for name, status, expires in (
            ("lapsed", "Approved", datetime(2000, 1, 1, tzinfo=UTC)),
            ("fresh", "Approved", datetime(2099, 1, 1, tzinfo=UTC)),
            ("paying", "Paying", datetime(2000, 1, 1, tzinfo=UTC)),
        ):
            ids[name] = uuid.uuid4()
            await conn.execute(
                "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
                "payee_id, asset_id, issue_date, due_at, invoice_no, amount, status) VALUES "
                "($1, $2, '00000000-0000-7000-8000-000000000040', 11155111, "
                "'00000000-0000-7000-8000-000000000050', "
                "'00000000-0000-7000-8000-000000000060', "
                "'00000000-0000-7000-8000-000000000030', '2026-10-01', '2026-10-31', $3, 1001, $4)",
                ids[name],
                ORG,
                name,
                status,
            )
            await conn.execute(
                "INSERT INTO approvals (id, request_id, revision, approver_address, typed_data, "
                "signature, expires_at) VALUES ($1, $2, 1, decode(repeat('33', 20), 'hex'), "
                "'{}'::jsonb, decode('01', 'hex'), $3)",
                uuid.uuid4(),
                ids[name],
                expires,
            )
    finally:
        await conn.close()

    monkeypatch.setenv("TP_DATABASE_URL", database_url)
    get_settings.cache_clear()
    assert await _expire_invoice_approvals() == 1
    assert await _expire_invoice_approvals() == 0  # idempotent

    conn = await asyncpg.connect(database_url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        statuses = {
            name: await conn.fetchval("SELECT status FROM payment_requests WHERE id = $1", rid)
            for name, rid in ids.items()
        }
        approvals = {
            name: await conn.fetchval("SELECT status FROM approvals WHERE request_id = $1", rid)
            for name, rid in ids.items()
        }
        event = await conn.fetchrow(
            'SELECT "from", "to", actor_type FROM request_status_events WHERE request_id = $1',
            ids["lapsed"],
        )
    finally:
        await conn.close()
    assert statuses == {"lapsed": "Expired", "fresh": "Approved", "paying": "Paying"}
    assert approvals == {"lapsed": "Expired", "fresh": "Valid", "paying": "Valid"}
    assert tuple(event) == ("Approved", "Expired", "SYSTEM")


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL expiry sweep test",
)
def test_expiry_sweep_runs_against_real_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    monkeypatch.delenv("TP_DATABASE_URL", raising=False)
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_sweep(database_url, monkeypatch))
    finally:
        monkeypatch.delenv("TP_DATABASE_URL", raising=False)
        get_settings.cache_clear()
        command.downgrade(config, "base")
