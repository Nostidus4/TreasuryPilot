from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api.invoices.requests import _csv_rows, _import_csv_rows

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

API_ROOT = Path(__file__).parents[1]
ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
USER_ID = uuid.UUID("00000000-0000-7000-8000-000000000001")
ASSET_ID = uuid.UUID("00000000-0000-7000-8000-000000000030")
TREASURY_ID = uuid.UUID("00000000-0000-7000-8000-000000000040")
VENDOR_ID = uuid.UUID("00000000-0000-7000-8000-000000000050")
PAYEE_ID = uuid.UUID("00000000-0000-7000-8000-000000000060")


def _alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _seed(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            for statement in (
                f"INSERT INTO users (id, email) VALUES ('{USER_ID}', 'csv-import@example.com')",
                f"INSERT INTO organizations (id, name) VALUES ('{ORG_ID}', 'CSV import test')",
                "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
                "VALUES (11155111, 'Sepolia', true, 3, 'https://example.test', '[\"https://rpc\"]')",
                f"INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) VALUES "
                f"('{ASSET_ID}', 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
                f"INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES "
                f"('{TREASURY_ID}', '{ORG_ID}', 11155111, '{ASSET_ID}')",
                f"INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES "
                f"('{VENDOR_ID}', '{ORG_ID}', 'Acme', 'acme')",
                "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
                f"VALUES ('{PAYEE_ID}', '{TREASURY_ID}', '{ORG_ID}', '{VENDOR_ID}', 'Main', "
                "decode(repeat('22', 20), 'hex'), 'Proposed')",
            ):
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


async def _import_scenario(database_url: str) -> tuple[float, int, int, int]:
    engine = create_async_engine(database_url)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        template = "vendor_ref,payee_address,invoice_no,issue_date,due_date,amount\n"
        line = "acme,0x" + "22" * 20 + ",INV-{index},2026-10-01,2026-10-15,12.50"
        _, rows = _csv_rows(
            (template + "\n".join(line.format(index=i) for i in range(500))).encode()
        )
        started = time.perf_counter()
        result = await _import_csv_rows(
            organization_id=ORG_ID,
            treasury_id=TREASURY_ID,
            user_id=USER_ID,
            rows=rows,
            file_sha256=bytes.fromhex("ab" * 32),
            dry_run=False,
            factory=sessions,
        )
        elapsed = time.perf_counter() - started
        imported_rows = cast(list[dict[str, object]], result["created"])
        import_errors = cast(list[dict[str, object]], result["errors"])
        assert len(imported_rows) == 500
        assert import_errors == []
        assert all(
            row["flags"] == ["FIRST_PAYMENT_TO_PAYEE", "NO_BASELINE"] for row in imported_rows
        )
        async with sessions() as session:
            flag_count = await session.scalar(text("SELECT count(*) FROM flags"))
        assert flag_count == 1_000

        async with sessions() as session:
            before = await session.scalar(text("SELECT count(*) FROM payment_requests"))
        dry_run_result = await _import_csv_rows(
            organization_id=ORG_ID,
            treasury_id=TREASURY_ID,
            user_id=USER_ID,
            rows=[
                (
                    2,
                    {
                        "vendor_ref": "acme",
                        "payee_address": "0x" + "22" * 20,
                        "invoice_no": "DRY-RUN",
                        "issue_date": "2026-10-01",
                        "due_date": "2026-10-15",
                        "amount": "1.00",
                    },
                )
            ],
            file_sha256=bytes.fromhex("cd" * 32),
            dry_run=True,
            factory=sessions,
        )
        async with sessions() as session:
            after = await session.scalar(text("SELECT count(*) FROM payment_requests"))
            imports = await session.scalar(text("SELECT count(*) FROM csv_imports"))
        assert dry_run_result["importId"] is None and dry_run_result["dryRun"] is True
        assert before == after == 500
        assert imports == 1

        # The second row with a matching fingerprint is rejected while the first is created.
        duplicate_rows = [
            (
                2,
                {
                    "vendor_ref": "acme",
                    "payee_address": "0x" + "22" * 20,
                    "invoice_no": "PAIR",
                    "issue_date": "2026-10-01",
                    "due_date": "2026-10-15",
                    "amount": "1.00",
                },
            ),
            (
                3,
                {
                    "vendor_ref": "acme",
                    "payee_address": "0x" + "22" * 20,
                    "invoice_no": "PAIR",
                    "issue_date": "2026-10-01",
                    "due_date": "2026-10-15",
                    "amount": "1.00",
                },
            ),
        ]
        duplicate_result = await _import_csv_rows(
            organization_id=ORG_ID,
            treasury_id=TREASURY_ID,
            user_id=USER_ID,
            rows=duplicate_rows,
            file_sha256=bytes.fromhex("ef" * 32),
            dry_run=False,
            factory=sessions,
        )
        duplicate_created = cast(list[dict[str, object]], duplicate_result["created"])
        duplicate_errors = cast(list[dict[str, object]], duplicate_result["errors"])
        assert len(duplicate_created) == 1
        assert duplicate_errors[0]["code"] == "DUPLICATE_FINGERPRINT"
        base = {
            "vendor_ref": "acme",
            "payee_address": "0x" + "22" * 20,
            "issue_date": "2026-10-01",
            "due_date": "2026-10-15",
            "amount": "12.50",
        }
        mixed_result = await _import_csv_rows(
            organization_id=ORG_ID,
            treasury_id=TREASURY_ID,
            user_id=USER_ID,
            rows=[
                (2, {**base, "invoice_no": "INV-0"}),  # fingerprint already active in the DB
                (3, {**base, "invoice_no": "NUL", "note": "a\x00b"}),
                (4, {**base, "invoice_no": "FRESH"}),
            ],
            file_sha256=bytes.fromhex("01" * 32),
            dry_run=True,
            factory=sessions,
        )
        mixed_errors = cast(list[dict[str, object]], mixed_result["errors"])
        assert [(e["row"], e["code"]) for e in mixed_errors] == [
            (2, "DUPLICATE_FINGERPRINT"),
            (3, "CSV_NUL_BYTE"),
        ]
        assert [c["row"] for c in cast(list[dict[str, object]], mixed_result["created"])] == [4]
        async with sessions() as session:
            count = await session.scalar(text("SELECT count(*) FROM payment_requests"))
            imports = await session.scalar(text("SELECT count(*) FROM csv_imports"))
        return elapsed, count or 0, imports or 0, len(duplicate_errors)
    finally:
        await engine.dispose()


def test_csv_import_500_rows_and_dry_run_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(database_url))
        elapsed, request_count, import_count, errors = asyncio.run(_import_scenario(database_url))
    finally:
        command.downgrade(config, "base")

    assert elapsed < 10
    assert request_count == 501
    assert import_count == 2
    assert errors == 1
