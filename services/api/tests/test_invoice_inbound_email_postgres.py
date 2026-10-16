"""Email inbox: allowlist, quarantine, content dedupe and audit against PostgreSQL."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx2 as httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pypdf import PdfWriter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from treasurypilot_api.audit.models import AuditLog
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.auth import AuthFailure, utc_now
from treasurypilot_api.identity.rate_limit import MemoryRateLimiter
from treasurypilot_api.identity.rbac import MemberAccess
from treasurypilot_api.invoices import inbound_email
from treasurypilot_api.invoices.models import (
    InvoiceInboundQuarantine,
    PaymentRequest,
    RequestFlag,
)

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

API_ROOT = Path(__file__).parents[1]
ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000110")
USER_ID = uuid.UUID("00000000-0000-7000-8000-000000000101")
TREASURY_ID = uuid.UUID("00000000-0000-7000-8000-000000000140")
ASSET_ID = uuid.UUID("00000000-0000-7000-8000-000000000130")
SECRET = "inbound-email-test-secret-with-at-least-32-bytes"


def _alembic(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _pdf(width: int) -> str:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=100)
    out = BytesIO()
    writer.write(out)
    return base64.b64encode(out.getvalue()).decode()


async def _seed(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session, session.begin():
        for sql in (
            f"INSERT INTO users (id, email) VALUES ('{USER_ID}', 'inbox@example.com')",
            f"INSERT INTO organizations (id, name) VALUES ('{ORG_ID}', 'Inbox test')",
            "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
            "rpc_urls) VALUES (11155111, 'Sepolia', true, 3, 'https://e', '[\"https://rpc\"]')",
            "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) VALUES "
            f"('{ASSET_ID}', 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES "
            f"('{TREASURY_ID}', '{ORG_ID}', 11155111, '{ASSET_ID}')",
        ):
            await session.execute(text(sql))


async def _scenario(database_url: str) -> None:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    await _seed(sessions)
    app = FastAPI()
    app.state.request_sessions = sessions
    app.state.settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        inbound_email_domain="invoices.example.test",
        inbound_email_webhook_secret=SECRET,
    )
    stored: list[str] = []
    enqueued: list[uuid.UUID] = []

    class Storage:
        def put(self, object_key: str, body: bytes, content_type: str) -> None:
            stored.append(object_key)

        def delete(self, object_key: str) -> None:
            stored.remove(object_key)

    class Queue:
        def enqueue(self, request_id: uuid.UUID, document_id: uuid.UUID, job_id: str) -> str:
            enqueued.append(request_id)
            return job_id

    app.state.api_key_rate_limiter = MemoryRateLimiter(utc_now)
    app.state.document_storage = Storage()
    app.state.extraction_queue = Queue()
    admin = MemberAccess(
        access=SimpleNamespace(user=SimpleNamespace(id=USER_ID)),  # type: ignore[arg-type]
        organization_id=ORG_ID,
        roles=frozenset({"OrgAdmin"}),
    )

    async def org_admin() -> MemberAccess:
        return admin

    app.dependency_overrides[inbound_email._require_org_admin] = org_admin
    app.include_router(inbound_email.router)

    @app.exception_handler(AuthFailure)
    async def handler(request: Request, exc: AuthFailure) -> JSONResponse:
        return problem_response(request, exc)

    async def deliver(
        client: httpx.AsyncClient,
        address: str,
        message_id: str,
        sender: str,
        attachments: list[tuple[str, str]],
        *,
        authenticated_domain: str | None,
    ) -> httpx.Response:
        auth = (
            {"spf": "pass", "spfDomain": authenticated_domain}
            if authenticated_domain
            else {"spf": "fail", "dkim": "none"}
        )
        body = json.dumps(
            {
                "messageId": message_id,
                "sender": sender,
                "recipient": address,
                "authenticationResults": auth,
                "attachments": [
                    {"filename": name, "contentBase64": content} for name, content in attachments
                ],
            },
            separators=(",", ":"),
        ).encode()
        signature = inbound_email.sign_webhook_body(SECRET.encode(), int(time.time()), body)
        local_part = address.removeprefix("invoices+").split("@", 1)[0]
        return await client.post(
            f"/v1/inbound/invoices/{local_part}",
            content=body,
            headers={
                "Content-Type": "application/json",
                inbound_email.SIGNATURE_HEADER: signature,
            },
        )

    config_url = f"/v1/orgs/{ORG_ID}/invoice-inbound-email"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            missing = await client.get(config_url)
            assert missing.status_code == 404
            created = await client.put(
                config_url, json={"treasuryId": str(TREASURY_ID), "enabled": True}
            )
            assert created.status_code == 200, created.text
            address = created.json()["address"]
            assert created.json()["senderAllowlist"] == []

            # No allowlist: an unauthenticated sender still yields a flagged draft.
            spoof = await deliver(
                client,
                address,
                "<m0@x>",
                "ceo@vendor.test",
                [("a.pdf", _pdf(101))],
                authenticated_domain=None,
            )
            assert spoof.status_code == 202, spoof.text
            assert len(spoof.json()["drafts"]) == 1 and not spoof.json()["quarantined"]
            async with sessions() as session:
                flag_codes = (await session.scalars(select(RequestFlag.code))).all()
            assert flag_codes == ["INBOUND_EMAIL_SENDER_UNVERIFIED"]

            updated = await client.put(
                config_url, json={"senderAllowlist": ["Billing@Vendor.test", "partner.test"]}
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["senderAllowlist"] == ["billing@vendor.test", "partner.test"]
            assert (await client.get(config_url)).json()["senderAllowlist"] == [
                "billing@vendor.test",
                "partner.test",
            ]
            bad = await client.put(config_url, json={"senderAllowlist": ["not a domain"]})
            assert bad.status_code == 422

            drafts_before = len(enqueued)
            # Not on the allowlist -> quarantined, no storage, no draft.
            stranger = await deliver(
                client,
                address,
                "<m1@x>",
                "Evil‮ <evil@other.test>",
                [("b.pdf", _pdf(102))],
                authenticated_domain="other.test",
            )
            assert stranger.status_code == 202
            assert stranger.json() == {
                "drafts": [],
                "quarantined": True,
                "duplicateAttachments": 0,
            }
            # Allowlisted address spoofed (authenticated domain does not align).
            forged = await deliver(
                client,
                address,
                "<m2@x>",
                "billing@vendor.test",
                [("c.pdf", _pdf(103))],
                authenticated_domain="attacker.test",
            )
            assert forged.json()["quarantined"] is True
            # Redelivery of a quarantined message does not duplicate the record or audit.
            again = await deliver(
                client,
                address,
                "<m2@x>",
                "billing@vendor.test",
                [("c.pdf", _pdf(103))],
                authenticated_domain="attacker.test",
            )
            assert again.json()["quarantined"] is True
            assert len(enqueued) == drafts_before

            listing = await client.get(f"{config_url}/quarantine")
            assert listing.status_code == 200
            items = listing.json()["items"]
            assert {item["reason"] for item in items} == {
                "SENDER_NOT_ALLOWLISTED",
                "SENDER_UNAUTHENTICATED",
            }
            assert len(items) == 2
            assert all("‮" not in item["sender"] for item in items)

            # Allowlisted + authenticated -> normal draft; repeated attachments dedupe.
            same = _pdf(104)
            ok = await deliver(
                client,
                address,
                "<m3@x>",
                "billing@vendor.test",
                [("d.pdf", same), ("d-copy.pdf", same)],
                authenticated_domain="vendor.test",
            )
            assert ok.status_code == 202, ok.text
            assert len(ok.json()["drafts"]) == 1
            assert ok.json()["duplicateAttachments"] == 1
            # The same content in another message is dropped; a retry of the first replays it.
            dup = await deliver(
                client,
                address,
                "<m4@x>",
                "billing@vendor.test",
                [("e.pdf", same)],
                authenticated_domain="vendor.test",
            )
            assert dup.json()["drafts"] == [] and dup.json()["duplicateAttachments"] == 1
            retry = await deliver(
                client,
                address,
                "<m3@x>",
                "billing@vendor.test",
                [("d.pdf", same), ("d-copy.pdf", same)],
                authenticated_domain="vendor.test",
            )
            assert retry.json()["drafts"] == ok.json()["drafts"]

            async with sessions() as session:
                statuses = set((await session.scalars(select(PaymentRequest.status))).all())
                quarantined = (await session.scalars(select(InvoiceInboundQuarantine))).all()
                actions = (
                    await session.scalars(select(AuditLog.action).order_by(AuditLog.seq))
                ).all()
            assert statuses == {"Draft"}  # nothing is ever auto-approved
            assert len(quarantined) == 2
            assert actions.count("invoice_inbound_email.quarantined") == 2
            assert (
                actions.count("invoice_inbound_email.configured") == 2
            )  # the rejected PUT is not audited
            assert actions.count("invoice_inbound_email.received") == 4  # m0, m3, m4, m3 retry
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE flags, documents, request_revisions, payment_requests, "
                    "invoice_inbound_quarantine CASCADE"
                )
            )
        await engine.dispose()


def test_email_inbox_allowlist_quarantine_dedupe_and_audit() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_scenario(database_url))
    finally:
        command.downgrade(config, "base")
