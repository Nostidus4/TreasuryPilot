"""Pure deterministic invoice anomaly rules."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

_AMOUNT_HISTORY_DAYS = 365
_MINIMUM_AMOUNT_HISTORY = 5


@dataclass(frozen=True, slots=True)
class AnomalyFlag:
    code: str
    severity: str
    evidence: dict[str, object]


@dataclass(frozen=True, slots=True)
class PaidInvoice:
    amount: int
    paid_on: date
    payee_id: uuid.UUID
    payee_address: bytes


@dataclass(frozen=True, slots=True)
class InvoiceRevisionSignals:
    issue_date: date
    due_date: date
    amount: int
    payee_id: uuid.UUID
    payee_address: bytes
    asset_symbol: str
    chain_name: str
    document_address: bytes | None = None
    document_currency: str | None = None
    document_chain: str | None = None
    ai_available: bool | None = None


def _median_lower(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def evaluate_anomalies(
    revision: InvoiceRevisionSignals,
    history: tuple[PaidInvoice, ...],
    *,
    registered_addresses: tuple[bytes, ...],
    prior_paid_to_payee: bool,
    previous_paid: PaidInvoice | None,
    today: date,
) -> list[AnomalyFlag]:
    """Evaluate flags without I/O; output depends only on revision and supplied history."""

    flags: list[AnomalyFlag] = []
    if revision.due_date < revision.issue_date:
        flags.append(
            AnomalyFlag(
                "DUE_BEFORE_ISSUE",
                "HIGH",
                {
                    "dueDate": revision.due_date.isoformat(),
                    "issueDate": revision.issue_date.isoformat(),
                },
            )
        )
    if revision.due_date < today:
        flags.append(
            AnomalyFlag(
                "DUE_DATE_PAST",
                "LOW",
                {"dueDate": revision.due_date.isoformat()},
            )
        )
    if revision.due_date > revision.issue_date + timedelta(days=120):
        flags.append(
            AnomalyFlag(
                "DUE_DATE_FAR",
                "LOW",
                {"dueDate": revision.due_date.isoformat(), "thresholdDays": 120},
            )
        )

    if not prior_paid_to_payee:
        flags.append(
            AnomalyFlag(
                "FIRST_PAYMENT_TO_PAYEE",
                "LOW",
                {"payeeId": str(revision.payee_id)},
            )
        )
    if previous_paid is not None and previous_paid.payee_address != revision.payee_address:
        flags.append(
            AnomalyFlag(
                "ADDRESS_CHANGED",
                "HIGH",
                {
                    "previousAddress": "0x" + previous_paid.payee_address.hex(),
                    "currentAddress": "0x" + revision.payee_address.hex(),
                    "previousPayeeId": str(previous_paid.payee_id),
                    "currentPayeeId": str(revision.payee_id),
                },
            )
        )

    if (
        revision.document_address is not None
        and revision.document_address not in registered_addresses
    ):
        flags.append(
            AnomalyFlag(
                "ADDRESS_NOT_REGISTERED",
                "HIGH",
                {"documentAddress": "0x" + revision.document_address.hex()},
            )
        )
    if (
        revision.document_currency is not None
        and revision.document_currency.strip().casefold()
        != revision.asset_symbol.strip().casefold()
    ):
        flags.append(
            AnomalyFlag(
                "CURRENCY_MISMATCH",
                "HIGH",
                {
                    "documentCurrency": revision.document_currency,
                    "assetSymbol": revision.asset_symbol,
                },
            )
        )
    if (
        revision.document_chain is not None
        and revision.document_chain.strip().casefold() != revision.chain_name.strip().casefold()
    ):
        flags.append(
            AnomalyFlag(
                "CHAIN_MISMATCH",
                "HIGH",
                {"documentChain": revision.document_chain, "chainName": revision.chain_name},
            )
        )
    if revision.ai_available is False:
        flags.append(AnomalyFlag("AI_UNAVAILABLE", "LOW", {"deterministicOnly": True}))

    recent_amounts = [
        item.amount
        for item in history
        if today - timedelta(days=_AMOUNT_HISTORY_DAYS) <= item.paid_on <= today
    ]
    if len(recent_amounts) < _MINIMUM_AMOUNT_HISTORY:
        flags.append(
            AnomalyFlag(
                "NO_BASELINE",
                "LOW",
                {"historyCount": len(recent_amounts), "minimumHistory": _MINIMUM_AMOUNT_HISTORY},
            )
        )
    else:
        median = _median_lower(recent_amounts)
        mad = _median_lower([abs(amount - median) for amount in recent_amounts])
        deviation = abs(revision.amount - median)
        # Compare against 3 * max(1.4826 * MAD, 0.02 * median) without floats.
        is_outlier = deviation * 5000 > max(22239 * mad, 300 * median)
        if is_outlier:
            flags.append(
                AnomalyFlag(
                    "AMOUNT_OUTLIER",
                    "HIGH",
                    {
                        "amount": revision.amount,
                        "median": median,
                        "mad": mad,
                        "deviation": deviation,
                        "historyCount": len(recent_amounts),
                    },
                )
            )
    return flags
