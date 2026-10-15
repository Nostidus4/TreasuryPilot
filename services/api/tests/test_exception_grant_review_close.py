from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.mandate.governance_service import GovernanceService
from treasurypilot_api.mandate.models import ExceptionStatus, MandateException
from treasurypilot_api.recovery.models import ReviewItem
from treasurypilot_api.recovery.review_queue import ReviewType, create_for_outcome
from treasurypilot_api.treasury.config import PlatformConfiguration

API_ROOT = Path(__file__).parents[1]
USER = uuid.UUID("00000000-0000-7000-8000-000000000001")
ORG = uuid.UUID("00000000-0000-7000-8000-000000000010")
TREASURY = "00000000-0000-7000-8000-000000000040"
REQUEST = uuid.UUID("00000000-0000-7000-8000-000000000070")
EXCEPTION = uuid.UUID("00000000-0000-7000-8000-000000000080")
GRANT_TX = uuid.UUID("00000000-0000-7000-8000-000000000090")


async def _exercise(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    try:
        async with engine.begin() as connection:
            statements = [
                "INSERT INTO users (id, email) VALUES (:user, 'grant@example.test')",
                "INSERT INTO organizations (id, name) VALUES (:org, 'Grant test')",
                "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
                "rpc_urls) VALUES (11155111, 'Sepolia', true, 3, 'https://s.example', "
                "'[\"https://rpc\"]')",
                "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                "VALUES ('00000000-0000-7000-8000-000000000030', 11155111, "
                "decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
                f"INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES ('{TREASURY}', "
                ":org, 11155111, '00000000-0000-7000-8000-000000000030')",
                "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES "
                "('00000000-0000-7000-8000-000000000050', :org, 'Vendor', 'vendor')",
                f"INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
                f"VALUES ('00000000-0000-7000-8000-000000000060', '{TREASURY}', :org, "
                "'00000000-0000-7000-8000-000000000050', 'Main', decode(repeat('22', 20), 'hex'), "
                "'Proposed')",
                "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
                "payee_id, invoice_no, issue_date, due_at, amount, asset_id) VALUES (:request, "
                f":org, '{TREASURY}', 11155111, '00000000-0000-7000-8000-000000000050', "
                "'00000000-0000-7000-8000-000000000060', 'INV-GRANT', '2026-10-01', "
                "'2026-10-31', 1001, '00000000-0000-7000-8000-000000000030')",
                "INSERT INTO governance_txs (id, org_id, treasury_id, chain_id, safe_address, "
                'purpose, calls, "to", value, data, operation, safe_nonce, safe_tx_hash, '
                "threshold, owners_snapshot, status, entity_type, entity_id) VALUES (:tx, :org, "
                f"'{TREASURY}', 11155111, decode(repeat('33', 20), 'hex'), 'EXCEPTION_GRANT', "
                "'[]', decode(repeat('33', 20), 'hex'), 0, '\\x', 0, 1, "
                "decode(repeat('ab', 32), 'hex'), 1, ARRAY[decode(repeat('33', 20), 'hex')], "
                "'Executed', 'exception', :exception)",
                "INSERT INTO exceptions (id, org_id, treasury_id, request_id, "
                "mandate_onchain_version, amount, payee, expiry, status, governance_tx_id, "
                f"created_by) VALUES (:exception, :org, '{TREASURY}', :request, 1, 1001, "
                "decode(repeat('22', 20), 'hex'), now() + interval '1 day', 'Proposed', :tx, "
                ":user)",
            ]
            params = {
                "user": USER,
                "org": ORG,
                "request": REQUEST,
                "exception": EXCEPTION,
                "tx": GRANT_TX,
            }
            for statement in statements:
                await connection.execute(text(statement), params)

        async with sessions() as session, session.begin():
            payment = await session.scalar(select(PaymentRequest))
            assert payment is not None
            item = await create_for_outcome(
                session,
                request=payment,
                outcome=ReviewType.NEEDS_AUTHORITY,
                primary_code="OVER_PER_REQUEST_LIMIT",
                now=datetime(2026, 10, 14, 10, tzinfo=UTC),
            )
            assert item is not None

        service = GovernanceService(sessions, None, PlatformConfiguration(chains=(), manifests=()))
        for _ in range(2):  # the second pass proves it is idempotent
            await service._record_exception_grant(organization_id=ORG, tx_id=GRANT_TX)

        async with sessions() as session:
            exception = await session.get(MandateException, EXCEPTION)
            review = await session.scalar(select(ReviewItem))
        assert exception is not None and review is not None
        assert exception.status == ExceptionStatus.GRANTED
        assert (review.status, review.resolution) == ("Resolved", "EXCEPTION_GRANTED")
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL integration test",
)
def test_executed_exception_grant_marks_granted_and_closes_the_review_item() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise(database_url))
    finally:
        command.downgrade(config, "base")
