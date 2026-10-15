"""Invoice extraction task body (AGT-004): attached document -> `extractions` row + draft prefill.
Instruction-like text (AGT-006) becomes a HIGH flag: the model's `suspicious_instructions`, or a
keyword scan of the PDF text when the LLM is down.

The model's answer is advisory. Only invoice number, dates and amount are prefilled, each
after a deterministic check, and only where the draft is still empty. The vendor, the payee
and its address are never applied: `payee_address_as_found` is stored for comparison only.
On any `AiError` the request goes to manual entry and nothing is written but that status.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from typing import Any, Protocol

import asyncpg  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader

from treasurypilot_core.domain import PaymentTerms
from treasurypilot_core.engine import InvalidTerms, validate_terms
from treasurypilot_core.ids import uuid7
from treasurypilot_core.money import BaseUnits
from treasurypilot_worker.agent import (
    AiAdapter,
    AiError,
    AiTask,
    DocumentBlock,
    SourceKind,
    UntrustedSource,
)
from treasurypilot_worker.agent.instruction_detector import (
    INSTRUCTION_REASON_CODE,
    INSTRUCTION_SEVERITY,
    MAX_QUOTE_CHARS,
    detect_instructions,
)
from treasurypilot_worker.agent.prompts.extract import EXTRACT_TEMPLATE
from treasurypilot_worker.locks import _asyncpg_database_url

logger = logging.getLogger(__name__)

MAX_INVOICE_NO_CHARS = 200
MAX_FLAGGED_QUOTES = 10  # bounds the flag evidence, whatever the model returns


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Located(_Strict):
    """A value as printed, with where it was found."""

    value: str
    page: int = Field(ge=1)
    span: str


class SuspiciousInstruction(_Strict):
    """Instruction-like text found in the document (AGT-006); reported, never acted on."""

    quote: str
    page: int = Field(ge=1)


class LateFeeExtraction(_Strict):
    kind: str
    amount_text: str | None = None
    rate_bps: int | None = None
    period_days: int | None = None
    cap_text: str | None = None


class TermsExtraction(_Strict):
    """Payment terms as printed (AGT-005). `uncertain` means a human must choose."""

    discount_bps: int | None = None
    discount_days: int | None = None
    net_days: int | None = None
    late_fee: LateFeeExtraction | None = None
    priority_note: str | None = None
    uncertain: bool
    uncertain_reason: str | None = None


class InvoiceExtraction(_Strict):
    vendor_name: Located | None
    invoice_no: Located | None
    issue_date: Located | None
    due_date: Located | None
    amount_text: Located | None
    currency: Located | None
    payee_address_as_found: Located | None
    terms: TermsExtraction | None
    invoice_count_in_document: int = Field(ge=1)
    suspicious_instructions: list[SuspiciousInstruction]


class DocumentReader(Protocol):
    def read(self, storage_key: str) -> bytes: ...


def prefill_values(
    extraction: InvoiceExtraction, *, asset_symbol: str, decimals: int, pages: int | None
) -> dict[str, Any]:
    """Draft columns the extraction may fill. A field that fails its check is left out."""

    if extraction.invoice_count_in_document != 1:
        return {}  # M05 rejects multi-invoice documents; nothing to prefill

    def text(field: Located | None) -> str | None:
        if field is None or (pages is not None and field.page > pages):
            return None  # provenance points outside the document
        return field.value.strip() or None

    values: dict[str, Any] = {}
    invoice_no = text(extraction.invoice_no)
    if invoice_no is not None and len(invoice_no) <= MAX_INVOICE_NO_CHARS:
        values["invoice_no"] = invoice_no
    issue, due = _iso_date(text(extraction.issue_date)), _iso_date(text(extraction.due_date))
    if issue is not None and due is not None and due < issue:
        issue = due = None
    for column, parsed in (("issue_date", issue), ("due_at", due)):
        if parsed is not None:
            values[column] = parsed
    amount, currency = text(extraction.amount_text), text(extraction.currency)
    if amount is not None and currency is not None and currency.upper() == asset_symbol.upper():
        try:
            base_units = BaseUnits.parse(amount, decimals)
        except ValueError:
            base_units = None
        if base_units and base_units < 1 << 256:  # zero is not a payable amount
            values["amount"] = int(base_units)
    return values


def terms_values(extraction: InvoiceExtraction, *, decimals: int) -> dict[str, Any] | None:
    """Provisional (unconfirmed) terms for the draft, or None when a human must choose.

    The model's `uncertain` flag is advisory: the terms must also pass the engine model
    and `validate_terms`. `priority_note` is untrusted text and is never copied.
    """

    terms = extraction.terms
    if terms is None:
        return None
    if terms.uncertain or terms.net_days is None:
        logger.debug("terms_dropped reason=%s", terms.uncertain_reason or "net_days missing")
        return None
    if (terms.discount_bps is None) != (terms.discount_days is None):
        logger.debug("terms_dropped reason=partial_discount")  # ambiguous, not "no discount"
        return None

    def units(text: str | None) -> int | None:
        return None if text is None else int(BaseUnits.parse(text, decimals))

    try:
        fee = terms.late_fee
        parsed = PaymentTerms.model_validate(
            {
                "net_due_day": terms.net_days,
                "discount_bps": terms.discount_bps or 0,
                "discount_deadline_day": terms.discount_days,
                "late_fee": None
                if fee is None
                else {
                    "kind": fee.kind,
                    "amount": units(fee.amount_text),
                    "rate_bps": fee.rate_bps,
                    "period_days": fee.period_days,
                    "cap": units(fee.cap_text),
                },
            }
        )
        validate_terms(parsed)
    except (ValueError, InvalidTerms) as error:  # pydantic's ValidationError is a ValueError
        logger.debug("terms_dropped reason=invalid %s", type(error).__name__)
        return None
    return parsed.model_dump(mode="json", exclude_none=True)


def _iso_date(value: str | None) -> date | None:
    try:
        return None if value is None else date.fromisoformat(value)
    except ValueError:
        return None


def llm_flag_evidence(extraction: InvoiceExtraction) -> dict[str, Any] | None:
    """Evidence for the AI-sourced flag, or None when the model reported nothing."""

    found = extraction.suspicious_instructions[:MAX_FLAGGED_QUOTES]
    if not found:
        return None
    return {
        "detector": "llm",
        "reducedCoverage": False,
        "matches": [{"quote": f.quote[:MAX_QUOTE_CHARS], "page": f.page} for f in found],
    }


def fallback_flag_evidence(
    mime: str, body: bytes, known_addresses: list[str]
) -> dict[str, Any] | None:
    """Keyword scan of the PDF text layer for when the LLM is down (reduced coverage).

    shortcut: images and scanned PDFs have no text layer, so they are not scanned; upgrade
    when OCR exists.
    """

    pages: list[str] = []
    if mime == "application/pdf":
        try:
            pages = [page.extract_text() or "" for page in PdfReader(BytesIO(body)).pages]
        except Exception:  # a malformed PDF is already on the manual-entry path
            logger.warning("instruction_fallback_unreadable_pdf")
    scan = detect_instructions(pages, known_addresses=known_addresses)
    if not scan.matches:
        return None
    return {
        "detector": scan.detector,
        "reducedCoverage": scan.reduced_coverage,
        "matches": [
            {"quote": m.quote, "page": m.page, "rules": list(m.rules)}
            for m in scan.matches[:MAX_FLAGGED_QUOTES]
        ],
    }


@dataclass(frozen=True)
class _Job:
    org_id: uuid.UUID
    storage_key: str
    mime: str
    pages: int | None
    asset_symbol: str
    decimals: int
    treasury_id: uuid.UUID


_LOAD = """
SELECT r.org_id, d.storage_key, d.mime, d.pages, a.symbol, a.decimals, r.treasury_id
FROM payment_requests r
JOIN documents d ON d.request_id = r.id AND d.id = $2
JOIN assets a ON a.id = r.asset_id AND a.chain_id = r.chain_id
WHERE r.id = $1 AND r.source = 'UPLOAD' AND r.extraction_status = 'Extracting'
  AND r.extraction_confirmed_by IS NULL
"""
# Guarded like _LOAD, so a redelivered task cannot overwrite what the operator has since done.
_MANUAL_ENTRY = """
UPDATE payment_requests SET extraction_status = 'ManualEntry', updated_at = now()
WHERE id = $1 AND extraction_status = 'Extracting'
"""
_INSERT_FLAG = f"""
INSERT INTO flags (id, request_id, revision, code, severity, evidence, source)
SELECT $1, id, current_revision, '{INSTRUCTION_REASON_CODE}', '{INSTRUCTION_SEVERITY}',
  $3::jsonb, $4
FROM payment_requests WHERE id = $2
"""
# Run after _EXTRACTED in one transaction: that UPDATE holds the payment_requests row lock the
# API's confirm takes with FOR UPDATE, so this NOT EXISTS cannot race its check-then-insert.
_INSERT_MULTI_INVOICE_FLAG = """
INSERT INTO flags (id, request_id, revision, code, severity, evidence, source)
SELECT $1, r.id, r.current_revision, 'MULTI_INVOICE_DOCUMENT', 'HIGH',
  jsonb_build_object('invoiceCountInDocument', $2::integer), 'AI'
FROM payment_requests r
WHERE r.id = $3
  AND NOT EXISTS (
    SELECT 1 FROM flags f
    WHERE f.request_id = r.id AND f.code = 'MULTI_INVOICE_DOCUMENT' AND f.status = 'Open'
  )
"""
_PAYEE_ADDRESSES = "SELECT '0x' || encode(address, 'hex') FROM payees WHERE treasury_id = $1"
_EXTRACTED = """
UPDATE payment_requests SET extraction_status = 'Extracted',
  invoice_no = COALESCE(invoice_no, $2), issue_date = COALESCE(issue_date, $3),
  due_at = COALESCE(due_at, $4), amount = COALESCE(amount, $5),
  terms = COALESCE(terms, $6::jsonb),
  version = version + 1, updated_at = now()
WHERE id = $1 AND extraction_status = 'Extracting' AND extraction_confirmed_by IS NULL
"""
_INSERT_EXTRACTION = """
INSERT INTO extractions (id, document_id, ai_call_id, fields) VALUES ($1, $2, $3, $4::jsonb)
"""


async def _with_connection(database_url: str, work: Any) -> Any:
    connection = await asyncpg.connect(_asyncpg_database_url(database_url))
    try:
        return await work(connection)
    finally:
        await connection.close()


async def _add_flag(
    connection: asyncpg.Connection, request_id: uuid.UUID, evidence: dict[str, Any], source: str
) -> None:
    """HIGH flag on the request's current revision. It informs the approver; nothing else changes."""

    await connection.execute(_INSERT_FLAG, uuid7(), request_id, json.dumps(evidence), source)


def extract_invoice_document(
    request_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    adapter: AiAdapter,
    reader: DocumentReader,
    database_url: str,
) -> str:
    """Run the extraction for one upload; returns "Extracted", "ManualEntry" or "skipped".

    Redeliveries are harmless: only a request still `Extracting` is processed. An
    `AiCallLogError` is not caught: with no decision record there is no result (F-093).
    """

    async def load(connection: asyncpg.Connection) -> _Job | None:
        row = await connection.fetchrow(_LOAD, request_id, document_id)
        return None if row is None else _Job(*row)

    job: _Job | None = asyncio.run(_with_connection(database_url, load))
    if job is None:
        return "skipped"

    body = reader.read(job.storage_key)
    try:
        result = adapter.run(
            AiTask.EXTRACT,
            org_id=str(job.org_id),
            prompt=EXTRACT_TEMPLATE.render(
                invoice=DocumentBlock(
                    str(UntrustedSource(SourceKind.DOCUMENT, str(document_id))), job.mime, body
                )
            ),
            output=InvoiceExtraction,
        )
    except AiError as error:
        logger.warning(
            "invoice_extraction_manual_entry",
            extra={"request_id": str(request_id), "error": type(error).__name__},
        )

        async def manual_entry(connection: asyncpg.Connection) -> None:
            known = [r[0] for r in await connection.fetch(_PAYEE_ADDRESSES, job.treasury_id)]
            evidence = fallback_flag_evidence(job.mime, body, known)
            async with connection.transaction():
                updated = await connection.execute(_MANUAL_ENTRY, request_id)
                if evidence is not None and updated == "UPDATE 1":
                    await _add_flag(connection, request_id, evidence, "DETERMINISTIC")

        asyncio.run(_with_connection(database_url, manual_entry))
        return "ManualEntry"

    values = prefill_values(
        result.output, asset_symbol=job.asset_symbol, decimals=job.decimals, pages=job.pages
    )

    terms = terms_values(result.output, decimals=job.decimals)  # stays unconfirmed (INV-008)

    async def save(connection: asyncpg.Connection) -> str:
        async with connection.transaction():
            updated = await connection.execute(
                _EXTRACTED,
                request_id,
                values.get("invoice_no"),
                values.get("issue_date"),
                values.get("due_at"),
                values.get("amount"),
                None if terms is None else json.dumps(terms),
            )
            if updated != "UPDATE 1":
                return "skipped"  # confirmed or settled by someone else meanwhile
            await connection.execute(
                _INSERT_EXTRACTION,
                uuid7(),
                document_id,
                uuid.UUID(result.ai_call_id),
                json.dumps(result.output.model_dump(mode="json")),
            )
            if result.output.invoice_count_in_document > 1:
                await connection.execute(
                    _INSERT_MULTI_INVOICE_FLAG,
                    uuid7(),
                    result.output.invoice_count_in_document,
                    request_id,
                )
            if (evidence := llm_flag_evidence(result.output)) is not None:
                await _add_flag(connection, request_id, evidence, "AI")
        return "Extracted"

    return str(asyncio.run(_with_connection(database_url, save)))
