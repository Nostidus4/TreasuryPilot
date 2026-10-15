"""Scoring for the extraction accuracy eval (AGT-013): pure functions, no model calls.

Field accuracy is exact match against the invoice label after trimming whitespace. The
amount is compared in integer base units, parsed with `BaseUnits.parse` exactly as the
draft prefill does, so a locale format the pipeline cannot read counts as a miss. Terms are
scored as a set of (term, value) elements with micro-averaged precision, recall and F1;
day offsets are measured from the invoice issue date.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from treasurypilot_core.money import BaseUnits
from treasurypilot_worker.invoices.extraction import InvoiceExtraction, TermsExtraction

FIELDS = (
    "vendor_name",
    "invoice_no",
    "issue_date",
    "due_date",
    "amount",
    "currency",
    "payee_address",
)

Term = tuple[str, str | int]


def _text(located: Any) -> str | None:
    return None if located is None else str(located.value).strip()


def predicted_fields(extraction: InvoiceExtraction, *, decimals: int) -> dict[str, str | None]:
    """The extraction in label form; a value that cannot be read becomes None (a miss)."""

    amount: str | None = None
    if (text := _text(extraction.amount_text)) is not None:
        try:
            amount = str(int(BaseUnits.parse(text, decimals)))
        except ValueError:
            amount = None
    address = _text(extraction.payee_address_as_found)
    return {
        "vendor_name": _text(extraction.vendor_name),
        "invoice_no": _text(extraction.invoice_no),
        "issue_date": _text(extraction.issue_date),
        "due_date": _text(extraction.due_date),
        "amount": amount,
        "currency": _text(extraction.currency),
        "payee_address": None if address is None else address.lower(),
    }


def expected_fields(label: Mapping[str, Any]) -> dict[str, str | None]:
    return {
        "vendor_name": label["vendor_name"].strip(),
        "invoice_no": label["invoice_no"].strip(),
        "issue_date": label["issue_date"],
        "due_date": label["due_date"],
        "amount": str(int(label["amount"])),
        "currency": label["currency"],
        "payee_address": label["payee_address"].lower(),
    }


def field_matches(
    expected: Mapping[str, str | None], predicted: Mapping[str, str | None]
) -> dict[str, bool]:
    return {name: predicted.get(name) == expected[name] for name in FIELDS}


def expected_terms(label: Mapping[str, Any]) -> frozenset[Term]:
    """Label terms as day offsets from the issue date; no printed terms is the empty set."""

    terms = label.get("terms")
    if terms is None:
        return frozenset()
    issue = date.fromisoformat(label["issue_date"])
    result: set[Term] = {("net_days", (date.fromisoformat(terms["net_due_date"]) - issue).days)}
    if terms.get("discount_bps") is not None:
        result.add(("discount_bps", terms["discount_bps"]))
        deadline = date.fromisoformat(terms["discount_deadline"])
        result.add(("discount_days", (deadline - issue).days))
    if (fee := terms.get("late_fee")) is not None:
        result.add(("late_fee.kind", fee["type"]))
        result.add(("late_fee.rate_bps", fee["rate_bps"]))
        result.add(("late_fee.period_days", fee["period_days"]))
    return frozenset(result)


def predicted_terms(terms: TermsExtraction | None) -> frozenset[Term]:
    """What the model reported. `uncertain` is not scored: it only withholds the prefill."""

    if terms is None:
        return frozenset()
    pairs: list[tuple[str, str | int | None]] = [
        ("net_days", terms.net_days),
        ("discount_bps", terms.discount_bps),
        ("discount_days", terms.discount_days),
    ]
    if (fee := terms.late_fee) is not None:
        pairs += [
            ("late_fee.kind", fee.kind),
            ("late_fee.rate_bps", fee.rate_bps),
            ("late_fee.period_days", fee.period_days),
        ]
    return frozenset((name, value) for name, value in pairs if value is not None)


@dataclass(frozen=True)
class TermsCounts:
    true_positive: int
    false_positive: int
    false_negative: int

    @property
    def exact(self) -> bool:
        return self.false_positive == 0 and self.false_negative == 0


def terms_counts(expected: frozenset[Term], predicted: frozenset[Term]) -> TermsCounts:
    hit = len(expected & predicted)
    return TermsCounts(hit, len(predicted) - hit, len(expected) - hit)


@dataclass(frozen=True)
class F1:
    precision: float
    recall: float
    f1: float


def f1_score(counts: Sequence[TermsCounts]) -> F1:
    """Micro-averaged. Nothing expected and nothing predicted anywhere scores 1.0."""

    tp = sum(c.true_positive for c in counts)
    fp = sum(c.false_positive for c in counts)
    fn = sum(c.false_negative for c in counts)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return F1(precision, recall, f1)


@dataclass(frozen=True)
class CaseScore:
    invoice_id: str
    fields: Mapping[str, bool]
    terms: TermsCounts
    failed: str | None = None  # AiError name when the pipeline produced no answer
    misses: Mapping[str, tuple[str | None, str | None]] = field(default_factory=dict)


def score_case(
    invoice_id: str, label: Mapping[str, Any], extraction: InvoiceExtraction, *, decimals: int
) -> CaseScore:
    expected, predicted = expected_fields(label), predicted_fields(extraction, decimals=decimals)
    matches = field_matches(expected, predicted)
    return CaseScore(
        invoice_id,
        matches,
        terms_counts(expected_terms(label), predicted_terms(extraction.terms)),
        misses={n: (expected[n], predicted[n]) for n, ok in matches.items() if not ok},
    )


def score_failure(invoice_id: str, label: Mapping[str, Any], error: str) -> CaseScore:
    """No answer: every field is a miss and every expected term is a false negative."""

    expected = expected_fields(label)
    return CaseScore(
        invoice_id,
        {name: False for name in FIELDS},
        terms_counts(expected_terms(label), frozenset()),
        failed=error,
        misses={name: (expected[name], None) for name in FIELDS},
    )


@dataclass(frozen=True)
class Summary:
    cases: int
    failed: int
    accuracy: Mapping[str, float]
    terms: F1
    terms_exact: float


def summarize(scores: Sequence[CaseScore]) -> Summary:
    n = len(scores)
    return Summary(
        cases=n,
        failed=sum(1 for s in scores if s.failed),
        accuracy={f: sum(s.fields[f] for s in scores) / n for f in FIELDS} if n else {},
        terms=f1_score([s.terms for s in scores]),
        terms_exact=sum(s.terms.exact for s in scores) / n if n else 0.0,
    )
