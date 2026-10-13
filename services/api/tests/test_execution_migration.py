from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

API_ROOT = Path(__file__).parents[1]


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option(
        "sqlalchemy.url",
        (database_url or "postgresql+asyncpg://offline/offline").replace("%", "%%"),
    )
    return config


def test_execution_upgrade_and_downgrade_compile_offline() -> None:
    output = io.StringIO()
    config = alembic_config()
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)
    command.downgrade(config, "head:base", sql=True)

    sql = output.getvalue()
    for table in ("operations", "transactions", "gas_ledger"):
        assert f"CREATE TABLE {table}" in sql
        assert f"DROP TABLE {table}" in sql
    assert "uq_operations_step_id" in sql
    assert "uq_transactions_chain_hash" in sql
    assert "uq_gas_ledger_transaction" in sql


async def _assert_duplicate_step_id_is_rejected(database_url: str) -> None:
    org_id = "00000000-0000-7000-8000-000000000010"
    asset_id = "00000000-0000-7000-8000-000000000030"
    treasury_id = "00000000-0000-7000-8000-000000000040"
    vendor_id = "00000000-0000-7000-8000-000000000050"
    payee_id = "00000000-0000-7000-8000-000000000060"
    request_id = "00000000-0000-7000-8000-000000000070"
    operation_a = "00000000-0000-7000-8000-000000000080"
    operation_b = "00000000-0000-7000-8000-000000000081"
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(f"INSERT INTO organizations (id, name) VALUES ('{org_id}', 'Execution test')")
            )
            await connection.execute(
                text(
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, "
                    "explorer_url, rpc_urls) VALUES "
                    "(11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', "
                    "'[\"https://rpc.example\"]')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                    f"VALUES ('{asset_id}', 11155111, decode(repeat('11', 20), 'hex'), "
                    "'USDC', 6, 'Circle')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES "
                    f"('{treasury_id}', '{org_id}', 11155111, '{asset_id}')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES "
                    f"('{vendor_id}', '{org_id}', 'Execution Vendor', 'execution-vendor')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO payees "
                    "(id, org_id, treasury_id, vendor_id, label, address, status) VALUES "
                    f"('{payee_id}', '{org_id}', '{treasury_id}', '{vendor_id}', 'Main', "
                    "decode(repeat('22', 20), 'hex'), 'Proposed')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO payment_requests "
                    "(id, org_id, treasury_id, chain_id, vendor_id, payee_id, invoice_no, "
                    "issue_date, due_at, amount, asset_id) VALUES "
                    f"('{request_id}', '{org_id}', '{treasury_id}', 11155111, '{vendor_id}', "
                    f"'{payee_id}', 'EXEC-001', '2026-10-01', '2026-10-31', 1000, '{asset_id}')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO operations "
                    "(id, treasury_id, plan_step_id, request_id, step_id, kind, payload, "
                    "idempotency_key) VALUES "
                    f"('{operation_a}', '{treasury_id}', '00000000-0000-7000-8000-000000000090', "
                    f"'{request_id}', decode(repeat('ab', 32), 'hex'), 'PAY', '{{}}'::jsonb, 'attempt-a')"
                )
            )

        with pytest.raises(IntegrityError, match="uq_operations_step_id"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO operations "
                        "(id, treasury_id, plan_step_id, request_id, step_id, kind, payload, "
                        "idempotency_key) VALUES "
                        f"('{operation_b}', '{treasury_id}', '00000000-0000-7000-8000-000000000091', "
                        f"'{request_id}', decode(repeat('ab', 32), 'hex'), 'PAY', '{{}}'::jsonb, 'attempt-b')"
                    )
                )
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL execution migration test",
)
def test_execution_migration_and_unique_step_id_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_assert_duplicate_step_id_is_rejected(database_url))
    finally:
        command.downgrade(config, "base")
