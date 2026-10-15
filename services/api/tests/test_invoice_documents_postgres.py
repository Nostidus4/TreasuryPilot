from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from datetime import UTC, date, datetime
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
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from treasurypilot_api.agent.models import AiCall, AiPurpose, AiValidationResult, Extraction
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.auth import AuthFailure, utc_now
from treasurypilot_api.identity.rate_limit import MemoryRateLimiter
from treasurypilot_api.identity.rbac import MemberAccess
from treasurypilot_api.invoices import documents, inbound_email, requests
from treasurypilot_api.invoices.models import (
    PaymentApproval,
    PaymentRequest,
    RequestDocument,
    RequestFlag,
    RequestRevision,
    RequestSource,
    RequestStatus,
)
from treasurypilot_api.mandate.models import Payee, Vendor

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

API_ROOT = Path(__file__).parents[1]
ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
USER_ID = uuid.UUID("00000000-0000-7000-8000-000000000001")
TREASURY_ID = uuid.UUID("00000000-0000-7000-8000-000000000040")
ASSET_ID = uuid.UUID("00000000-0000-7000-8000-000000000030")
DOC_SHA = bytes.fromhex("11" * 32)
FIELDS = {
    "invoiceNo": "INV-1",
    "issueDate": "2026-10-01",
    "dueDate": "2026-10-20",
    "amount": "100.00",
}


def _alembic(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _seed(sessions: async_sessionmaker[AsyncSession]) -> dict[str, uuid.UUID]:
    async with sessions() as session, session.begin():
        for sql in (
            f"INSERT INTO users (id, email) VALUES ('{USER_ID}', 'docs@example.com')",
            f"INSERT INTO organizations (id, name) VALUES ('{ORG_ID}', 'Docs test')",
            "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
            "rpc_urls) VALUES (11155111, 'Sepolia', true, 3, 'https://e', '[\"https://rpc\"]')",
            "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) VALUES "
            f"('{ASSET_ID}', 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES "
            f"('{TREASURY_ID}', '{ORG_ID}', 11155111, '{ASSET_ID}')",
        ):
            await session.execute(text(sql))
        vendor = Vendor(org_id=ORG_ID, name="Acme", normalized_ref="acme")
        session.add(vendor)
        await session.flush()
        ids = {"vendor": vendor.id}
        now = datetime.now(UTC)
        for name, address, status in (
            ("active", "aa", "Active"),
            ("deactivated", "bb", "Deactivated"),
        ):
            payee = Payee(
                treasury_id=TREASURY_ID,
                org_id=ORG_ID,
                vendor_id=vendor.id,
                label=name,
                address=bytes.fromhex(address * 20),
                status=status,
                oob_verified_by=USER_ID,
                oob_verified_at=now,
                oob_method="PHONE",
                oob_note="verified",
                active_from=now,
                deactivated_at=now if status == "Deactivated" else None,
            )
            session.add(payee)
            await session.flush()
            ids[name] = payee.id
    return ids


async def _draft(sessions: async_sessionmaker[AsyncSession], source: str) -> uuid.UUID:
    request_id = uuid.uuid4()
    async with sessions() as session, session.begin():
        session.add(
            PaymentRequest(
                id=request_id,
                org_id=ORG_ID,
                treasury_id=TREASURY_ID,
                chain_id=11155111,
                asset_id=ASSET_ID,
                source=source,
                status=RequestStatus.DRAFT.value,
                current_revision=1,
                created_by=USER_ID,
                last_edited_by=USER_ID,
                onchain_request_id=requests._request_id(ORG_ID, request_id),
                idempotency_key=str(request_id),
                idempotency_payload_hash=bytes(32),
            )
        )
        await session.flush()
        session.add(RequestRevision(request_id=request_id, revision=1, snapshot={}))
        if source == RequestSource.UPLOAD.value:
            session.add(
                RequestDocument(
                    request_id=request_id,
                    storage_key=f"k/{request_id}",
                    sha256=DOC_SHA,
                    mime="application/pdf",
                    size=1,
                    pages=1,
                    uploaded_by=USER_ID,
                )
            )
    return request_id


async def _scenario(database_url: str) -> None:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    ids = await _seed(sessions)
    app = FastAPI()
    app.state.request_sessions = sessions
    webhook_secret = "inbound-email-test-secret-with-at-least-32-bytes"
    app.state.settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        inbound_email_domain="invoices.example.test",
        inbound_email_webhook_secret=webhook_secret,
    )
    enqueued: list[uuid.UUID] = []
    stored_keys: list[str] = []

    class Storage:
        def put(self, object_key: str, body: bytes, content_type: str) -> None:
            stored_keys.append(object_key)

        def delete(self, object_key: str) -> None:
            stored_keys.remove(object_key)

    class Queue:
        def enqueue(self, request_id: uuid.UUID, document_id: uuid.UUID, job_id: str) -> str:
            enqueued.append(request_id)
            return job_id

    app.state.api_key_rate_limiter = MemoryRateLimiter(utc_now)
    app.state.document_storage = Storage()
    app.state.extraction_queue = Queue()
    member = MemberAccess(
        access=SimpleNamespace(user=SimpleNamespace(id=USER_ID)),  # type: ignore[arg-type]
        organization_id=ORG_ID,
        roles=frozenset({"Operator"}),
    )

    async def operator() -> MemberAccess:
        return member

    admin = MemberAccess(
        access=SimpleNamespace(user=SimpleNamespace(id=USER_ID)),  # type: ignore[arg-type]
        organization_id=ORG_ID,
        roles=frozenset({"OrgAdmin"}),
    )

    async def org_admin() -> MemberAccess:
        return admin

    app.dependency_overrides[documents._require_operator] = operator
    app.dependency_overrides[requests._require_operator] = operator
    app.dependency_overrides[inbound_email._require_org_admin] = org_admin
    app.include_router(documents.router)
    app.include_router(requests.router)
    app.include_router(inbound_email.router)

    @app.exception_handler(AuthFailure)
    async def handler(request: Request, exc: AuthFailure) -> JSONResponse:
        return problem_response(request, exc)

    base = f"/v1/orgs/{ORG_ID}/requests"
    confirm = {"vendorId": str(ids["vendor"]), "payeeId": str(ids["active"]), **FIELDS}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            config_response = await client.put(
                f"/v1/orgs/{ORG_ID}/invoice-inbound-email",
                json={"treasuryId": str(TREASURY_ID), "enabled": True},
            )
            assert config_response.status_code == 200, config_response.text
            address = config_response.json()["address"]
            assert address.endswith("@invoices.example.test")
            local_part = address.removeprefix("invoices+").split("@", 1)[0]
            assert len(local_part) == 48

            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            email_pdf = BytesIO()
            writer.write(email_pdf)
            email_body = json.dumps(
                {
                    "messageId": "<spoofed-invoice@example.test>",
                    "sender": "billing@example.test",
                    "recipient": address,
                    "authenticationResults": {
                        "spf": "pass",
                        "spfDomain": "attacker.test",
                        "dkim": "pass",
                        "dkimDomain": "attacker.test",
                    },
                    "attachments": [
                        {
                            "filename": "invoice.pdf",
                            "contentBase64": base64.b64encode(email_pdf.getvalue()).decode(),
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode()
            invalid_auth = await client.post(
                f"/v1/inbound/invoices/{local_part}",
                content=email_body,
                headers={"Content-Type": "application/json"},
            )
            assert invalid_auth.status_code == 401, invalid_auth.text

            mismatched_body = email_body.replace(
                address.encode(), b"invoices+" + b"b" * 48 + b"@invoices.example.test"
            )
            timestamp = int(time.time())
            mismatched_signature = inbound_email.sign_webhook_body(
                webhook_secret.encode(), timestamp, mismatched_body
            )
            mismatch = await client.post(
                f"/v1/inbound/invoices/{local_part}",
                content=mismatched_body,
                headers={
                    "Content-Type": "application/json",
                    inbound_email.SIGNATURE_HEADER: mismatched_signature,
                },
            )
            assert mismatch.status_code == 403, mismatch.text

            timestamp = int(time.time())
            signature = inbound_email.sign_webhook_body(
                webhook_secret.encode(), timestamp, email_body
            )
            email_response = await client.post(
                f"/v1/inbound/invoices/{local_part}",
                content=email_body,
                headers={
                    "Content-Type": "application/json",
                    inbound_email.SIGNATURE_HEADER: signature,
                },
            )
            assert email_response.status_code == 202, email_response.text
            email_request_id = uuid.UUID(email_response.json()["drafts"][0]["requestId"])
            async with sessions() as session:
                email_draft = await session.get(PaymentRequest, email_request_id)
                email_approval = await session.scalar(
                    select(PaymentApproval.id).where(PaymentApproval.request_id == email_request_id)
                )
                spoof_flag = await session.scalar(
                    select(RequestFlag).where(
                        RequestFlag.request_id == email_request_id,
                        RequestFlag.code == "INBOUND_EMAIL_SENDER_UNVERIFIED",
                    )
                )
                email_document = await session.scalar(
                    select(RequestDocument).where(RequestDocument.request_id == email_request_id)
                )
            assert email_draft is not None and email_draft.status == RequestStatus.DRAFT.value
            assert email_draft.source == RequestSource.UPLOAD.value
            assert email_approval is None
            assert spoof_flag is not None and spoof_flag.severity == "HIGH"
            assert email_document is not None and email_document.uploaded_by is None
            assert email_document.storage_key in stored_keys
            assert email_request_id in enqueued

            # Re-delivery of the same message replays the existing draft.
            replayed = await client.post(
                f"/v1/inbound/invoices/{local_part}",
                content=email_body,
                headers={
                    "Content-Type": "application/json",
                    inbound_email.SIGNATURE_HEADER: inbound_email.sign_webhook_body(
                        webhook_secret.encode(), int(time.time()), email_body
                    ),
                },
            )
            assert replayed.status_code == 202, replayed.text
            assert replayed.json()["drafts"][0]["requestId"] == str(email_request_id)

            # A bad later attachment rejects the whole message before any draft is stored.
            good = base64.b64encode(email_pdf.getvalue()).decode()
            drafts_before = list(enqueued)
            for attachments, expected in (
                (
                    [
                        {"filename": "a.pdf", "contentBase64": good},
                        {"filename": "b.pdf", "contentBase64": "YWJj"},
                    ],
                    415,
                ),
                ([{"filename": "a.pdf", "contentBase64": "===="}], 422),
            ):
                bad_body = json.dumps(
                    {
                        "messageId": f"<bad-{expected}@example.test>",
                        "sender": "billing@example.test",
                        "recipient": address,
                        "attachments": attachments,
                    }
                ).encode()
                bad = await client.post(
                    f"/v1/inbound/invoices/{local_part}",
                    content=bad_body,
                    headers={
                        "Content-Type": "application/json",
                        inbound_email.SIGNATURE_HEADER: inbound_email.sign_webhook_body(
                            webhook_secret.encode(), int(time.time()), bad_body
                        ),
                    },
                )
                assert bad.status_code == expected, bad.text
            assert enqueued == drafts_before
            async with sessions() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(PaymentRequest)
                        .where(PaymentRequest.idempotency_key.like("email:%"))
                    )
                    == 1
                )

            # Re-configuring keeps the same private address.
            again = await client.put(
                f"/v1/orgs/{ORG_ID}/invoice-inbound-email", json={"enabled": True}
            )
            assert again.json()["address"] == address

            # Simulate the worker settling extraction (AGT-004) so the operator can confirm.
            async with sessions() as session, session.begin():
                settled = await session.get(PaymentRequest, email_request_id)
                assert settled is not None
                settled.extraction_status = "ManualEntry"

            # Sender-authentication risk stays on the active revision after an operator confirms.
            response = await client.post(
                f"{base}/{email_request_id}/extraction/confirm",
                json={**confirm, "invoiceNo": "EMAIL-INV-1"},
            )
            assert response.status_code == 200, response.text
            async with sessions() as session:
                email_draft = await session.get(PaymentRequest, email_request_id)
                spoof_flags = (
                    await session.scalars(
                        select(RequestFlag)
                        .where(
                            RequestFlag.request_id == email_request_id,
                            RequestFlag.code == "INBOUND_EMAIL_SENDER_UNVERIFIED",
                        )
                        .order_by(RequestFlag.revision)
                    )
                ).all()
                assert email_draft is not None and email_draft.current_revision == 2
                assert [(flag.revision, flag.status) for flag in spoof_flags] == [
                    (1, "Superseded"),
                    (2, "Open"),
                ]
                with pytest.raises(AuthFailure) as unacked_sender:
                    await requests.assert_high_flags_acknowledged(session, email_draft)
                assert unacked_sender.value.code == "HIGH_FLAGS_UNACKED"

            # An upload starts in Extracting for the worker to settle (AGT-004).
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            pdf = BytesIO()
            writer.write(pdf)
            response = await client.post(
                f"{base}/upload",
                data={"treasury_id": str(TREASURY_ID)},
                files={"file": ("invoice.pdf", pdf.getvalue(), "application/pdf")},
                headers={"Idempotency-Key": "upload-1"},
            )
            assert response.status_code == 202, response.text
            async with sessions() as session:
                uploaded = await session.get(
                    PaymentRequest, uuid.UUID(response.json()["requestId"])
                )
            assert uploaded is not None and uploaded.extraction_status == "Extracting"
            # The email replay re-enqueues under the same deterministic job id.
            assert enqueued == [email_request_id, email_request_id, uploaded.id]

            # Deactivated payee is rejected by the shared _bound_fields guard.
            first = await _draft(sessions, RequestSource.UPLOAD.value)
            response = await client.post(
                f"{base}/{first}/extraction/confirm",
                json={**confirm, "payeeId": str(ids["deactivated"])},
            )
            assert response.status_code == 422, response.text

            # Valid confirm recomputes flags.
            response = await client.post(f"{base}/{first}/extraction/confirm", json=confirm)
            assert response.status_code == 200, response.text
            assert response.json()["flags"]

            # Confirming the same invoice on a second draft is a 409, not a 500.
            second = await _draft(sessions, RequestSource.UPLOAD.value)
            response = await client.post(f"{base}/{second}/extraction/confirm", json=confirm)
            assert response.status_code == 409, response.text
            assert response.json()["code"] == "DUPLICATE_FINGERPRINT"

            # Editing a bound field keeps the document sha256 inside invoice_hash.
            async with sessions() as session:
                version = (await session.get(PaymentRequest, first)).version  # type: ignore[union-attr]
            response = await client.patch(
                f"{base}/{first}",
                json={"amount": "200.00"},
                headers={"If-Match": f'"{version}"'},
            )
            assert response.status_code == 200, response.text
            async with sessions() as session:
                row = await session.get(PaymentRequest, first)
                assert row is not None
                expected = PaymentRequest(
                    invoice_no="INV-1",
                    amount=200_000_000,
                    issue_date=date(2026, 10, 1),
                    due_at=date(2026, 10, 20),
                )
                requests._hashes(expected, "acme", bytes.fromhex("11" * 20), DOC_SHA)
                assert row.invoice_hash == expected.invoice_hash

            # A manual client report is refused on non-upload requests.
            multi = {**confirm, "invoiceCountInDocument": 2}
            manual = await _draft(sessions, RequestSource.MANUAL.value)
            response = await client.post(f"{base}/{manual}/extraction/confirm", json=multi)
            assert response.status_code == 409, response.text

            async def store(request_id: uuid.UUID, count: object) -> None:
                async with sessions() as session, session.begin():
                    document = await session.scalar(
                        select(RequestDocument).where(RequestDocument.request_id == request_id)
                    )
                    assert document is not None
                    ai_call = AiCall(
                        org_id=ORG_ID,
                        purpose=AiPurpose.EXTRACT,
                        model="fixture",
                        prompt_version="test",
                        input_refs=[f"document:{document.id}"],
                        tool_calls=[],
                        validation_result=AiValidationResult.OK,
                        latency_ms=0,
                        input_tokens=0,
                        output_tokens=0,
                        cost_usd_micros=0,
                    )
                    session.add(ai_call)
                    await session.flush()
                    session.add(
                        Extraction(
                            document_id=document.id,
                            ai_call_id=ai_call.id,
                            fields={"invoice_count_in_document": count},
                        )
                    )

            async def flag_counts(request_id: uuid.UUID) -> list[object]:
                async with sessions() as session:
                    return [
                        flag.evidence["invoiceCountInDocument"]
                        for flag in await session.scalars(
                            select(RequestFlag).where(
                                RequestFlag.request_id == request_id,
                                RequestFlag.code == "MULTI_INVOICE_DOCUMENT",
                            )
                        )
                    ]

            # A client-reported count is refused and flagged once, however often it is retried.
            upload = await _draft(sessions, RequestSource.UPLOAD.value)
            for _ in range(2):
                response = await client.post(f"{base}/{upload}/extraction/confirm", json=multi)
                assert response.status_code == 422, response.text
            assert await flag_counts(upload) == [2]

            # M09's persisted count is authoritative even if a client omits the count.
            stored = await _draft(sessions, RequestSource.UPLOAD.value)
            await store(stored, 2)
            for _ in range(2):
                response = await client.post(f"{base}/{stored}/extraction/confirm", json=confirm)
                assert response.status_code == 422, response.text
            assert await flag_counts(stored) == [2]

            # The larger of the stored and reported counts is the evidence.
            larger = await _draft(sessions, RequestSource.UPLOAD.value)
            await store(larger, 1)
            response = await client.post(
                f"{base}/{larger}/extraction/confirm", json={**confirm, "invoiceCountInDocument": 3}
            )
            assert response.status_code == 422, response.text
            assert await flag_counts(larger) == [3]

            # A malformed stored count falls back to the reported one instead of blocking confirm.
            malformed = await _draft(sessions, RequestSource.UPLOAD.value)
            await store(malformed, "many")
            response = await client.post(f"{base}/{malformed}/extraction/confirm", json=multi)
            assert response.status_code == 422, response.text
            assert response.json()["code"] == "MULTI_INVOICE_DOCUMENT"
            assert await flag_counts(malformed) == [2]

            # While the worker is still extracting, confirm is refused so its count cannot be missed.
            pending = await _draft(sessions, RequestSource.UPLOAD.value)
            async with sessions() as session, session.begin():
                row = await session.get(PaymentRequest, pending)
                assert row is not None
                row.extraction_status = "Extracting"
            response = await client.post(f"{base}/{pending}/extraction/confirm", json=confirm)
            assert response.status_code == 409, response.text
            assert response.json()["code"] == "EXTRACTION_PENDING"

            # The worker's HIGH INSTRUCTION_TEXT flag (revision 1) survives confirm and edit.
            injected = await _draft(sessions, RequestSource.UPLOAD.value)
            async with sessions() as session, session.begin():
                session.add(
                    RequestFlag(
                        request_id=injected,
                        revision=1,
                        code="INSTRUCTION_TEXT",
                        severity="HIGH",
                        evidence={"matches": []},
                        source="AI",
                    )
                )
            response = await client.post(
                f"{base}/{injected}/extraction/confirm",
                json={**confirm, "invoiceNo": "INV-2"},
            )
            assert response.status_code == 200, response.text
            for expected_revision in (2, 3):
                async with sessions() as session:
                    row = await session.get(PaymentRequest, injected)
                    assert row is not None and row.current_revision == expected_revision
                    live = (
                        await session.scalars(
                            select(RequestFlag).where(
                                RequestFlag.request_id == injected,
                                RequestFlag.code == "INSTRUCTION_TEXT",
                                RequestFlag.status != "Superseded",
                            )
                        )
                    ).all()
                    assert [(f.revision, f.status) for f in live] == [(expected_revision, "Open")]
                    with pytest.raises(AuthFailure) as unacked:
                        await requests.assert_high_flags_acknowledged(session, row)
                    assert unacked.value.code == "HIGH_FLAGS_UNACKED"
                    version = row.version
                if expected_revision == 2:
                    response = await client.patch(
                        f"{base}/{injected}",
                        json={"amount": "300.00"},
                        headers={"If-Match": f'"{version}"'},
                    )
                    assert response.status_code == 200, response.text
    finally:
        # Incomplete upload drafts would (deliberately) block the 0023 downgrade.
        async with engine.begin() as connection:
            await connection.execute(
                text("TRUNCATE flags, documents, request_revisions, payment_requests CASCADE")
            )
        await engine.dispose()


def test_confirm_extraction_and_edit_enforce_request_invariants() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_scenario(database_url))
    finally:
        command.downgrade(config, "base")
