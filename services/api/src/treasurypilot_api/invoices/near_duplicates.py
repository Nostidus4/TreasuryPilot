"""Indexed candidate lookup and deterministic near-duplicate evidence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.invoices.models import PaymentRequest, RequestStatus
from treasurypilot_core.fingerprint import damerau_levenshtein, normalize

_EXCLUDED_STATUSES = (RequestStatus.REJECTED.value, RequestStatus.CANCELLED.value)
_DATE_WINDOW_DAYS = 45


@dataclass(frozen=True, slots=True)
class NearDuplicate:
    request_id: uuid.UUID
    invoice_no: str
    distance: int

    @property
    def severity(self) -> str:
        return "HIGH" if self.distance <= 2 else "LOW"

    def evidence(self, invoice_no: str) -> dict[str, object]:
        return {
            "otherRequestId": str(self.request_id),
            "invoiceNo": invoice_no,
            "otherInvoiceNo": self.invoice_no,
            "distance": self.distance,
        }


async def find_near_duplicates(
    session: AsyncSession, request: PaymentRequest
) -> list[NearDuplicate]:
    """Find same-vendor/amount requests in the indexed 45-day issue-date window."""

    if request.fingerprint is None:
        return []
    candidates = await session.execute(
        select(PaymentRequest.id, PaymentRequest.invoice_no).where(
            PaymentRequest.id != request.id,
            PaymentRequest.vendor_id == request.vendor_id,
            PaymentRequest.amount == request.amount,
            PaymentRequest.issue_date.between(
                request.issue_date - timedelta(days=_DATE_WINDOW_DAYS),
                request.issue_date + timedelta(days=_DATE_WINDOW_DAYS),
            ),
            PaymentRequest.status.not_in(_EXCLUDED_STATUSES),
            PaymentRequest.fingerprint.is_not(None),
            PaymentRequest.fingerprint != request.fingerprint,
        )
    )
    normalized_invoice = normalize(request.invoice_no)
    matches: list[NearDuplicate] = []
    for candidate_id, candidate_invoice in candidates:
        distance = damerau_levenshtein(normalized_invoice, normalize(candidate_invoice))
        matches.append(NearDuplicate(candidate_id, candidate_invoice, distance))
    return matches
