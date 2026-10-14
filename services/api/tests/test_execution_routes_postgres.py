"""Plan timeline reads against the persisted attestation and operation records."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from sqlalchemy import text

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.execution.models import TransactionCrosscheck
from treasurypilot_api.execution.routes import (
    _plan_status,
    _step_amount,
    _step_verification,
    get_execution_plan,
    list_execution_plans,
    router,
)
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess

API_ROOT = Path(__file__).parents[1]
ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
OTHER_ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000011")
TREASURY_ID = uuid.UUID("00000000-0000-7000-8000-000000000040")
ASSET_ID = uuid.UUID("00000000-0000-7000-8000-000000000030")
VENDOR_ID = uuid.UUID("00000000-0000-7000-8000-000000000050")
PAYEE_ID = uuid.UUID("00000000-0000-7000-8000-000000000060")
REQUEST_ID = uuid.UUID("00000000-0000-7000-8000-000000000070")
PLAN_ID = uuid.UUID("00000000-0000-7000-8000-000000000080")
OPERATION_ID = uuid.UUID("00000000-0000-7000-8000-000000000090")
TRANSACTION_ID = uuid.UUID("00000000-0000-7000-8000-000000000091")
PLAN_STEP_ID = uuid.UUID("00000000-0000-7000-8000-000000000092")
STEP_ID = bytes.fromhex("33" * 32)


def test_step_amount_uses_the_signed_operation_payload() -> None:
    operation = SimpleNamespace(payload={"amountBaseUnits": "975", "amount": "1000"})
    assert _step_amount(operation) == "975"
    assert _step_amount(SimpleNamespace(payload={})) is None


def test_receipt_verification_requires_a_completed_crosscheck() -> None:
    assert _step_verification(TransactionCrosscheck.NOT_RUN) is None
    assert _step_verification(TransactionCrosscheck.MATCH) == "VERIFIED"
    assert _step_verification(TransactionCrosscheck.MISMATCH) == "MISMATCH"


def test_plan_status_only_claims_states_supported_by_persisted_rows() -> None:
    assert _plan_status(["Planned"], 1) == "Proposed"
    assert _plan_status(["Pending"], 1) == "Executing"
    assert _plan_status(["Confirmed"], 1) == "Unknown"
    assert _plan_status(["Failed"], 1) == "Unknown"
    assert _plan_status(["Pending"], 2) == "Unknown"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _seed(database_url: str) -> None:
    engine, _sessions = create_session_factory(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO organizations (id, name) VALUES (:id, 'Plan route test')"),
                {"id": ORG_ID},
            )
            await connection.execute(
                text("INSERT INTO organizations (id, name) VALUES (:id, 'Other org')"),
                {"id": OTHER_ORG_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
                    "VALUES (31337, 'Anvil', true, 3, 'https://explorer.invalid', '[\"http://rpc\"]')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                    "VALUES (:id, 31337, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')"
                ),
                {"id": ASSET_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
                    "VALUES (:id, :org, 31337, :asset)"
                ),
                {"id": TREASURY_ID, "org": ORG_ID, "asset": ASSET_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO vendors (id, org_id, name, normalized_ref) "
                    "VALUES (:id, :org, 'Vendor', 'vendor')"
                ),
                {"id": VENDOR_ID, "org": ORG_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
                    "VALUES (:id, :treasury, :org, :vendor, 'Main', decode(repeat('22', 20), 'hex'), 'Proposed')"
                ),
                {"id": PAYEE_ID, "treasury": TREASURY_ID, "org": ORG_ID, "vendor": VENDOR_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, "
                    "invoice_no, issue_date, due_at, amount, asset_id) VALUES "
                    "(:id, :org, :treasury, 31337, :vendor, :payee, 'PLAN-001', '2026-10-01', "
                    "'2026-10-31', 1000, :asset)"
                ),
                {
                    "id": REQUEST_ID,
                    "org": ORG_ID,
                    "treasury": TREASURY_ID,
                    "vendor": VENDOR_ID,
                    "payee": PAYEE_ID,
                    "asset": ASSET_ID,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, kind, "
                    "payload, idempotency_key, status) VALUES (:id, :treasury, :step, :request, :hash, "
                    "'PAY', CAST(:payload AS jsonb), 'plan-route-operation', 'Pending')"
                ),
                {
                    "id": OPERATION_ID,
                    "treasury": TREASURY_ID,
                    "step": PLAN_STEP_ID,
                    "request": REQUEST_ID,
                    "hash": STEP_ID,
                    "payload": '{"amountBaseUnits":"975"}',
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, from_address, "
                    "status, block_number, block_hash, confirmations, last_seen_pending_at) "
                    "VALUES (:id, :operation, 31337, decode(repeat('44', 32), 'hex'), 1, "
                    "decode(repeat('55', 20), 'hex'), 'Pending', 123, decode(repeat('66', 32), 'hex'), 2, now())"
                ),
                {"id": TRANSACTION_ID, "operation": OPERATION_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO attestations (id, plan_id, request_id, plan_hash, step_ids, policy_version, "
                    "executor, nonce, valid_until, evidence_digest, typed_data, signature, policy_signer) "
                    "VALUES (:id, :plan, decode(repeat('77', 32), 'hex'), decode(repeat('88', 32), 'hex'), "
                    "ARRAY[decode(repeat('33', 32), 'hex')], decode(repeat('99', 32), 'hex'), "
                    "'0x0000000000000000000000000000000000000001', 1, now(), decode(repeat('aa', 32), 'hex'), "
                    "'{}'::jsonb, decode(repeat('bb', 65), 'hex'), '0x0000000000000000000000000000000000000002')"
                ),
                {"id": uuid.uuid4(), "plan": PLAN_ID},
            )
    finally:
        await engine.dispose()


async def _read_routes(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    app = FastAPI()
    app.include_router(router)
    app.state.request_sessions = sessions
    request = Request({"type": "http", "app": app, "method": "GET", "path": "/"})
    member = MemberAccess(
        access=SimpleNamespace(user=SimpleNamespace(id=uuid.uuid4())),  # type: ignore[arg-type]
        organization_id=ORG_ID,
        roles=frozenset({"Finance"}),
    )
    try:
        listed = await list_execution_plans(ORG_ID, TREASURY_ID, request, member)
        items = [item.model_dump(by_alias=True, mode="json") for item in listed.items]
        assert len(items) == 1
        assert items[0] == {
            "id": str(PLAN_ID),
            "treasuryId": str(TREASURY_ID),
            "createdAt": items[0]["createdAt"],
            "status": "Executing",
            "plannerSource": "UNKNOWN",
            "expectedSaving": None,
            "totalAmount": "975",
            "stepCount": 1,
        }

        detail = await get_execution_plan(ORG_ID, PLAN_ID, request, member)
        body = detail.model_dump(by_alias=True, mode="json")
        step = body["steps"][0]
        assert step["id"] == str(PLAN_STEP_ID)
        assert step["requestId"] == str(REQUEST_ID)
        assert step["kind"] == "PAY"
        assert step["status"] == "Pending"
        assert step["amount"] == "975"
        assert step["verification"] is None
        assert step["txHash"] == "0x" + "44" * 32
        assert step["confirmations"] == 2
        assert body["attestation"]["planHash"] == "0x" + "88" * 32

        with pytest.raises(AuthFailure) as exc_info:
            await get_execution_plan(
                OTHER_ORG_ID,
                PLAN_ID,
                request,
                MemberAccess(
                    access=member.access,
                    organization_id=OTHER_ORG_ID,
                    roles=member.roles,
                ),
            )
        assert exc_info.value.status == 404
    finally:
        await engine.dispose()


def test_plan_timeline_reads_live_records_from_postgres() -> None:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for plan timeline integration tests")
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(database_url))
        asyncio.run(_read_routes(database_url))
    finally:
        command.downgrade(config, "base")
