from __future__ import annotations

import asyncio
import os
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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess
from treasurypilot_api.invoices import documents, requests
from treasurypilot_api.invoices.models import (
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
    enqueued: list[uuid.UUID] = []

    class Storage:
        def put(self, object_key: str, body: bytes, content_type: str) -> None:
            pass

    class Queue:
        def enqueue(self, request_id: uuid.UUID, document_id: uuid.UUID, job_id: str) -> str:
            enqueued.append(request_id)
            return job_id

    app.state.document_storage = Storage()
    app.state.extraction_queue = Queue()
    member = MemberAccess(
        access=SimpleNamespace(user=SimpleNamespace(id=USER_ID)),  # type: ignore[arg-type]
        organization_id=ORG_ID,
        roles=frozenset({"Operator"}),
    )

    async def operator() -> MemberAccess:
        return member

    app.dependency_overrides[documents._require_operator] = operator
    app.dependency_overrides[requests._require_operator] = operator
    app.include_router(documents.router)
    app.include_router(requests.router)

    @app.exception_handler(AuthFailure)
    async def handler(request: Request, exc: AuthFailure) -> JSONResponse:
        return problem_response(request, exc)

    base = f"/v1/orgs/{ORG_ID}/requests"
    confirm = {"vendorId": str(ids["vendor"]), "payeeId": str(ids["active"]), **FIELDS}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
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
            assert enqueued == [uploaded.id]

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

            # Multi-invoice flag: refused on non-upload requests, idempotent on upload drafts.
            multi = {**confirm, "invoiceCountInDocument": 2}
            manual = await _draft(sessions, RequestSource.MANUAL.value)
            response = await client.post(f"{base}/{manual}/extraction/confirm", json=multi)
            assert response.status_code == 409, response.text
            upload = await _draft(sessions, RequestSource.UPLOAD.value)
            for _ in range(2):
                response = await client.post(f"{base}/{upload}/extraction/confirm", json=multi)
                assert response.status_code == 422, response.text
            async with sessions() as session:
                flags = (
                    await session.scalars(
                        select(RequestFlag.request_id).where(
                            RequestFlag.code == "MULTI_INVOICE_DOCUMENT"
                        )
                    )
                ).all()
            assert list(flags) == [upload]
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
