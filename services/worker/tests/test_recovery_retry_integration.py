"""An exhausted retry becomes exactly one open INFRA review item (RCV-005)."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.recovery.review_queue import create_for_outcome
from treasurypilot_worker.chain.rpc import RpcUnavailable
from treasurypilot_worker.recovery.retry import OperationIds, Remedy, Stop, run_with_retry

API_ROOT = Path(__file__).parents[2] / "api"
ORG = uuid.UUID("00000000-0000-7000-8000-000000000010")
REQUEST = uuid.UUID("00000000-0000-7000-8000-000000000070")
SEED = [
    "INSERT INTO organizations (id, name) VALUES (:org, 'Retry test')",
    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) VALUES (11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', '[\"https://rpc\"]')",
    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) VALUES ('00000000-0000-7000-8000-000000000030', 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES ('00000000-0000-7000-8000-000000000040', :org, 11155111, '00000000-0000-7000-8000-000000000030')",
    "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES ('00000000-0000-7000-8000-000000000050', :org, 'Vendor', 'vendor')",
    "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) VALUES ('00000000-0000-7000-8000-000000000060', '00000000-0000-7000-8000-000000000040', :org, '00000000-0000-7000-8000-000000000050', 'Main', decode(repeat('22', 20), 'hex'), 'Proposed')",
    "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, invoice_no, issue_date, due_at, amount, asset_id) VALUES (:request, :org, '00000000-0000-7000-8000-000000000040', 11155111, '00000000-0000-7000-8000-000000000050', '00000000-0000-7000-8000-000000000060', 'INV-RETRY', '2026-10-01', '2026-10-31', 1001, '00000000-0000-7000-8000-000000000030')",
]


async def _exercise(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    ids = OperationIds(str(REQUEST), "step-1", "op-1", "key-1")
    seen: list[OperationIds] = []

    async def always_down(ids: OperationIds, attempt: int, remedy: Remedy) -> None:
        seen.append(ids)
        raise RpcUnavailable("503")

    async def no_sleep(seconds: float) -> None: ...

    try:
        async with engine.begin() as connection:
            for statement in SEED:
                await connection.execute(text(statement), {"org": ORG, "request": REQUEST})
        stop = await run_with_retry(always_down, ids, sleep=no_sleep)
        assert isinstance(stop, Stop) and len(seen) == 6 and set(seen) == {ids}
        async with sessions() as session, session.begin():
            payment = await session.scalar(select(PaymentRequest))
            assert payment is not None and str(payment.id) == ids.request_id
            for _ in range(2):  # a re-reported stop shares one item
                item = await create_for_outcome(
                    session,
                    request=payment,
                    outcome=stop.review.kind,
                    primary_code=stop.review.primary_code,
                )
        assert item is not None
        assert (item.type, item.primary_code, item.status) == ("INFRA", "RETRY_EXHAUSTED", "Open")
    finally:
        await engine.dispose()


@pytest.mark.skipif("TP_TEST_DATABASE_URL" not in os.environ, reason="needs TP_TEST_DATABASE_URL")
def test_exhausted_retry_creates_one_open_infra_review_item() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise(database_url))
    finally:
        command.downgrade(config, "base")
