from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api.audit.events import AuditEvent
from treasurypilot_api.compliance.screening import build_screening_service
from treasurypilot_api.mandate.models import OobMethod, ScreeningResult
from treasurypilot_api.mandate.payees import (
    NotAwaitingOwner,
    PayeeExists,
    SqlAlchemyPayeeRepository,
)
from treasurypilot_api.mandate.vendors import (
    SqlAlchemyVendorRepository,
    VendorHasPayees,
    VendorRefExists,
)

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

API_ROOT = Path(__file__).parents[1]


def alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
USER_ID = uuid.UUID("00000000-0000-7000-8000-000000000001")
TREASURY_ID = uuid.UUID("00000000-0000-7000-8000-000000000040")
CLEAN = bytes.fromhex("ab" * 20)
LISTED = bytes.fromhex("000000000000000000000000000000000000dead")  # in the fixture list


async def _seed(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as c:
            for sql in (
                f"INSERT INTO users (id, email) VALUES ('{USER_ID}', 'payees@example.com')",
                f"INSERT INTO organizations (id, name) VALUES ('{ORG_ID}', 'Payees test')",
                "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
                "rpc_urls) VALUES (11155111, 'Sepolia', true, 3, 'https://e', '[\"https://rpc\"]')",
                "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) VALUES "
                "('00000000-0000-7000-8000-000000000030', 11155111, "
                "decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
                "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES "
                f"('{TREASURY_ID}', '{ORG_ID}', 11155111, '00000000-0000-7000-8000-000000000030')",
            ):
                await c.execute(text(sql))
    finally:
        await engine.dispose()


async def _scenario(database_url: str) -> list[AuditEvent]:
    events: list[AuditEvent] = []

    async def audit(_: object, event: AuditEvent) -> None:
        events.append(event)

    engine = create_async_engine(database_url)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        vendors = SqlAlchemyVendorRepository(sessions, audit)
        payees = SqlAlchemyPayeeRepository(sessions, audit)
        screening = build_screening_service("test", sessions)  # DB fixture provider

        vendor = await vendors.create_vendor(
            organization_id=ORG_ID, user_id=USER_ID, name="Acme", normalized_ref="acme",
            tax_id=b"enc", contact=None, notes=None,
        )  # fmt: skip
        with pytest.raises(VendorRefExists):
            await vendors.create_vendor(
                organization_id=ORG_ID, user_id=USER_ID, name="ACME", normalized_ref="acme",
                tax_id=None, contact=None, notes=None,
            )  # fmt: skip

        async def propose(address: bytes) -> ScreeningResult:
            payee = await payees.propose(
                organization_id=ORG_ID, treasury_id=TREASURY_ID, vendor_id=vendor.id,
                user_id=USER_ID, label="Main", address=address,
            )  # fmt: skip
            record = await screening.screen(
                organization_id=ORG_ID, address=address, chain_id=11155111, payee_id=payee.id
            )
            await payees.finish_screening(
                organization_id=ORG_ID, treasury_id=TREASURY_ID, payee_id=payee.id,
                user_id=USER_ID, result=record.result, provider=record.provider,
            )  # fmt: skip
            return record.result

        assert await propose(CLEAN) == ScreeningResult.CLEAR
        with pytest.raises(PayeeExists):
            await payees.propose(
                organization_id=ORG_ID, treasury_id=TREASURY_ID, vendor_id=vendor.id,
                user_id=USER_ID, label="Dup", address=CLEAN,
            )  # fmt: skip
        assert await propose(LISTED) == ScreeningResult.HIT
        # A failed address can be proposed again (and is blocked again).
        assert await propose(LISTED) == ScreeningResult.HIT

        rows = await payees.list_payees(organization_id=ORG_ID, treasury_id=TREASURY_ID)
        assert rows is not None
        by_status = sorted(r.status for r in rows)
        assert by_status == ["AwaitingOwner", "ScreeningFailed", "ScreeningFailed"]
        clear = next(r for r in rows if r.status == "AwaitingOwner")
        assert clear.screening is not None and clear.screening.result == ScreeningResult.CLEAR

        failed = next(r for r in rows if r.status == "ScreeningFailed")
        with pytest.raises(NotAwaitingOwner):
            await payees.verify_oob(
                organization_id=ORG_ID, treasury_id=TREASURY_ID, payee_id=failed.id,
                user_id=USER_ID, method=OobMethod.PHONE, note="x", at=datetime.now(UTC),
            )  # fmt: skip
        verified = await payees.verify_oob(
            organization_id=ORG_ID, treasury_id=TREASURY_ID, payee_id=clear.id,
            user_id=USER_ID, method=OobMethod.IN_PERSON, note="met CFO", at=datetime.now(UTC),
        )  # fmt: skip
        assert verified is not None and verified.oob_method == "IN_PERSON"

        with pytest.raises(VendorHasPayees):
            await vendors.delete_vendor(
                organization_id=ORG_ID, user_id=USER_ID, vendor_id=vendor.id
            )
        # Another tenant sees nothing.
        assert await vendors.get_vendor(organization_id=uuid.uuid4(), vendor_id=vendor.id) is None
    finally:
        await engine.dispose()
    return events


def test_vendor_and_payee_repositories_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(database_url))
        events = asyncio.run(_scenario(database_url))
    finally:
        command.downgrade(config, "base")

    actions = [e.action for e in events]
    assert actions.count("payee.proposed") == 3
    assert actions.count("payee.screening_failed") == 2
    assert "payee.oob_verified" in actions and "vendor.created" in actions
