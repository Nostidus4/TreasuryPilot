from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_signer.store import SignerStore

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

API_ROOT = Path(__file__).parents[2] / "api"
EXECUTOR = bytes([9]) * 20
PLAN = bytes([1]) * 32
STEP = bytes([2]) * 32
PAYLOAD = bytes([3]) * 32


async def _exercise(database_url: str) -> None:
    async def use_signer_role(connection: asyncpg.Connection) -> None:
        await connection.execute("SET ROLE treasurypilot_signer")

    pool = await asyncpg.create_pool(
        database_url.replace("postgresql+asyncpg://", "postgresql://", 1),
        min_size=1,
        max_size=2,
        init=use_signer_role,
    )
    try:
        store = SignerStore(pool)
        reserve = {
            "attestation_nonce": 1,
            "plan_hash": PLAN,
            "step_id": STEP,
            "payload_hash": PAYLOAD,
            "executor": EXECUTOR,
            "pending_nonce": 5,
        }
        first = await store.reserve(**reserve)
        assert (first.transaction_nonce, first.replacement, first.raw_transaction) == (
            5,
            False,
            None,
        )

        # A definitively rejected broadcast frees the nonce for the next attempt.
        await store.release(
            attestation_nonce=1, step_id=STEP, executor=EXECUTOR, transaction_nonce=5
        )
        retry = await store.reserve(**reserve)
        assert (retry.transaction_nonce, retry.replacement) == (5, False)

        # A replay returns the stored hash and raw transaction instead of a fresh reservation.
        await store.record_signed(
            attestation_nonce=1, step_id=STEP, tx_hash="0x" + "ab" * 32, raw_transaction=b"\x02raw"
        )
        replay = await store.reserve(**{**reserve, "pending_nonce": 9})
        assert replay.replacement
        assert (replay.transaction_nonce, replay.tx_hash, replay.raw_transaction) == (
            5,
            "0x" + "ab" * 32,
            b"\x02raw",
        )
    finally:
        await pool.close()


def test_store_persists_signed_transactions_and_releases_rejected_nonces() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise(database_url))
    finally:
        command.downgrade(config, "base")
