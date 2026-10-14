from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi import FastAPI, Request, Response
from sqlalchemy import text

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.access import MemberContext
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.invoices.requests import (
    ApproveRequest,
    approve_request,
    get_approval_typed_data,
)

API_ROOT = Path(__file__).parents[1]
ORG = uuid.UUID("00000000-0000-7000-8000-000000000110")
MAKER = uuid.UUID("00000000-0000-7000-8000-000000000101")
APPROVER = uuid.UUID("00000000-0000-7000-8000-000000000102")
REQUEST = uuid.UUID("00000000-0000-7000-8000-000000000170")
NO_WALLET_REQUEST = uuid.UUID("00000000-0000-7000-8000-000000000171")
TREASURY = uuid.UUID("00000000-0000-7000-8000-000000000140")
ASSET = uuid.UUID("00000000-0000-7000-8000-000000000130")
VENDOR = uuid.UUID("00000000-0000-7000-8000-000000000150")
PAYEE = uuid.UUID("00000000-0000-7000-8000-000000000160")
WALLET = uuid.UUID("00000000-0000-7000-8000-000000000180")


class _Chain:
    async def is_approver(self, *, chain_id: int, module: str, signer: str) -> bool:
        return True

    async def is_valid_erc1271_signature(
        self, *, chain_id: int, wallet: str, digest: bytes, signature: bytes
    ) -> bool:
        return False


async def _seed(connection, account: Account) -> None:  # type: ignore[no-untyped-def]
    for user_id, email in ((MAKER, "maker"), (APPROVER, "approver")):
        await connection.execute(
            text("INSERT INTO users (id, email) VALUES (:id, :email)"),
            {"id": user_id, "email": f"{email}@example.test"},
        )
    params = {
        "org": ORG,
        "treasury": TREASURY,
        "asset": ASSET,
        "vendor": VENDOR,
        "payee": PAYEE,
        "wallet": WALLET,
    }
    statements = [
        "INSERT INTO organizations (id, name) VALUES (:org, 'Approval')",
        "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
        "VALUES (11155111, 'Sepolia', true, 3, 'https://x.test', '[\"https://rpc\"]')",
        "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
        "VALUES (:asset, 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
        "INSERT INTO treasuries (id, org_id, chain_id, asset_id, module_address) "
        "VALUES (:treasury, :org, 11155111, :asset, decode(repeat('33', 20), 'hex'))",
        "INSERT INTO treasury_wallets (id, org_id, treasury_id, chain_id, role, label, "
        "safe_address, owners, threshold) VALUES (:wallet, :org, :treasury, 11155111, "
        "'OPERATIONAL', 'Ops', decode(repeat('44', 20), 'hex'), "
        f"'[\"0x{'55' * 20}\"]', 1)",
        "INSERT INTO vendors (id, org_id, name, normalized_ref) "
        "VALUES (:vendor, :org, 'Vendor', 'vendor')",
        "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
        "VALUES (:payee, :treasury, :org, :vendor, 'Main', decode(repeat('22', 20), 'hex'), "
        "'Active')",
        "INSERT INTO mandate_versions (id, treasury_id, version, status, config, config_hash) "
        "VALUES ('00000000-0000-7000-8000-000000000190', :treasury, 1, 'Active', "
        "'{\"approvalMaxAge\": 86400}', decode(repeat('66', 32), 'hex'))",
    ]
    for statement in statements:
        await connection.execute(text(statement), params)
    for user_id, address in (
        (APPROVER, account.address),
        (MAKER, Account.create().address),
    ):
        await connection.execute(
            text("INSERT INTO wallet_links (id, user_id, address) VALUES (:id, :user, :address)"),
            {"id": uuid.uuid4(), "user": user_id, "address": bytes.fromhex(address[2:])},
        )
    due = (datetime.now(UTC) + timedelta(days=30)).date()
    for request_id, wallet_id, invoice_no in (
        (REQUEST, WALLET, "INV-API"),
        (NO_WALLET_REQUEST, None, "INV-API-NOWALLET"),
    ):
        await connection.execute(
            text(
                "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
                "payee_id, invoice_no, issue_date, due_at, amount, asset_id, paying_wallet_id, "
                "status, created_by, last_edited_by, fingerprint, invoice_hash, "
                "onchain_request_id) VALUES (:id, :org, :treasury, 11155111, :vendor, :payee, "
                ":no, '2026-10-01', :due, 1001, :asset, :wallet, 'AwaitingApproval', :maker, "
                ":maker, :fp, :ih, :oid)"
            ),
            {
                **params,
                "id": request_id,
                "wallet": wallet_id,
                "no": invoice_no,
                "due": due,
                "maker": MAKER,
                "fp": request_id.bytes * 2,
                "ih": bytes.fromhex("77" * 32),
                "oid": bytes.fromhex("88" * 32),
            },
        )


async def _approve_in_postgres(database_url: str) -> None:
    account = Account.create()
    engine, sessions = create_session_factory(database_url)
    try:
        async with engine.begin() as connection:
            await _seed(connection, account)

        app = FastAPI()
        app.state.request_sessions = sessions
        app.state.approval_chain_reader = _Chain()
        request = Request({"type": "http", "app": app, "method": "GET", "path": "/"})
        approver = MemberContext(ORG, APPROVER, frozenset({"Approver"}))
        maker = MemberContext(ORG, MAKER, frozenset({"Approver"}))

        # Maker-checker applies to the GET too, before anything is signed.
        with pytest.raises(AuthFailure) as error:
            await get_approval_typed_data(ORG, REQUEST, request, Response(), maker)
        assert error.value.code == "MAKER_CHECKER"
        # The signed paying wallet must be the request's explicit choice.
        with pytest.raises(AuthFailure) as error:
            await get_approval_typed_data(ORG, NO_WALLET_REQUEST, request, Response(), approver)
        assert error.value.code == "PAYING_WALLET_UNKNOWN"

        get_response = Response()
        typed = await get_approval_typed_data(ORG, REQUEST, request, get_response, approver)
        assert get_response.headers["X-Request-Revision"] == "1"
        signature = account.sign_message(encode_typed_data(full_message=typed)).signature.hex()
        expiry = typed["message"]["expiry"]  # type: ignore[index]

        # Wall-clock time moves between the GET and the POST; the pinned expiry must hold.
        await asyncio.sleep(1.1)
        for tampered, code in (
            (expiry + 1, "SIGNATURE_INVALID"),  # in the window, but not what was signed
            (expiry + 30 * 86_400, "APPROVAL_EXPIRY_INVALID"),  # beyond the mandate window
        ):
            with pytest.raises(AuthFailure) as error:
                await approve_request(
                    ORG,
                    REQUEST,
                    ApproveRequest(signature=signature, revision=1, expiry=tampered),
                    request,
                    Response(),
                    "approve-key",
                    approver,
                )
            assert error.value.code == code
        result = await approve_request(
            ORG,
            REQUEST,
            ApproveRequest(signature=signature, revision=1, expiry=expiry),
            request,
            Response(),
            "approve-key",
            approver,
        )
        assert result["request"]["status"] == "Approved"  # type: ignore[index]
        assert result["approval"]["typedData"] == typed  # type: ignore[index]
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL approval test",
)
def test_signed_get_payload_verifies_on_post_after_time_passes() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_approve_in_postgres(database_url))
    finally:
        command.downgrade(config, "base")
