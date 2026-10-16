"""Reconciled payment -> ERP bill/payment mapping (REC-L01): integer money, no guessing."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from treasurypilot_api.integrations.erp.mapping import (
    ReconciledPayment,
    currency_decimals,
    export_key,
    to_bill,
    to_payment,
)
from treasurypilot_api.integrations.erp.provider import ErpPermanentError

RID, CID = uuid.uuid4(), uuid.uuid4()


def payment(**overrides: object) -> ReconciledPayment:
    values: dict[str, object] = {
        "reconciliation_id": RID,
        "request_id": uuid.uuid4(),
        "status": "Matched",
        "invoice_no": "INV-7",
        "vendor_name": "Acme",
        "issue_date": date(2026, 10, 1),
        "due_date": date(2026, 10, 31),
        "amount": 1_500_000,
        "asset_symbol": "USDC",
        "asset_decimals": 6,
        "fiat_amount_minor": None,
        "fiat_currency": None,
        "tx_hash": bytes.fromhex("ab" * 32),
        "paid_on": date(2026, 10, 15),
    }
    values.update(overrides)
    return ReconciledPayment(**values)  # type: ignore[arg-type]


def test_usd_stablecoin_is_booked_as_usd_cents() -> None:
    bill = to_bill(payment(), "k")
    assert (bill.currency, bill.amount_minor, bill.currency_decimals) == ("USD", 150, 2)
    assert bill.reference == "INV-7" and bill.expense_account_code == "6000"


def test_fiat_amount_on_the_request_wins() -> None:
    bill = to_bill(payment(fiat_amount_minor=123_456, fiat_currency="EUR"), "k")
    assert (bill.currency, bill.amount_minor) == ("EUR", 123_456)


def test_sub_cent_precision_is_refused_not_rounded() -> None:
    with pytest.raises(ErpPermanentError, match="AMOUNT_NOT_REPRESENTABLE"):
        to_bill(payment(amount=1_500_001), "k")


def test_non_stable_asset_without_fiat_value_is_refused() -> None:
    with pytest.raises(ErpPermanentError, match="NO_FIAT_VALUE"):
        to_bill(payment(asset_symbol="WETH", asset_decimals=18), "k")


def test_low_decimal_stablecoin_scales_up() -> None:
    assert to_bill(payment(amount=7, asset_decimals=0), "k").amount_minor == 700


def test_payment_references_the_tx_hash_and_uses_the_bank_account() -> None:
    result = to_payment(payment(), "090", "pk")
    assert result.tx_hash == "0x" + "ab" * 32
    assert (result.payment_account_code, result.paid_on, result.amount_minor) == (
        "090",
        date(2026, 10, 15),
        150,
    )


def test_payment_without_an_onchain_transaction_is_refused() -> None:
    with pytest.raises(ErpPermanentError, match="NOT_PAID_ON_CHAIN"):
        to_payment(payment(tx_hash=None), "090", "pk")


def test_currency_decimals_and_keys() -> None:
    assert (currency_decimals("JPY"), currency_decimals("KWD"), currency_decimals("USD")) == (
        0,
        3,
        2,
    )
    assert export_key("BILL", RID, CID) == export_key("BILL", RID, CID)
    assert export_key("BILL", RID, CID) != export_key("PAYMENT", RID, CID)
    assert len(export_key("PAYMENT", RID, CID)) <= 128
