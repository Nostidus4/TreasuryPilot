import asyncio
import os
import uuid
from datetime import date
from time import perf_counter

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from treasurypilot_api.invoices.models import PaymentRequest, RequestStatus
from treasurypilot_api.invoices.near_duplicates import find_near_duplicates


class _Rows:
    def __init__(self, rows: list[tuple[uuid.UUID, str]]) -> None:
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class _Session:
    def __init__(self, rows: list[tuple[uuid.UUID, str]]) -> None:
        self.rows = rows
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Rows(self.rows)


def test_near_duplicate_candidates_have_severity_and_evidence() -> None:
    original_id = uuid.uuid4()
    request = PaymentRequest(
        id=uuid.uuid4(),
        vendor_id=uuid.uuid4(),
        invoice_no="INV-2026-0421",
        issue_date=date(2026, 2, 1),
        fingerprint=b"x" * 32,
    )
    session = _Session([(original_id, "INV-2026-0412")])

    matches = asyncio.run(find_near_duplicates(session, request))

    assert [(match.distance, match.severity) for match in matches] == [(1, "HIGH")]
    assert matches[0].evidence(request.invoice_no) == {
        "otherRequestId": str(original_id),
        "invoiceNo": "INV-2026-0421",
        "otherInvoiceNo": "INV-2026-0412",
        "distance": 1,
    }
    sql = str(
        session.statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "vendor_id" in sql and "amount" in sql and "issue_date" in sql
    assert RequestStatus.REJECTED.value in sql and RequestStatus.CANCELLED.value in sql

    recurring = PaymentRequest(
        id=uuid.uuid4(),
        vendor_id=request.vendor_id,
        invoice_no="RENT-OCT",
        issue_date=request.issue_date,
        fingerprint=b"y" * 32,
    )
    session = _Session([(uuid.uuid4(), "RENT-SEP")])
    matches = asyncio.run(find_near_duplicates(session, recurring))
    assert [(match.distance, match.severity) for match in matches] == [(3, "LOW")]


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL performance test",
)
def test_near_duplicate_lookup_is_fast_for_ten_thousand_vendor_requests() -> None:
    async def run() -> float:
        engine = create_async_engine(os.environ["TP_TEST_DATABASE_URL"])
        try:
            async with engine.connect() as connection:
                await connection.execute(
                    text(
                        "CREATE TEMP TABLE payment_requests ("
                        "id uuid, vendor_id uuid, amount numeric(78,0), issue_date date, "
                        "status text, fingerprint bytea, invoice_no text) ON COMMIT PRESERVE ROWS"
                    )
                )
                await connection.execute(
                    text(
                        "CREATE INDEX ix_payment_requests_vendor_amount_issue_date "
                        "ON payment_requests (vendor_id, amount, issue_date)"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO payment_requests "
                        "SELECT md5(i::text)::uuid, '00000000-0000-7000-8000-000000000001', "
                        "3000, date '2000-01-01' + i, 'Draft', "
                        "decode(lpad(to_hex(i), 64, '0'), 'hex'), 'RENT-' || i::text "
                        "FROM generate_series(1, 10000) AS i"
                    )
                )
                request = PaymentRequest(
                    id=uuid.uuid4(),
                    vendor_id=uuid.UUID("00000000-0000-7000-8000-000000000001"),
                    amount=3000,
                    issue_date=date(2013, 9, 9),
                    invoice_no="RENT-5001",
                    fingerprint=b"x" * 32,
                )
                session = AsyncSession(bind=connection)
                try:
                    started = perf_counter()
                    matches = await find_near_duplicates(session, request)
                    elapsed = perf_counter() - started
                finally:
                    await session.close()
                assert matches
                return elapsed
        finally:
            await engine.dispose()

    elapsed = asyncio.run(run())
    assert elapsed < 0.05, f"10,000-row candidate lookup took {elapsed * 1000:.1f} ms"
