from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Response
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess
from treasurypilot_api.invoices.requests import (
    RequestCreate,
    create_request,
    get_request,
    list_requests,
)
from treasurypilot_api.mandate.vendors import SqlAlchemyVendorRepository

API_ROOT = Path(__file__).parents[1]
_USER = uuid.UUID("00000000-0000-7000-8000-000000000001")
_ORG = uuid.UUID("00000000-0000-7000-8000-000000000010")
_OTHER_ORG = uuid.UUID("00000000-0000-7000-8000-000000000011")
_ASSET = uuid.UUID("00000000-0000-7000-8000-000000000030")
_TREASURY = uuid.UUID("00000000-0000-7000-8000-000000000040")
_VENDOR = uuid.UUID("00000000-0000-7000-8000-000000000050")
_BARE_VENDOR = uuid.UUID("00000000-0000-7000-8000-000000000051")
_PAYEE = uuid.UUID("00000000-0000-7000-8000-000000000060")


def _member(org: uuid.UUID, role: str = "VIEWER") -> MemberAccess:
    return MemberAccess(
        access=SimpleNamespace(user=SimpleNamespace(id=_USER)),  # type: ignore[arg-type]
        organization_id=org,
        roles=frozenset({role}),
    )


async def _seed(database_url: str) -> None:
    engine = create_async_engine(database_url)
    statements = [
        f"INSERT INTO users (id, email, display_name) VALUES ('{_USER}', 'r@example.com', 'Rita')",
        f"INSERT INTO organizations (id, name) VALUES ('{_ORG}', 'Reads'), "
        f"('{_OTHER_ORG}', 'Other')",
        "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
        "VALUES (11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', '[\"https://rpc\"]')",
        "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
        f"VALUES ('{_ASSET}', 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
        "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
        f"VALUES ('{_TREASURY}', '{_ORG}', 11155111, '{_ASSET}')",
        "INSERT INTO vendors (id, org_id, name, normalized_ref) "
        f"VALUES ('{_VENDOR}', '{_ORG}', 'Vendor', 'vendor'), "
        f"('{_BARE_VENDOR}', '{_ORG}', 'Bare', 'bare')",
        "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status, "
        "oob_verified_by, oob_verified_at, oob_method, oob_note, active_from) VALUES "
        f"('{_PAYEE}', '{_TREASURY}', '{_ORG}', '{_VENDOR}', 'Main', "
        f"decode(repeat('22', 20), 'hex'), 'Active', '{_USER}', now(), 'PHONE', 'verified', now())",
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
        pytest.skip("TP_TEST_DATABASE_URL is required for the PostgreSQL request read tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    if "test" not in (make_url(url).database or "").lower():
        pytest.skip("TP_TEST_DATABASE_URL must point at a database whose name contains 'test'")
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(url))
        yield url
    finally:
        command.downgrade(config, "base")


def _run(database_url: str, scenario: Callable[[async_sessionmaker[AsyncSession]], Any]) -> Any:
    async def main() -> Any:
        engine = create_async_engine(database_url)
        try:
            return await scenario(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    return asyncio.run(main())


def _http(sessions: async_sessionmaker[AsyncSession]) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(request_sessions=sessions)))


async def _create(sessions: async_sessionmaker[AsyncSession], invoice_no: str, amount: str) -> str:
    payload = RequestCreate(
        treasury_id=_TREASURY,
        vendor_id=_VENDOR,
        payee_id=_PAYEE,
        invoice_no=invoice_no,
        issue_date=date(2026, 10, 1),
        due_date=date(2026, 10, 31),
        amount=amount,
        asset_id=_ASSET,
    )
    member = _member(_ORG, "OPERATOR")
    result = await create_request(
        _ORG, payload, _http(sessions), Response(), f"key-{invoice_no}", member
    )
    return str(result["request"]["id"])


def test_list_and_detail(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        http = _http(sessions)
        first = await _create(sessions, "L-1", "145.25")  # 145250000: Decimal prints 1.4525E+8
        await _create(sessions, "L-2", "7")
        async with sessions() as session, session.begin():
            await session.execute(
                text("UPDATE payment_requests SET status = 'Rejected' WHERE invoice_no = 'L-2'")
            )

        def mine(result: dict[str, object]) -> list[Any]:
            return [i for i in result["items"] if i["invoiceNumber"].startswith("L-")]  # type: ignore[attr-defined]

        items = mine(await list_requests(_ORG, http, None, None, 200, _member(_ORG)))
        assert [item["invoiceNumber"] for item in items] == ["L-2", "L-1"]
        by_no = {item["invoiceNumber"]: item for item in items}
        assert by_no["L-1"]["amount"] == "145250000"
        assert by_no["L-1"]["vendorName"] == "Vendor"
        assert by_no["L-1"]["payeeAddress"] == "0x" + "22" * 20
        assert by_no["L-1"]["createdBy"] == {"id": str(_USER), "name": "Rita"}

        drafts = mine(await list_requests(_ORG, http, "Draft", None, 200, _member(_ORG)))
        assert [i["invoiceNumber"] for i in drafts] == ["L-1"]
        both = mine(
            await list_requests(_ORG, http, "Draft,Rejected", _TREASURY, 200, _member(_ORG))
        )
        assert len(both) == 2
        other_treasury = await list_requests(_ORG, http, None, uuid.uuid4(), 200, _member(_ORG))
        assert other_treasury["items"] == []

        detail = await get_request(_ORG, uuid.UUID(first), http, _member(_ORG))
        assert detail["amount"] == "145250000"
        assert detail["version"] == "1"
        assert detail["cancelOnchain"] == "NOT_NEEDED"
        assert detail["options"][-1] == {  # type: ignore[index]
            "kind": "STANDARD",
            "payBy": "2026-10-31",
            "amount": "145250000",
            "saving": "0",
        }
        assert len(detail["revisions"]) == 1  # type: ignore[arg-type]

    _run(database_url, scenario)


def test_status_mapping_and_filter(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        http = _http(sessions)
        await _create(sessions, "M-PAY", "1")
        await _create(sessions, "M-EXP", "2")
        async with sessions() as session, session.begin():
            for no, status in (("M-PAY", "Paying"), ("M-EXP", "Expired")):
                await session.execute(
                    text(
                        f"UPDATE payment_requests SET status = '{status}' WHERE invoice_no = '{no}'"
                    )
                )

        async def statuses(filter_: str | None) -> dict[str, str]:
            result = await list_requests(_ORG, http, filter_, None, 200, _member(_ORG))
            return {
                i["invoiceNumber"]: i["status"]  # type: ignore[index]
                for i in result["items"]  # type: ignore[attr-defined]
                if i["invoiceNumber"].startswith("M-")  # type: ignore[index]
            }

        assert await statuses(None) == {"M-PAY": "InFlight", "M-EXP": "Cancelled"}
        assert await statuses("InFlight") == {"M-PAY": "InFlight"}
        assert await statuses("Cancelled") == {"M-EXP": "Cancelled"}
        assert await statuses("Paying") == {"M-PAY": "InFlight"}  # backend names still accepted
        assert await statuses("Paid") == {}

    _run(database_url, scenario)


def test_invalid_status_is_422(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        with pytest.raises(AuthFailure) as bad:
            await list_requests(_ORG, _http(sessions), "Nope", None, 200, _member(_ORG))
        assert bad.value.status == 422
        assert bad.value.code == "STATUS_INVALID"

    _run(database_url, scenario)


def test_other_org_sees_nothing(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        http = _http(sessions)
        request_id = await _create(sessions, "INV-ISO", "5")
        other = _member(_OTHER_ORG)
        assert (await list_requests(_OTHER_ORG, http, None, None, 200, other))["items"] == []
        with pytest.raises(AuthFailure) as missing:
            await get_request(_OTHER_ORG, uuid.UUID(request_id), http, other)
        assert missing.value.status == 404
        with pytest.raises(AuthFailure) as unknown:
            await get_request(_ORG, uuid.uuid4(), http, _member(_ORG))
        assert unknown.value.status == 404

    _run(database_url, scenario)


def test_vendor_list_carries_payee(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        rows = await SqlAlchemyVendorRepository(sessions).list_vendors(organization_id=_ORG)
        by_name = {row.name: row for row in rows}
        assert by_name["Vendor"].payee_address == "0x" + "22" * 20
        assert by_name["Vendor"].payee_status == "Active"
        assert by_name["Vendor"].payee_id is not None
        assert by_name["Bare"].payee_address is None
        assert by_name["Bare"].payee_id is None
        # Scoped to another treasury, the payee is not offered.
        scoped = await SqlAlchemyVendorRepository(sessions).list_vendors(
            organization_id=_ORG, treasury_id=uuid.uuid4()
        )
        assert all(row.payee_id is None for row in scoped)
        mine = await SqlAlchemyVendorRepository(sessions).list_vendors(
            organization_id=_ORG, treasury_id=_TREASURY
        )
        assert {row.name: row.payee_id is not None for row in mine}["Vendor"]

    _run(database_url, scenario)
