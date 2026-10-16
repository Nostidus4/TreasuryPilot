"""Map a reconciled payment request to ERP bill and payment objects (pure, no I/O).

Money stays in integer minor units end to end. A bill is priced in the request's fiat
amount when it has one, otherwise a USD-pegged stablecoin is booked as USD; anything else
has no fiat value and is refused rather than guessed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from treasurypilot_api.integrations.erp.provider import ErpBill, ErpPayment, ErpPermanentError

USD_STABLECOINS = frozenset({"USDC", "USDT", "DAI", "PYUSD", "USDS", "FDUSD"})
_ZERO_DECIMAL = frozenset({"JPY", "KRW", "VND", "CLP", "ISK", "UGX", "XAF", "XOF"})
_THREE_DECIMAL = frozenset({"KWD", "BHD", "OMR", "JOD", "TND"})
DEFAULT_EXPENSE_ACCOUNT = "6000"  # the generic EXTERNAL_EXPENSE debit code (M11-D6)


def currency_decimals(currency: str) -> int:
    if currency in _ZERO_DECIMAL:
        return 0
    return 3 if currency in _THREE_DECIMAL else 2


@dataclass(frozen=True, slots=True)
class ReconciledPayment:
    reconciliation_id: uuid.UUID
    request_id: uuid.UUID
    status: str  # Pending | Matched | Discrepancy
    invoice_no: str
    vendor_name: str
    issue_date: date
    due_date: date
    amount: int  # asset base units
    asset_symbol: str
    asset_decimals: int
    fiat_amount_minor: int | None
    fiat_currency: str | None
    tx_hash: bytes | None  # the EXTERNAL_EXPENSE transaction
    paid_on: date | None
    expense_account_code: str = DEFAULT_EXPENSE_ACCOUNT


def export_key(kind: str, reconciliation_id: uuid.UUID, connection_id: uuid.UUID) -> str:
    """Deterministic per (object, reconciliation, connection); sent as the ERP idempotency key."""

    return f"tp-{kind.lower()}-{reconciliation_id}-{connection_id.hex[:8]}"


def _priced(data: ReconciledPayment) -> tuple[str, int]:
    """(currency, amount in that currency's minor units)."""

    if data.fiat_amount_minor is not None and data.fiat_currency:
        return data.fiat_currency, data.fiat_amount_minor
    symbol = data.asset_symbol.upper()
    if symbol not in USD_STABLECOINS:
        raise ErpPermanentError(f"NO_FIAT_VALUE: {symbol} has no fiat price on this request")
    shift = data.asset_decimals - currency_decimals("USD")
    if shift < 0:
        return "USD", data.amount * 10**-shift
    quotient, remainder = divmod(data.amount, 10**shift)
    if remainder:
        raise ErpPermanentError("AMOUNT_NOT_REPRESENTABLE: amount has sub-cent precision")
    return "USD", quotient


def to_bill(data: ReconciledPayment, idempotency_key: str) -> ErpBill:
    currency, minor = _priced(data)
    return ErpBill(
        reference=data.invoice_no,
        idempotency_key=idempotency_key,
        vendor_name=data.vendor_name,
        issue_date=data.issue_date,
        due_date=data.due_date,
        currency=currency,
        amount_minor=minor,
        currency_decimals=currency_decimals(currency),
        description=f"Invoice {data.invoice_no} (TreasuryPilot request {data.request_id})",
        expense_account_code=data.expense_account_code,
    )


def to_payment(
    data: ReconciledPayment, payment_account_code: str, idempotency_key: str
) -> ErpPayment:
    if data.tx_hash is None or data.paid_on is None:
        raise ErpPermanentError("NOT_PAID_ON_CHAIN: no external payment transaction")
    currency, minor = _priced(data)
    return ErpPayment(
        bill_reference=data.invoice_no,
        idempotency_key=idempotency_key,
        paid_on=data.paid_on,
        currency=currency,
        amount_minor=minor,
        currency_decimals=currency_decimals(currency),
        tx_hash="0x" + data.tx_hash.hex(),
        payment_account_code=payment_account_code,
    )
