from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request, Response
from sqlalchemy import select, text

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.invoices.requests import (
    ConfirmTermsRequest,
    FlagAcknowledgment,
    RequestReason,
    acknowledge_flag,
    assert_high_flags_acknowledged,
    confirm_request_terms,
    request_changes,
    submit_request,
    withdraw_request,
)

API_ROOT = Path(__file__).parents[1]
USER_ID = uuid.UUID("00000000-0000-7000-8000-000000000001")
ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
REQUEST_ID = uuid.UUID("00000000-0000-7000-8000-000000000070")
APPROVER_ID = uuid.UUID("00000000-0000-7000-8000-000000000002")
FLAG_ID = uuid.UUID("00000000-0000-7000-8000-000000000075")
SUBMIT_REQUEST_ID = uuid.UUID("00000000-0000-7000-8000-000000000074")
TERMS_REQUEST_ID = uuid.UUID("00000000-0000-7000-8000-000000000072")
UPLOAD_REQUEST_ID = uuid.UUID("00000000-0000-7000-8000-000000000073")


def _member(user_id: uuid.UUID, role: str) -> MemberAccess:
    return MemberAccess(
        access=SimpleNamespace(user=SimpleNamespace(id=user_id)),  # type: ignore[arg-type]
        organization_id=ORG_ID,
        roles=frozenset({role}),
    )


async def _confirm_in_postgres(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO users (id, email) VALUES (:id, 'terms@example.test')"),
                {"id": USER_ID},
            )
            await connection.execute(
                text("INSERT INTO organizations (id, name) VALUES (:id, 'Terms test')"),
                {"id": ORG_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) VALUES (11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', '[\"https://rpc\"]')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) VALUES ('00000000-0000-7000-8000-000000000030', 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES ('00000000-0000-7000-8000-000000000040', :org, 11155111, '00000000-0000-7000-8000-000000000030')"
                ),
                {"org": ORG_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES ('00000000-0000-7000-8000-000000000050', :org, 'Vendor', 'vendor')"
                ),
                {"org": ORG_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status, oob_verified_by, oob_verified_at, oob_method, oob_note, active_from) VALUES ('00000000-0000-7000-8000-000000000060', '00000000-0000-7000-8000-000000000040', :org, '00000000-0000-7000-8000-000000000050', 'Main', decode(repeat('22', 20), 'hex'), 'Active', '00000000-0000-7000-8000-000000000001', now(), 'PHONE', 'verified', now())"
                ),
                {"org": ORG_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, invoice_no, issue_date, due_at, amount, asset_id) VALUES (:id, :org, '00000000-0000-7000-8000-000000000040', 11155111, '00000000-0000-7000-8000-000000000050', '00000000-0000-7000-8000-000000000060', 'INV-TERMS', '2026-10-01', '2026-10-31', 1001, '00000000-0000-7000-8000-000000000030')"
                ),
                {"id": REQUEST_ID, "org": ORG_ID},
            )

        app = FastAPI()
        app.state.request_sessions = sessions
        request = Request({"type": "http", "app": app, "method": "POST", "path": "/"})
        response = Response()
        member = MemberAccess(
            access=SimpleNamespace(user=SimpleNamespace(id=USER_ID)),  # type: ignore[arg-type]
            organization_id=ORG_ID,
            roles=frozenset({"OPERATOR"}),
        )
        result = await confirm_request_terms(
            ORG_ID,
            REQUEST_ID,
            ConfirmTermsRequest(
                terms={"netDueDay": 21_000, "discountBps": 250, "discountDeadlineDay": 20_990}
            ),
            request,
            response,
            "1",
            member,
        )
        assert result["request"]["earlyAmount"] == "976"
        assert result["request"]["termsConfirmedBy"] == str(USER_ID)
        async with sessions() as session:
            row = await session.scalar(
                select(PaymentRequest).where(PaymentRequest.id == REQUEST_ID)
            )
            assert row is not None
            assert row.terms_confirmed_by == USER_ID
            assert row.terms_hash is not None and len(row.terms_hash) == 32
            assert row.current_revision == 2
            confirmed_at = row.terms_confirmed_at

        # An equivalent re-confirmation keeps the original confirmer and revision.
        await confirm_request_terms(
            ORG_ID,
            REQUEST_ID,
            ConfirmTermsRequest(
                terms={"net_due_day": 21_000, "discount_bps": 250, "discount_deadline_day": 20_990}
            ),
            request,
            response,
            response.headers["ETag"],
            member,
        )
        async with sessions() as session:
            row = await session.scalar(
                select(PaymentRequest).where(PaymentRequest.id == REQUEST_ID)
            )
            assert row is not None
            assert row.current_revision == 2
            assert row.terms_confirmed_at == confirmed_at
    finally:
        await engine.dispose()


async def _submit_and_ack_in_postgres(database_url: str) -> None:
    engine, sessions = create_session_factory(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE organizations SET solo_mode = true WHERE id = :org"),
                {"org": ORG_ID},
            )
            await connection.execute(
                text("INSERT INTO users (id, email) VALUES (:id, 'approver@example.test')"),
                {"id": APPROVER_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
                    "payee_id, invoice_no, issue_date, due_at, amount, asset_id, created_by, "
                    "last_edited_by) VALUES "
                    "(:id, :org, '00000000-0000-7000-8000-000000000040', 11155111, "
                    "'00000000-0000-7000-8000-000000000050', "
                    "'00000000-0000-7000-8000-000000000060', 'INV-SUBMIT', '2026-10-01', "
                    "'2026-10-31', 1001, '00000000-0000-7000-8000-000000000030', :creator, :creator)"
                ),
                {"id": SUBMIT_REQUEST_ID, "org": ORG_ID, "creator": USER_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO request_revisions (id, request_id, revision, snapshot) "
                    "VALUES (gen_random_uuid(), :request, 1, '{}')"
                ),
                {"request": SUBMIT_REQUEST_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO flags (id, request_id, revision, code, severity, evidence, source) "
                    "VALUES (:id, :request, 1, 'AMOUNT_OUTLIER', 'HIGH', '{}', 'DETERMINISTIC')"
                ),
                {"id": FLAG_ID, "request": SUBMIT_REQUEST_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
                    "payee_id, invoice_no, issue_date, due_at, amount, asset_id, terms) VALUES "
                    "(:id, :org, '00000000-0000-7000-8000-000000000040', 11155111, "
                    "'00000000-0000-7000-8000-000000000050', "
                    "'00000000-0000-7000-8000-000000000060', 'INV-TERMS-PENDING', '2026-10-01', "
                    "'2026-10-31', 1001, '00000000-0000-7000-8000-000000000030', '{\"net_due_day\": 21000}')"
                ),
                {"id": TERMS_REQUEST_ID, "org": ORG_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
                    "payee_id, invoice_no, issue_date, due_at, amount, asset_id, source) VALUES "
                    "(:id, :org, '00000000-0000-7000-8000-000000000040', 11155111, "
                    "'00000000-0000-7000-8000-000000000050', "
                    "'00000000-0000-7000-8000-000000000060', 'INV-UPLOAD-PENDING', '2026-10-01', "
                    "'2026-10-31', 1002, '00000000-0000-7000-8000-000000000030', 'UPLOAD')"
                ),
                {"id": UPLOAD_REQUEST_ID, "org": ORG_ID},
            )

        app = FastAPI()
        app.state.request_sessions = sessions
        request = Request({"type": "http", "app": app, "method": "POST", "path": "/"})
        response = Response()
        operator = _member(USER_ID, "Operator")
        approver = _member(APPROVER_ID, "Approver")
        for blocked_id, error_code in (
            (TERMS_REQUEST_ID, "TERMS_UNCONFIRMED"),
            (UPLOAD_REQUEST_ID, "EXTRACTION_UNCONFIRMED"),
        ):
            with pytest.raises(AuthFailure) as error:
                await submit_request(
                    ORG_ID,
                    blocked_id,
                    request,
                    Response(),
                    '"1"',
                    operator,
                )
            assert error.value.code == error_code

        submitted = await submit_request(
            ORG_ID, SUBMIT_REQUEST_ID, request, response, '"1"', operator
        )
        assert submitted["request"]["status"] == "AwaitingApproval"
        async with sessions() as session:
            row = await session.scalar(
                select(PaymentRequest).where(PaymentRequest.id == SUBMIT_REQUEST_ID)
            )
            assert row is not None
            with pytest.raises(AuthFailure) as error:
                await assert_high_flags_acknowledged(session, row)
            assert error.value.code == "HIGH_FLAGS_UNACKED"

        with pytest.raises(AuthFailure) as error:
            await acknowledge_flag(
                ORG_ID,
                SUBMIT_REQUEST_ID,
                FLAG_ID,
                FlagAcknowledgment(note="Reviewed high risk flag"),
                request,
                operator,
            )
        assert error.value.code == "MAKER_CHECKER"
        acknowledged = await acknowledge_flag(
            ORG_ID,
            SUBMIT_REQUEST_ID,
            FLAG_ID,
            FlagAcknowledgment(note="Reviewed high risk flag"),
            request,
            approver,
        )
        assert acknowledged["flag"]["status"] == "Acknowledged"
        async with sessions() as session:
            row = await session.scalar(
                select(PaymentRequest).where(PaymentRequest.id == SUBMIT_REQUEST_ID)
            )
            assert row is not None
            await assert_high_flags_acknowledged(session, row)

        response = Response()
        changed = await request_changes(
            ORG_ID,
            SUBMIT_REQUEST_ID,
            RequestReason(reason="Please verify the supporting document."),
            request,
            response,
            f'"{submitted["request"]["version"]}"',
            approver,
        )
        assert changed["request"]["status"] == "Draft"
        resubmitted = await submit_request(
            ORG_ID,
            SUBMIT_REQUEST_ID,
            request,
            Response(),
            f'"{changed["request"]["version"]}"',
            operator,
        )
        withdrawn = await withdraw_request(
            ORG_ID,
            SUBMIT_REQUEST_ID,
            request,
            Response(),
            f'"{resubmitted["request"]["version"]}"',
            operator,
        )
        assert withdrawn["request"]["status"] == "Draft"
        with pytest.raises(AuthFailure) as error:
            await acknowledge_flag(
                ORG_ID,
                SUBMIT_REQUEST_ID,
                FLAG_ID,
                FlagAcknowledgment(note="Reviewed high risk flag"),
                request,
                approver,
            )
        assert error.value.code == "NOT_AWAITING_APPROVAL"
        await submit_request(
            ORG_ID,
            SUBMIT_REQUEST_ID,
            request,
            Response(),
            f'"{withdrawn["request"]["version"]}"',
            operator,
        )
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE flags SET status = 'Superseded' WHERE id = :id"),
                {"id": FLAG_ID},
            )
        with pytest.raises(AuthFailure) as error:
            await acknowledge_flag(
                ORG_ID,
                SUBMIT_REQUEST_ID,
                FLAG_ID,
                FlagAcknowledgment(note="Reviewed high risk flag"),
                request,
                approver,
            )
        assert error.value.code == "FLAG_SUPERSEDED"
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL terms confirmation test",
)
def test_terms_confirmation_persists_revision_and_hash() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_confirm_in_postgres(database_url))
    finally:
        command.downgrade(config, "base")


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL submit/acknowledgment test",
)
def test_submit_guards_and_flag_acknowledgment_persist_in_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_confirm_in_postgres(database_url))
        asyncio.run(_submit_and_ack_in_postgres(database_url))
    finally:
        command.downgrade(config, "base")
