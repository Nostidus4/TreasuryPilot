from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from eth_hash.auto import keccak
from fastapi import FastAPI, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess
from treasurypilot_api.invoices.onchain_cancel import confirm_onchain_cancel
from treasurypilot_api.invoices.requests import (
    RenewRequest,
    RequestReason,
    _require_renewer,
    cancel_request,
    get_cancel_transaction,
    reject_request,
    renew_request,
)
from treasurypilot_api.mandate.models import GovernanceTx
from treasurypilot_core.fingerprint import fingerprint
from treasurypilot_core.money import BaseUnits

API_ROOT = Path(__file__).parents[1]
ORG = uuid.UUID("00000000-0000-7000-8000-000000000010")
CREATOR = uuid.UUID("00000000-0000-7000-8000-000000000001")
APPROVER = uuid.UUID("00000000-0000-7000-8000-000000000002")
OWNER = uuid.UUID("00000000-0000-7000-8000-000000000003")
ONCHAIN_ID = bytes.fromhex("bb" * 32)
MODULE = bytes.fromhex("aa" * 20)
CANCEL_SELECTOR = "0x" + keccak(b"cancelRequest(bytes32)")[:4].hex()
_NAMES = ("cancel_valid", "cancel_none", "reject", "renew", "renew_dup", "renew_ok")
_IDS = {
    name: uuid.UUID(f"00000000-0000-7000-8000-0000000001{i:02d}") for i, name in enumerate(_NAMES)
}
_TREASURY = "'00000000-0000-7000-8000-000000000040'"
_VENDOR = "'00000000-0000-7000-8000-000000000050'"
_PAYEE = "'00000000-0000-7000-8000-000000000060'"
_ASSET = "'00000000-0000-7000-8000-000000000030'"


def _member(user_id: uuid.UUID, role: str) -> MemberAccess:
    return MemberAccess(
        access=SimpleNamespace(user=SimpleNamespace(id=user_id)),  # type: ignore[arg-type]
        organization_id=ORG,
        roles=frozenset({role}),
    )


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
            "fp": fp or hashlib.sha256(name.encode()).digest(),
        },
    )
    await conn.execute(
        text(
            "INSERT INTO request_revisions (id, request_id, revision, snapshot) "
            "VALUES (gen_random_uuid(), :id, 1, '{}')"
        ),
        {"id": _IDS[name]},
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
        f"INSERT INTO treasuries (id, org_id, chain_id, asset_id, module_address) VALUES "
        f"({_TREASURY}, :org, 11155111, {_ASSET}, decode(repeat('aa', 20), 'hex'))",
        f"INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES ({_VENDOR}, :org, "
        "'Vendor', 'vendor')",
        "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status, "
        "oob_verified_by, oob_verified_at, oob_method, oob_note, active_from) VALUES "
        f"({_PAYEE}, {_TREASURY}, :org, {_VENDOR}, 'Main', decode(repeat('22', 20), 'hex'), "
        f"'Active', '{CREATOR}', now(), 'PHONE', 'verified', now())",
    )
    for statement in statements:
        await conn.execute(text(statement), {"org": ORG})
    future, past = today + timedelta(days=30), today - timedelta(days=5)
    # An approved request holds a Valid signature, so cancelling it owes an on-chain cancel (BR-077).
    await _insert_request(conn, "cancel_valid", "Approved", "INV-CV", future)
    await _insert_approval(conn, "cancel_valid")
    await conn.execute(
        text("UPDATE payment_requests SET onchain_request_id = :rid WHERE id = :id"),
        {"rid": ONCHAIN_ID, "id": _IDS["cancel_valid"]},
    )
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


class _FakeGovernance:
    """Stands in for GovernanceService, which needs a Safe RPC; stores the row like the real one."""

    def __init__(self, sessions: Any) -> None:
        self._sessions = sessions
        self.created = 0

    async def create(self, *, calls: list[Any], **kwargs: Any) -> dict[str, Any]:
        self.created += 1
        async with self._sessions() as session, session.begin():
            session.add(
                GovernanceTx(
                    org_id=kwargs["organization_id"],
                    treasury_id=kwargs["treasury_id"],
                    chain_id=11155111,
                    safe_address=bytes.fromhex("11" * 20),
                    purpose=kwargs["purpose"],
                    calls=[call.as_json() for call in calls],
                    to=calls[0].to,
                    value=0,
                    data=calls[0].data,
                    operation=0,
                    safe_nonce=0,
                    safe_tx_hash=bytes(32),
                    threshold=1,
                    owners_snapshot=[bytes.fromhex("12" * 20)],
                    created_by=kwargs["user_id"],
                    updated_by=kwargs["user_id"],
                )
            )
        return {"data": "0x" + calls[0].data.hex()}

    async def get(self, **kwargs: Any) -> dict[str, Any]:
        return {"data": CANCEL_SELECTOR + ONCHAIN_ID.hex()}


async def _scenario(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    try:
        today = datetime.now(UTC).date()
        async with engine.begin() as conn:
            await _seed(conn, today)

        app = FastAPI()
        app.state.request_sessions = sessions
        governance = _FakeGovernance(sessions)
        app.state.governance_service = governance
        req = Request({"type": "http", "app": app, "method": "POST", "path": "/"})
        owner = _member(OWNER, "Owner")
        approver = _member(APPROVER, "Approver")
        operator = _member(CREATOR, "Operator")
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
        # Approver wallet path: plain module call; Owner path: Safe transaction, reused while open.
        call = await get_cancel_transaction(ORG, _IDS["cancel_valid"], req, approver)
        assert call == {
            "to": "0x" + MODULE.hex(),
            "data": CANCEL_SELECTOR + ONCHAIN_ID.hex(),
        }
        first = await get_cancel_transaction(ORG, _IDS["cancel_valid"], req, owner)
        again = await get_cancel_transaction(ORG, _IDS["cancel_valid"], req, owner)
        assert first == again
        assert first["safeTx"]["data"] == CANCEL_SELECTOR + ONCHAIN_ID.hex()  # type: ignore[index]
        assert governance.created == 1
        await cancel_request(ORG, _IDS["cancel_none"], why, req, Response(), '"1"', owner)
        assert await state("cancel_none") == ("Cancelled", "NotNeeded", [])
        with pytest.raises(AuthFailure) as err:
            await get_cancel_transaction(ORG, _IDS["cancel_none"], req, owner)
        assert err.value.code == "CANCEL_NOT_NEEDED"

        # RequestCancelled sync: only the owning module's Pending request confirms, once.
        tx_hash = bytes.fromhex("cc" * 32)
        other_module = bytes.fromhex("dd" * 20)
        async with sessions() as session, session.begin():
            assert not await confirm_onchain_cancel(
                session, module_address=other_module, request_id=ONCHAIN_ID, tx_hash=tx_hash
            )
            assert await confirm_onchain_cancel(
                session, module_address=MODULE, request_id=ONCHAIN_ID, tx_hash=tx_hash
            )
        async with sessions() as session, session.begin():
            assert not await confirm_onchain_cancel(
                session, module_address=MODULE, request_id=ONCHAIN_ID, tx_hash=tx_hash
            )
        assert await state("cancel_valid") == ("Cancelled", "Confirmed", ["Cancelled"])
        with pytest.raises(AuthFailure) as err:
            await get_cancel_transaction(ORG, _IDS["cancel_valid"], req, approver)
        assert err.value.code == "CANCEL_NOT_NEEDED"
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
    admin = _member(OWNER, "OrgAdmin")
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
