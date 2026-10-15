"""Plan timeline reads against the persisted attestation and operation records."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.execution.routes import (
    PlanStepView,
    _plan_status,
    _step_verification,
    _total_amount,
    get_execution_plan,
    list_execution_plans,
    router,
)
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess
from treasurypilot_core.eip712 import SWAP_IN, plan_hash

API_ROOT = Path(__file__).parents[1]
ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
OTHER_ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000011")
TREASURY_ID = uuid.UUID("00000000-0000-7000-8000-000000000040")
ASSET_ID = uuid.UUID("00000000-0000-7000-8000-000000000030")
VENDOR_ID = uuid.UUID("00000000-0000-7000-8000-000000000050")
PAYEE_ID = uuid.UUID("00000000-0000-7000-8000-000000000060")
REQUEST_ID = uuid.UUID("00000000-0000-7000-8000-000000000070")
PLAN_ID = uuid.UUID("00000000-0000-7000-8000-000000000080")
BROKEN_PLAN_ID = uuid.UUID("00000000-0000-7000-8000-000000000081")
OPERATION_ID = uuid.UUID("00000000-0000-7000-8000-000000000090")
TRANSACTION_ID = uuid.UUID("00000000-0000-7000-8000-000000000091")
PLAN_STEP_ID = uuid.UUID("00000000-0000-7000-8000-000000000092")
STEP_ID = bytes.fromhex("33" * 32)
SIGNED_REQUEST_ID = bytes.fromhex("77" * 32)
MODULE_ADDRESS = bytes.fromhex("aa" * 20)
EXPECTED_FROM = bytes.fromhex("55" * 20)
EXPECTED_TO = bytes.fromhex("22" * 20)
SIGNED_PLAN_HASH = plan_hash(
    "0x" + SIGNED_REQUEST_ID.hex(),
    "0x" + MODULE_ADDRESS.hex(),
    31337,
    [
        {
            "seq": 0,
            "stepId": "0x" + STEP_ID.hex(),
            "action": 1,
            "from": "0x" + EXPECTED_FROM.hex(),
            "to": "0x" + EXPECTED_TO.hex(),
            "asset": "0x" + bytes.fromhex("11" * 20).hex(),
            "amount": 975,
        }
    ],
)


def test_verification_compares_the_signed_fields_to_the_module_event() -> None:
    signed_step = SimpleNamespace(
        step_id=STEP_ID,
        action=1,
        request_id=SIGNED_REQUEST_ID,
        from_address=EXPECTED_FROM,
        to_address=EXPECTED_TO,
        amount=975,
    )
    event = SimpleNamespace(
        event_name="PaymentExecuted",
        payload={
            "stepId": "0x" + STEP_ID.hex(),
            "requestId": "0x" + SIGNED_REQUEST_ID.hex(),
            "payingWallet": "0x" + EXPECTED_FROM.hex(),
            "payee": "0x" + EXPECTED_TO.hex(),
            "amount": "975",
        },
    )
    assert _step_verification(signed_step, [event]) == "VERIFIED"
    assert _step_verification(signed_step, []) is None

    event.payload["payee"] = "0x" + bytes.fromhex("99" * 20).hex()
    assert _step_verification(signed_step, [event]) == "MISMATCH"


def test_refill_verification_needs_the_actual_target_and_amount() -> None:
    signed_step = SimpleNamespace(
        step_id=STEP_ID,
        action=2,
        request_id=SIGNED_REQUEST_ID,
        from_address=EXPECTED_FROM,
        to_address=EXPECTED_TO,
        amount=975,
    )
    event = SimpleNamespace(
        event_name="RefillExecuted",
        payload={
            "stepId": "0x" + STEP_ID.hex(),
            "requestId": "0x" + SIGNED_REQUEST_ID.hex(),
            "toWallet": "0x" + EXPECTED_TO.hex(),
            "amount": "975",
        },
    )
    assert _step_verification(signed_step, [event]) == "VERIFIED"
    event.payload["amount"] = "974"
    assert _step_verification(signed_step, [event]) == "MISMATCH"


def test_liquidity_events_do_not_claim_recipient_verification_without_recipient_data() -> None:
    signed_step = SimpleNamespace(
        step_id=STEP_ID,
        action=4,
        request_id=SIGNED_REQUEST_ID,
        from_address=EXPECTED_FROM,
        to_address=EXPECTED_TO,
        amount=975,
    )
    event = SimpleNamespace(
        event_name="Supplied",
        payload={"stepId": "0x" + STEP_ID.hex(), "amount": "975"},
    )
    assert _step_verification(signed_step, [event]) is None
    event.payload["amount"] = "974"
    assert _step_verification(signed_step, [event]) == "MISMATCH"


def test_swap_event_is_not_marked_mismatched_without_supported_event_fields() -> None:
    signed_step = SimpleNamespace(
        step_id=STEP_ID,
        action=SWAP_IN,
        request_id=SIGNED_REQUEST_ID,
        from_address=EXPECTED_FROM,
        to_address=EXPECTED_TO,
        amount=975,
    )
    event = SimpleNamespace(
        event_name="SwapExecuted",
        payload={"stepId": "0x" + STEP_ID.hex(), "amount": "975"},
    )
    assert _step_verification(signed_step, [event]) is None


def _step(status: str, kind: str = "PAY", verification: str | None = None) -> PlanStepView:
    return PlanStepView.model_validate(
        {
            "id": uuid.uuid4(),
            "index": 1,
            "kind": kind,
            "title": "step",
            "from": "0x" + "55" * 20,
            "to": "0x" + "22" * 20,
            "amount": "1",
            "request_id": None,
            "reason": "",
            "status": status,
            "tx_hash": None,
            "confirmations": None,
            "verification": verification,
            "updated_at": "2026-10-15T00:00:00Z",
        }
    )


def test_plan_status_only_claims_states_supported_by_persisted_rows() -> None:
    assert _plan_status([_step("Planned")], 1) == "Proposed"
    assert _plan_status([_step("Pending")], 1) == "Executing"
    assert _plan_status([_step("Failed")], 1) == "Unknown"
    assert _plan_status([_step("Verified")], 1) == "Completed"
    assert _plan_status([_step("Verified"), _step("Failed")], 2) == "PartiallyCompleted"
    assert _plan_status([_step("Pending")], 2) == "Unknown"


def test_plan_status_keeps_partly_executed_plans_executing_and_completes_unverifiable_steps() -> (
    None
):
    assert _plan_status([_step("Verified"), _step("Planned")], 2) == "Executing"
    # A confirmed PAY with no module event yet is still awaiting verification.
    assert _plan_status([_step("Confirmed")], 1) == "Executing"
    assert _plan_status([_step("Confirmed", verification="MISMATCH")], 1) == "Unknown"
    # SUPPLY/WITHDRAW/SWAP steps can never become Verified, so Confirmed is terminal.
    assert _plan_status([_step("Confirmed", "SUPPLY")], 1) == "Completed"
    assert _plan_status([_step("Confirmed", "SWAP"), _step("Verified")], 2) == "Completed"
    assert (
        _plan_status([_step("Confirmed", "WITHDRAW"), _step("Failed")], 2) == "PartiallyCompleted"
    )


def test_plan_total_requires_every_signed_step_amount() -> None:
    assert _total_amount(["975", "25"], 2) == "1000"
    assert _total_amount(["975"], 2) is None
    assert _total_amount(["975", None], 2) is None


def _alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _seed(
    database_url: str,
    *,
    transaction_chain_id: int = 31337,
    add_matching_module_event: bool = False,
) -> None:
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
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
                    "VALUES (31338, 'Other Anvil', true, 3, 'https://other-explorer.invalid', '[\"http://rpc\"]')"
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
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id, module_address) "
                    "VALUES (:id, :org, 31337, :asset, :module)"
                ),
                {
                    "id": TREASURY_ID,
                    "org": ORG_ID,
                    "asset": ASSET_ID,
                    "module": MODULE_ADDRESS,
                },
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
                    "status, block_number, block_hash, confirmations, last_seen_pending_at, crosscheck) "
                    "VALUES (:id, :operation, :chain_id, decode(repeat('44', 32), 'hex'), 1, "
                    "decode(repeat('55', 20), 'hex'), 'Pending', 123, decode(repeat('66', 32), 'hex'), "
                    "2, now(), 'Match')"
                ),
                {
                    "id": TRANSACTION_ID,
                    "operation": OPERATION_ID,
                    "chain_id": transaction_chain_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO attestations (id, plan_id, request_id, plan_hash, step_ids, policy_version, "
                    "executor, nonce, valid_until, evidence_digest, typed_data, signature, policy_signer) "
                    "VALUES (:id, :plan, decode(repeat('77', 32), 'hex'), :plan_hash, "
                    "ARRAY[decode(repeat('33', 32), 'hex')], decode(repeat('99', 32), 'hex'), "
                    "'0x0000000000000000000000000000000000000001', 1, now(), decode(repeat('aa', 32), 'hex'), "
                    "'{}'::jsonb, decode(repeat('bb', 65), 'hex'), '0x0000000000000000000000000000000000000002')"
                ),
                {"id": uuid.uuid4(), "plan": PLAN_ID, "plan_hash": SIGNED_PLAN_HASH},
            )
            await connection.execute(
                text(
                    "INSERT INTO plan_steps (id, attestation_id, plan_id, seq, step_id, action, "
                    "request_id, treasury_address, chain_id, from_address, to_address, asset_address, amount) "
                    "SELECT :step_id, a.id, a.plan_id, 0, :hash, 1, :request, :module, 31337, "
                    ":from_address, :to_address, decode(repeat('11', 20), 'hex'), 975 FROM attestations a "
                    "WHERE a.plan_id = :plan"
                ),
                {
                    "step_id": PLAN_STEP_ID,
                    "hash": STEP_ID,
                    "request": SIGNED_REQUEST_ID,
                    "module": MODULE_ADDRESS,
                    "from_address": EXPECTED_FROM,
                    "to_address": EXPECTED_TO,
                    "plan": PLAN_ID,
                },
            )
            # A newer attestation of the same plan must not duplicate the list entry.
            await connection.execute(
                text(
                    "INSERT INTO attestations (id, plan_id, request_id, plan_hash, step_ids, "
                    "policy_version, executor, nonce, valid_until, evidence_digest, typed_data, "
                    "signature, policy_signer, created_at) SELECT :id, plan_id, request_id, plan_hash, "
                    "step_ids, policy_version, executor, nonce + 1, valid_until, evidence_digest, "
                    "typed_data, signature, policy_signer, created_at + interval '1 minute' "
                    "FROM attestations WHERE plan_id = :plan"
                ),
                {"id": uuid.uuid4(), "plan": PLAN_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO plan_steps (id, attestation_id, plan_id, seq, step_id, action, "
                    "request_id, treasury_address, chain_id, from_address, to_address, "
                    "asset_address, amount) SELECT :id, a.id, a.plan_id, p.seq, p.step_id, p.action, "
                    "p.request_id, p.treasury_address, p.chain_id, p.from_address, p.to_address, "
                    "p.asset_address, p.amount FROM attestations a JOIN plan_steps p "
                    "ON p.plan_id = a.plan_id AND p.attestation_id <> a.id "
                    "WHERE a.id = (SELECT id FROM attestations WHERE plan_id = :plan "
                    "ORDER BY created_at DESC LIMIT 1)"
                ),
                {"id": uuid.uuid4(), "plan": PLAN_ID},
            )
            # An inconsistent plan (hash does not match its rows) is skipped, not a list-wide 404.
            await connection.execute(
                text(
                    "INSERT INTO attestations (id, plan_id, request_id, plan_hash, step_ids, "
                    "policy_version, executor, nonce, valid_until, evidence_digest, typed_data, "
                    "signature, policy_signer, created_at) SELECT :id, :plan, request_id, "
                    "decode(repeat('ee', 32), 'hex'), step_ids, policy_version, executor, nonce + 2, "
                    "valid_until, evidence_digest, typed_data, signature, policy_signer, "
                    "created_at + interval '2 minutes' FROM attestations WHERE plan_id = :source LIMIT 1"
                ),
                {"id": uuid.uuid4(), "plan": BROKEN_PLAN_ID, "source": PLAN_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO plan_steps (id, attestation_id, plan_id, seq, step_id, action, "
                    "request_id, treasury_address, chain_id, from_address, to_address, "
                    "asset_address, amount) SELECT :id, a.id, a.plan_id, 0, :hash, 1, :request, "
                    ":module, 31337, :from_address, :to_address, decode(repeat('11', 20), 'hex'), 975 "
                    "FROM attestations a WHERE a.plan_id = :plan"
                ),
                {
                    "id": uuid.uuid4(),
                    "plan": BROKEN_PLAN_ID,
                    "hash": STEP_ID,
                    "request": SIGNED_REQUEST_ID,
                    "module": MODULE_ADDRESS,
                    "from_address": EXPECTED_FROM,
                    "to_address": EXPECTED_TO,
                },
            )
            # A newer Dropped transaction must not hide the live Pending one.
            await connection.execute(
                text(
                    "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, "
                    "from_address, status, submitted_at, crosscheck) VALUES (:id, :operation, "
                    ":chain_id, decode(repeat('45', 32), 'hex'), 2, decode(repeat('55', 20), 'hex'), "
                    "'Dropped', now() + interval '1 hour', 'Match')"
                ),
                {
                    "id": uuid.uuid4(),
                    "operation": OPERATION_ID,
                    "chain_id": transaction_chain_id,
                },
            )
            if add_matching_module_event:
                await connection.execute(
                    text(
                        "INSERT INTO observed_events (id, treasury_id, chain_id, stream, block_number, "
                        "block_hash, tx_hash, log_index, address, event_name, payload) VALUES "
                        "(:id, :treasury, 31337, 'MODULE', 123, decode(repeat('66', 32), 'hex'), "
                        "decode(repeat('44', 32), 'hex'), 0, :module, 'PaymentExecuted', CAST(:payload AS jsonb))"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "treasury": TREASURY_ID,
                        "module": MODULE_ADDRESS,
                        "payload": json.dumps(
                            {
                                "stepId": "0x" + STEP_ID.hex(),
                                "requestId": "0x" + SIGNED_REQUEST_ID.hex(),
                                "payingWallet": "0x" + EXPECTED_FROM.hex(),
                                "payee": "0x" + EXPECTED_TO.hex(),
                                "amount": "975",
                            }
                        ),
                    },
                )
    finally:
        await engine.dispose()


async def _read_routes(database_url: str, *, expect_transaction: bool) -> None:
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
        assert step["to"] == "0x" + EXPECTED_TO.hex()
        assert step["from"] == "0x" + EXPECTED_FROM.hex()
        assert step["status"] == "Pending"
        assert step["amount"] == "975"
        # A provider-to-provider receipt match alone cannot establish execution of
        # the signed fields; only a same-chain module event may do that.
        assert step["verification"] is None
        assert step["txHash"] == ("0x" + "44" * 32 if expect_transaction else None)
        assert step["confirmations"] == (2 if expect_transaction else None)
        assert body["attestation"]["planHash"] == "0x" + SIGNED_PLAN_HASH.hex()

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


@pytest.mark.parametrize(
    ("transaction_chain_id", "add_matching_module_event", "expect_transaction"),
    [(31337, False, True), (31338, True, False)],
)
def test_plan_timeline_reads_only_same_chain_transactions_from_postgres(
    transaction_chain_id: int,
    add_matching_module_event: bool,
    expect_transaction: bool,
) -> None:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for plan timeline integration tests")
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(
            _seed(
                database_url,
                transaction_chain_id=transaction_chain_id,
                add_matching_module_event=add_matching_module_event,
            )
        )
        asyncio.run(_read_routes(database_url, expect_transaction=expect_transaction))
    finally:
        command.downgrade(config, "base")


_COPY_AS_SWAP = (
    "INSERT INTO plan_steps (id, attestation_id, plan_id, seq, step_id, action, request_id, "
    "treasury_address, chain_id, from_address, to_address, asset_address, amount, min_out, venue) "
    "SELECT :id, attestation_id, plan_id, 7, decode(repeat('5e', 32), 'hex'), :action, request_id, "
    "treasury_address, chain_id, from_address, to_address, asset_address, amount, "
    "CAST(:min_out AS numeric), :venue FROM plan_steps WHERE id = :source"
)


async def _swap_rows(database_url: str) -> None:
    engine, _sessions = create_session_factory(database_url)
    try:
        for fields in (
            {"action": 3, "min_out": None, "venue": None},
            {"action": 3, "min_out": "100", "venue": "UNISWAP"},
            {"action": 3, "min_out": "0", "venue": "TEST_ROUTER"},
            {"action": 1, "min_out": "5", "venue": None},  # only a swap carries swap fields
        ):
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(_COPY_AS_SWAP), {"id": uuid.uuid4(), "source": PLAN_STEP_ID, **fields}
                    )
        async with engine.begin() as connection:
            await connection.execute(
                text(_COPY_AS_SWAP),
                {
                    "id": uuid.uuid4(),
                    "source": PLAN_STEP_ID,
                    "action": 3,
                    "min_out": "100",
                    "venue": "TEST_ROUTER",
                },
            )
    finally:
        await engine.dispose()


def test_swap_step_rows_need_min_out_and_the_test_router_label() -> None:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for plan timeline integration tests")
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(database_url))
        asyncio.run(_swap_rows(database_url))
    finally:
        command.downgrade(config, "base")


def test_plan_step_view_carries_the_test_router_label() -> None:
    step = _step("Planned", "SWAP").model_copy(update={"venue": "TEST_ROUTER", "min_out": "190"})

    body = step.model_dump(by_alias=True, mode="json")

    assert body["kind"] == "SWAP" and body["venue"] == "TEST_ROUTER" and body["minOut"] == "190"
