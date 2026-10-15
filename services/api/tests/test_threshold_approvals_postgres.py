"""MDT-L01 (#127): a request in a k-of-n band stays AwaitingApproval until k distinct approvers sign."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi import FastAPI, Request, Response
from sqlalchemy import text

from treasurypilot_api.compliance.travel_rule import (
    HttpTravelRuleProvider,
    SqlAlchemyTravelRuleRepository,
    TravelRulePolicy,
    TravelRuleService,
    TravelRuleThreshold,
)
from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.invoices.requests import (
    ApproveRequest,
    approve_request,
    get_approval_typed_data,
)
from treasurypilot_core.privacy import FieldCipher, FieldEncryptionKey

API_ROOT = Path(__file__).parents[1]
# Reuse the approval API test's seed; tests are not an importable package.
_spec = importlib.util.spec_from_file_location(
    "approval_api_seed", Path(__file__).with_name("test_invoice_approval_api.py")
)
assert _spec is not None and _spec.loader is not None
_seed_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_seed_module)
ORG, REQUEST = _seed_module.ORG, _seed_module.REQUEST
_Chain, _member, _seed = _seed_module._Chain, _seed_module._member, _seed_module._seed
SECOND = uuid.UUID("00000000-0000-7000-8000-000000000103")


class _Banded:
    def __init__(self, connection) -> None:  # type: ignore[no-untyped-def]
        self._connection = connection

    async def execute(self, statement, params=None):  # type: ignore[no-untyped-def]
        sql = str(statement).replace(
            '{"approvalMaxAge": 86400}',
            '{"approvalMaxAge": 86400, "approvalBands": [{"upTo": "1000", "k": 1}, {"k": 2}]}',
        )
        return await self._connection.execute(text(sql), params)


async def _run(database_url: str) -> None:
    first, second = Account.create(), Account.create()
    engine, sessions = create_session_factory(database_url)
    try:
        async with engine.begin() as connection:
            # The mandate row is immutable, so the banded config is swapped in while seeding.
            # The request amount is 1001: above 1000, so the second band needs two approvals.
            await _seed(_Banded(connection), first)
            await connection.execute(
                text("INSERT INTO users (id, email) VALUES (:id, 'second@example.test')"),
                {"id": SECOND},
            )
            await connection.execute(
                text("INSERT INTO wallet_links (id, user_id, address) VALUES (:id, :u, :a)"),
                {"id": uuid.uuid4(), "u": SECOND, "a": bytes.fromhex(second.address[2:])},
            )
        app = FastAPI()
        app.state.request_sessions = sessions
        app.state.approval_chain_reader = _Chain()
        app.state.travel_rule_service = TravelRuleService(  # thresholds far above the request
            SqlAlchemyTravelRuleRepository(sessions),
            HttpTravelRuleProvider(base_url="https://gateway.example", api_key="x"),
            TravelRulePolicy(
                (TravelRuleThreshold("US", "USD", 10**9), TravelRuleThreshold("GB", "USD", 10**9))
            ),
            FieldCipher(FieldEncryptionKey.from_base64("A" * 43)),
        )
        request = Request({"type": "http", "app": app, "method": "GET", "path": "/"})

        async def approve(account, user: uuid.UUID, key: str):  # type: ignore[no-untyped-def]
            member = _member(user)
            typed = await get_approval_typed_data(ORG, REQUEST, request, Response(), member)
            signature = account.sign_message(encode_typed_data(full_message=typed)).signature.hex()
            expiry = typed["message"]["expiry"]
            result = await approve_request(
                ORG,
                REQUEST,
                ApproveRequest(signature=signature, revision=1, expiry=expiry),
                request,
                Response(),
                key,
                member,
            )
            return typed, signature, expiry, result

        approver_one = uuid.UUID("00000000-0000-7000-8000-000000000102")
        typed, signature, expiry, result = await approve(first, approver_one, "k1")
        assert result["request"]["status"] == "AwaitingApproval"  # type: ignore[index]
        assert result["approvalProgress"] == {"collected": 1, "required": 2}

        # The same approver cannot count twice.
        with pytest.raises(AuthFailure) as error:
            await approve_request(
                ORG,
                REQUEST,
                ApproveRequest(signature=signature, revision=1, expiry=expiry),
                request,
                Response(),
                "k1-again",
                _member(approver_one),
            )
        assert error.value.code == "APPROVAL_EXISTS"

        await asyncio.sleep(1.1)  # the second approver signs the same typed data, same expiry
        typed2, _sig, expiry2, result = await approve(second, SECOND, "k2")
        assert typed2 == typed and expiry2 == expiry
        assert result["request"]["status"] == "Approved"  # type: ignore[index]
        assert result["approvalProgress"] == {"collected": 2, "required": 2}
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL threshold approval test",
)
def test_two_approval_band_is_not_approved_after_one() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_run(database_url))
    finally:
        command.downgrade(config, "base")
