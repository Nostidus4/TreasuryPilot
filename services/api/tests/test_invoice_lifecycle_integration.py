from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.access import MemberContext
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.invoices.requests import (
    RenewRequest,
    RequestReason,
    _require_renewer,
    cancel_request,
    reject_request,
    renew_request,
)
from treasurypilot_core.fingerprint import fingerprint
from treasurypilot_core.money import BaseUnits

API_ROOT = Path(__file__).parents[1]
ORG = uuid.UUID("00000000-0000-7000-8000-000000000010")
CREATOR = uuid.UUID("00000000-0000-7000-8000-000000000001")
APPROVER = uuid.UUID("00000000-0000-7000-8000-000000000002")
OWNER = uuid.UUID("00000000-0000-7000-8000-000000000003")
_NAMES = ("cancel_valid", "cancel_none", "reject", "renew", "renew_dup", "renew_ok")
_IDS = {
    name: uuid.UUID(f"00000000-0000-7000-8000-0000000001{i:02d}") for i, name in enumerate(_NAMES)
}
_TREASURY = "'00000000-0000-7000-8000-000000000040'"
_VENDOR = "'00000000-0000-7000-8000-000000000050'"
_PAYEE = "'00000000-0000-7000-8000-000000000060'"
_ASSET = "'00000000-0000-7000-8000-000000000030'"


async def _insert_request(
    conn: AsyncConnection,
    name: str,
    status: str,
    invoice_no: str,
    due: date,
    fp: bytes | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
            "payee_id, asset_id, issue_date, created_by, last_edited_by, invoice_no, due_at, "
            f"amount, status, fingerprint) VALUES (:id, :org, {_TREASURY}, 11155111, {_VENDOR}, "
            f"{_PAYEE}, {_ASSET}, '2026-10-01', :creator, :creator, :inv, :due, 1001, :status, :fp)"
        ),
        {
            "id": _IDS[name],
            "org": ORG,
            "creator": CREATOR,
            "inv": invoice_no,
            "due": due,
            "status": status,
            "fp": fp,
        },
    )


async def _insert_approval(conn: AsyncConnection, name: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO approvals (id, request_id, revision, approver_address, typed_data, "
            "signature, expires_at) VALUES (:id, :rid, 1, decode(repeat('33', 20), 'hex'), "
            "'{}'::jsonb, decode('01', 'hex'), '2099-01-01T00:00:00Z')"
        ),
        {"id": uuid.uuid4(), "rid": _IDS[name]},
    )


async def _seed(conn: AsyncConnection, today: date) -> None:
    for uid, email in ((CREATOR, "c"), (APPROVER, "a"), (OWNER, "o")):
        await conn.execute(
            text("INSERT INTO users (id, email) VALUES (:id, :e)"),
            {"id": uid, "e": f"{email}@example.test"},
        )
    statements = (
        "INSERT INTO organizations (id, name) VALUES (:org, 'Lifecycle')",
        "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
        "VALUES (11155111, 'Sepolia', true, 3, 'https://e.test', '[\"https://rpc\"]')",
        "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) VALUES "
        f"({_ASSET}, 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
        f"INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES ({_TREASURY}, :org, "
        f"11155111, {_ASSET})",
        f"INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES ({_VENDOR}, :org, "
        "'Vendor', 'vendor')",
        "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) VALUES "
        f"({_PAYEE}, {_TREASURY}, :org, {_VENDOR}, 'Main', decode(repeat('22', 20), 'hex'), "
        "'Active')",
    )
    for statement in statements:
        await conn.execute(text(statement), {"org": ORG})
    future, past = today + timedelta(days=30), today - timedelta(days=5)
    # A partially approved request still holds a Valid signature (BR-077).
    await _insert_request(conn, "cancel_valid", "AwaitingApproval", "INV-CV", future)
    await _insert_approval(conn, "cancel_valid")
    await _insert_request(conn, "cancel_none", "AwaitingApproval", "INV-CN", future)
    await _insert_request(conn, "reject", "AwaitingApproval", "INV-RJ", future)
    await _insert_approval(conn, "reject")
    await _insert_request(conn, "renew", "Expired", "INV-RN", past)
    await _insert_request(
        conn,
        "renew_dup",
        "Draft",
        "INV-RN",
        future,
        fingerprint("vendor", "INV-RN", BaseUnits(1001), "0x" + "11" * 20),
    )
    await _insert_request(conn, "renew_ok", "Expired", "INV-OK", past)


async def _scenario(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    try:
        today = datetime.now(UTC).date()
        async with engine.begin() as conn:
            await _seed(conn, today)

        app = FastAPI()
        app.state.request_sessions = sessions
        req = Request({"type": "http", "app": app, "method": "POST", "path": "/"})
        owner = MemberContext(ORG, OWNER, frozenset({"Owner"}))
        approver = MemberContext(ORG, APPROVER, frozenset({"Approver"}))
        operator = MemberContext(ORG, CREATOR, frozenset({"Operator"}))
        why = RequestReason(reason="because")

        async def state(name: str) -> tuple[str, str, list[str]]:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT status, cancel_onchain FROM payment_requests WHERE id = :id"),
                        {"id": _IDS[name]},
                    )
                ).one()
                approvals = (
                    await conn.execute(
                        text("SELECT status FROM approvals WHERE request_id = :id"),
                        {"id": _IDS[name]},
                    )
                ).scalars()
                return row[0], row[1], list(approvals)

        await cancel_request(ORG, _IDS["cancel_valid"], why, req, Response(), '"1"', owner)
        assert await state("cancel_valid") == ("Cancelled", "Pending", ["Cancelled"])
        await cancel_request(ORG, _IDS["cancel_none"], why, req, Response(), '"1"', owner)
        assert await state("cancel_none") == ("Cancelled", "NotNeeded", [])
        await reject_request(ORG, _IDS["reject"], why, req, Response(), '"1"', approver)
        assert await state("reject") == ("Rejected", "NotNeeded", ["Invalidated"])

        past_due = RenewRequest(due_date=today - timedelta(days=1))
        with pytest.raises(AuthFailure) as err:
            await renew_request(ORG, _IDS["renew"], past_due, req, Response(), '"1"', operator)
        assert err.value.code == "DUE_DATE_IN_PAST"
        # Renewing would collide with the active renew_dup fingerprint: 409, not a 500.
        with pytest.raises(AuthFailure) as err:
            await renew_request(
                ORG, _IDS["renew"], RenewRequest(), req, Response(), '"1"', operator
            )
        assert err.value.code == "DUPLICATE_FINGERPRINT"
        assert (await state("renew"))[0] == "Expired"
        result = await renew_request(
            ORG, _IDS["renew_ok"], RenewRequest(due_date=today), req, Response(), '"1"', operator
        )
        assert result["request"]["status"] == "Draft"  # type: ignore[index]
    finally:
        await engine.dispose()


def test_org_admin_cannot_pass_renew_route_guard() -> None:
    admin = MemberContext(ORG, OWNER, frozenset({"OrgAdmin"}))
    with pytest.raises(AuthFailure) as err:
        asyncio.run(_require_renewer(member=admin))
    assert err.value.status == 403


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL lifecycle test",
)
def test_cancel_reject_and_renew_lifecycle_in_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_scenario(database_url))
    finally:
        command.downgrade(config, "base")
