"""Deterministic checks between the model's answer and the draft prefill (AGT-004)."""

import json
from datetime import date
from pathlib import Path

from treasurypilot_worker.invoices.extraction import InvoiceExtraction, prefill_values

SAMPLE = json.loads(
    (Path(__file__).parent / "fixtures" / "invoice_extraction_sample.json").read_text()
)


def _extraction(**overrides: object) -> InvoiceExtraction:
    return InvoiceExtraction.model_validate({**SAMPLE, **overrides})


def _located(value: str, page: int = 1) -> dict[str, object]:
    return {"value": value, "page": page, "span": value}


def test_sample_invoice_prefills_text_dates_and_base_units() -> None:
    values = prefill_values(_extraction(), asset_symbol="USDC", decimals=6, pages=1)

    assert values == {
        "invoice_no": "INV-2026-0042",
        "issue_date": date(2026, 10, 1),
        "due_at": date(2026, 10, 31),
        "amount": 1_250_500_000,
    }


def test_amount_in_another_currency_is_not_converted_or_guessed() -> None:
    values = prefill_values(
        _extraction(currency=_located("EUR")), asset_symbol="USDC", decimals=6, pages=1
    )

    assert "amount" not in values and values["invoice_no"] == "INV-2026-0042"


def test_ambiguous_amount_text_is_left_for_the_operator() -> None:
    for text in ("1,250.50", "1250.5000001", "0", "twelve"):
        values = prefill_values(
            _extraction(amount_text=_located(text)), asset_symbol="USDC", decimals=6, pages=1
        )
        assert "amount" not in values, text


def test_field_citing_a_page_the_document_lacks_is_not_applied() -> None:
    values = prefill_values(
        _extraction(invoice_no=_located("INV-9", page=3)), asset_symbol="USDC", decimals=6, pages=2
    )

    assert "invoice_no" not in values


def test_non_iso_or_inverted_dates_are_not_applied() -> None:
    non_iso = prefill_values(
        _extraction(issue_date=_located("01/10/2026")), asset_symbol="USDC", decimals=6, pages=1
    )
    inverted = prefill_values(
        _extraction(due_date=_located("2026-09-01")), asset_symbol="USDC", decimals=6, pages=1
    )

    assert "issue_date" not in non_iso and non_iso["due_at"] == date(2026, 10, 31)
    assert "issue_date" not in inverted and "due_at" not in inverted


def test_document_with_several_invoices_prefills_nothing() -> None:
    values = prefill_values(
        _extraction(invoice_count_in_document=2), asset_symbol="USDC", decimals=6, pages=1
    )

    assert values == {}
