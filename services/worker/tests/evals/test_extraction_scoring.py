"""Scoring logic of the extraction accuracy eval (AGT-013)."""

from typing import Any

import pytest

from treasurypilot_worker.evals.extraction_scoring import (
    FIELDS,
    TermsCounts,
    expected_terms,
    f1_score,
    predicted_terms,
    score_case,
    score_failure,
    summarize,
)
from treasurypilot_worker.invoices.extraction import InvoiceExtraction, TermsExtraction

LABEL: dict[str, Any] = {
    "id": "inv-900",
    "vendor_name": "SYNTH Vendor Ltd",
    "invoice_no": "TEST-INV-0900",
    "issue_date": "2026-10-01",
    "amount": "125000000",
    "currency": "USDC",
    "payee_address": "0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD",
    "due_date": "2026-10-31",
    "terms": {
        "net_due_date": "2026-10-31",
        "priority_note": "n/a",
        "discount_bps": 200,
        "discount_deadline": "2026-10-11",
        "late_fee": {"type": "percent_per_period", "rate_bps": 150, "period_days": 7},
    },
}


def located(value: str) -> dict[str, Any]:
    return {"value": value, "page": 1, "span": value}


def extraction(**overrides: Any) -> InvoiceExtraction:
    data: dict[str, Any] = {
        "vendor_name": located("SYNTH Vendor Ltd"),
        "invoice_no": located("TEST-INV-0900"),
        "issue_date": located("2026-10-01"),
        "due_date": located("2026-10-31"),
        "amount_text": located("125.000000"),
        "currency": located("USDC"),
        "payee_address_as_found": located("0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"),
        "terms": {
            "discount_bps": 200,
            "discount_days": 10,
            "net_days": 30,
            "late_fee": {"kind": "percent_per_period", "rate_bps": 150, "period_days": 7},
            "uncertain": False,
        },
        "invoice_count_in_document": 1,
        "suspicious_instructions": [],
    }
    return InvoiceExtraction.model_validate({**data, **overrides})


def test_perfect_extraction_scores_every_field_and_all_terms() -> None:
    score = score_case("inv-900", LABEL, extraction(), decimals=6)

    assert all(score.fields[name] for name in FIELDS)
    assert score.terms == TermsCounts(6, 0, 0) and score.terms.exact and not score.misses


def test_amount_is_compared_in_base_units_not_text() -> None:
    same = score_case("x", LABEL, extraction(amount_text=located("125")), decimals=6)
    off_by_one = score_case("x", LABEL, extraction(amount_text=located("125.000001")), decimals=6)

    assert same.fields["amount"] and not off_by_one.fields["amount"]
    assert off_by_one.misses["amount"] == ("125000000", "125000001")


def test_amount_the_prefill_cannot_parse_is_a_miss() -> None:
    for text in ("125.000,000000", "1,250.50", "twelve", "125.0000001"):
        score = score_case("x", LABEL, extraction(amount_text=located(text)), decimals=6)
        assert not score.fields["amount"], text


def test_exact_match_trims_whitespace_but_nothing_else() -> None:
    padded = score_case(
        "x", LABEL, extraction(vendor_name=located("  SYNTH Vendor Ltd ")), decimals=6
    )
    cased = score_case("x", LABEL, extraction(vendor_name=located("synth vendor ltd")), decimals=6)

    assert padded.fields["vendor_name"] and not cased.fields["vendor_name"]


def test_missing_and_wrong_dates_are_misses() -> None:
    score = score_case(
        "x", LABEL, extraction(issue_date=None, due_date=located("31/10/2026")), decimals=6
    )

    assert not score.fields["issue_date"] and not score.fields["due_date"]
    assert score.misses["issue_date"] == ("2026-10-01", None)


def test_payee_address_ignores_hex_case() -> None:
    score = score_case(
        "x",
        LABEL,
        extraction(payee_address_as_found=located("0xABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCD")),
        decimals=6,
    )

    assert score.fields["payee_address"]


def test_expected_terms_are_day_offsets_from_the_issue_date() -> None:
    assert expected_terms(LABEL) == {
        ("net_days", 30),
        ("discount_bps", 200),
        ("discount_days", 10),
        ("late_fee.kind", "percent_per_period"),
        ("late_fee.rate_bps", 150),
        ("late_fee.period_days", 7),
    }
    assert expected_terms({**LABEL, "terms": None}) == frozenset()


def test_wrong_discount_days_costs_one_false_positive_and_one_false_negative() -> None:
    wrong = {**extraction().terms.model_dump(), "discount_days": 15}  # type: ignore[union-attr]
    score = score_case("x", LABEL, extraction(terms=wrong), decimals=6)

    assert score.terms == TermsCounts(5, 1, 1) and not score.terms.exact


def test_terms_invented_for_an_invoice_without_any_hurt_precision_only() -> None:
    label = {**LABEL, "terms": None}
    score = score_case(
        "x", label, extraction(terms={"net_days": 30, "uncertain": False}), decimals=6
    )

    assert score.terms == TermsCounts(0, 1, 0)
    assert f1_score([score.terms]).precision == 0.0


def test_missing_terms_hurt_recall_only() -> None:
    score = score_case("x", LABEL, extraction(terms=None), decimals=6)

    assert score.terms == TermsCounts(0, 0, 6)
    result = f1_score([score.terms])
    assert result.precision == 1.0 and result.recall == 0.0 and result.f1 == 0.0


def test_uncertain_flag_does_not_change_the_terms_score() -> None:
    uncertain = TermsExtraction(net_days=30, uncertain=True, uncertain_reason="ambiguous")

    assert predicted_terms(uncertain) == {("net_days", 30)}


def test_f1_is_micro_averaged_across_invoices() -> None:
    result = f1_score([TermsCounts(6, 0, 0), TermsCounts(1, 1, 5)])

    assert result.precision == pytest.approx(7 / 8)
    assert result.recall == pytest.approx(7 / 12)
    assert result.f1 == pytest.approx(2 * (7 / 8) * (7 / 12) / (7 / 8 + 7 / 12))


def test_f1_with_nothing_expected_or_predicted_is_one() -> None:
    assert f1_score([TermsCounts(0, 0, 0)]).f1 == 1.0
    assert f1_score([]).f1 == 1.0


def test_pipeline_failure_misses_every_field_and_every_term() -> None:
    score = score_failure("inv-900", LABEL, "AiTimeout")

    assert not any(score.fields.values()) and score.terms == TermsCounts(0, 0, 6)
    assert score.failed == "AiTimeout"


def test_summary_reports_per_field_accuracy_and_exact_terms_rate() -> None:
    good = score_case("a", LABEL, extraction(), decimals=6)
    bad = score_case("b", LABEL, extraction(currency=located("EUR"), terms=None), decimals=6)
    summary = summarize([good, bad, score_failure("c", LABEL, "AiTimeout")])

    assert summary.cases == 3 and summary.failed == 1
    assert summary.accuracy["currency"] == pytest.approx(1 / 3)
    assert summary.accuracy["vendor_name"] == pytest.approx(2 / 3)
    assert summary.terms_exact == pytest.approx(1 / 3)
