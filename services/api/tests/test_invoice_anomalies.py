import asyncio
import uuid
from datetime import date, timedelta

from hypothesis import given
from hypothesis import strategies as st

from treasurypilot_api.invoices.anomalies import (
    InvoiceRevisionSignals,
    PaidInvoice,
    evaluate_anomalies,
)
from treasurypilot_api.invoices.models import PaymentRequest, RequestFlag, RequestStatus
from treasurypilot_api.invoices.requests import _recompute_flags

TODAY = date(2026, 10, 14)
PAYEE_ID = uuid.UUID("00000000-0000-7000-8000-000000000001")
ADDRESS = bytes.fromhex("11" * 20)


def revision(
    *,
    amount: int = 1000,
    due_date: date = date(2026, 11, 1),
    payee_address: bytes = ADDRESS,
    document_address: bytes | None = None,
    document_currency: str | None = None,
    document_chain: str | None = None,
    ai_available: bool | None = True,
) -> InvoiceRevisionSignals:
    return InvoiceRevisionSignals(
        issue_date=date(2026, 10, 1),
        due_date=due_date,
        amount=amount,
        payee_id=PAYEE_ID,
        payee_address=payee_address,
        asset_symbol="USDC",
        chain_name="Sepolia",
        document_address=document_address,
        document_currency=document_currency,
        document_chain=document_chain,
        ai_available=ai_available,
    )


def paid_history(
    amounts: tuple[int, ...] = (1000, 1020, 980, 1010, 990),
) -> tuple[PaidInvoice, ...]:
    return tuple(
        PaidInvoice(amount, TODAY - timedelta(days=30 * (index + 1)), PAYEE_ID, ADDRESS)
        for index, amount in enumerate(amounts)
    )


def codes(flags) -> set[str]:
    return {flag.code for flag in flags}


def test_amount_outlier_uses_documented_integer_median_mad_example() -> None:
    history = paid_history()
    assert "AMOUNT_OUTLIER" in codes(
        evaluate_anomalies(
            revision(amount=1100),
            history,
            registered_addresses=(ADDRESS,),
            prior_paid_to_payee=True,
            previous_paid=history[0],
            today=TODAY,
        )
    )
    assert "AMOUNT_OUTLIER" not in codes(
        evaluate_anomalies(
            revision(amount=1050),
            history,
            registered_addresses=(ADDRESS,),
            prior_paid_to_payee=True,
            previous_paid=history[0],
            today=TODAY,
        )
    )


def test_identical_recurring_amounts_have_two_percent_floor() -> None:
    flags = evaluate_anomalies(
        revision(amount=1001),
        paid_history((1000, 1000, 1000, 1000, 1000)),
        registered_addresses=(ADDRESS,),
        prior_paid_to_payee=True,
        previous_paid=paid_history()[0],
        today=TODAY,
    )
    assert "AMOUNT_OUTLIER" not in codes(flags)


def test_new_payee_has_first_payment_and_no_baseline_flags() -> None:
    flags = evaluate_anomalies(
        revision(),
        (),
        registered_addresses=(ADDRESS,),
        prior_paid_to_payee=False,
        previous_paid=None,
        today=TODAY,
    )
    assert {"FIRST_PAYMENT_TO_PAYEE", "NO_BASELINE"} <= codes(flags)
    assert {flag.severity for flag in flags} == {"LOW"}


def test_address_change_and_unregistered_document_address_are_high() -> None:
    previous = PaidInvoice(1000, TODAY - timedelta(days=1), PAYEE_ID, bytes.fromhex("22" * 20))
    flags = evaluate_anomalies(
        revision(payee_address=ADDRESS, document_address=bytes.fromhex("33" * 20)),
        paid_history(),
        registered_addresses=(ADDRESS,),
        prior_paid_to_payee=True,
        previous_paid=previous,
        today=TODAY,
    )
    selected = {flag.code: flag for flag in flags}
    assert selected["ADDRESS_CHANGED"].severity == "HIGH"
    assert selected["ADDRESS_NOT_REGISTERED"].severity == "HIGH"
    assert selected["ADDRESS_CHANGED"].evidence["previousAddress"] == "0x" + "22" * 20


def test_currency_chain_ai_and_due_date_rules_emit_expected_severity() -> None:
    flags = evaluate_anomalies(
        revision(
            due_date=date(2026, 9, 1),
            document_currency="USD",
            document_chain="Polygon",
            ai_available=False,
        ),
        (),
        registered_addresses=(ADDRESS,),
        prior_paid_to_payee=False,
        previous_paid=None,
        today=TODAY,
    )
    by_code = {flag.code: flag for flag in flags}
    assert {
        "DUE_DATE_PAST",
        "DUE_BEFORE_ISSUE",
        "CURRENCY_MISMATCH",
        "CHAIN_MISMATCH",
        "AI_UNAVAILABLE",
    } <= set(by_code)
    assert by_code["DUE_BEFORE_ISSUE"].severity == "HIGH"
    assert by_code["DUE_DATE_PAST"].severity == "LOW"
    assert by_code["AI_UNAVAILABLE"].severity == "LOW"


def test_anomaly_evaluation_is_a_pure_function_of_revision_and_history() -> None:
    inputs = (
        revision(amount=1100),
        paid_history(),
    )
    kwargs = {
        "registered_addresses": (ADDRESS,),
        "prior_paid_to_payee": True,
        "previous_paid": inputs[1][0],
        "today": TODAY,
    }
    first = evaluate_anomalies(*inputs, **kwargs)
    second = evaluate_anomalies(*inputs, **kwargs)
    assert first == second


def test_far_due_date_is_low_severity() -> None:
    flags = evaluate_anomalies(
        revision(due_date=date(2027, 2, 1)),
        paid_history(),
        registered_addresses=(ADDRESS,),
        prior_paid_to_payee=True,
        previous_paid=paid_history()[0],
        today=TODAY,
    )
    far_date = next(flag for flag in flags if flag.code == "DUE_DATE_FAR")
    assert far_date.severity == "LOW"
    assert far_date.evidence["thresholdDays"] == 120


def test_old_vendor_history_does_not_count_toward_amount_baseline() -> None:
    old_history = tuple(
        PaidInvoice(1000, TODAY - timedelta(days=400 + index), PAYEE_ID, ADDRESS)
        for index in range(5)
    )
    flags = evaluate_anomalies(
        revision(),
        old_history,
        registered_addresses=(ADDRESS,),
        prior_paid_to_payee=True,
        previous_paid=old_history[0],
        today=TODAY,
    )
    assert "NO_BASELINE" in codes(flags)


@given(st.lists(st.integers(min_value=1, max_value=10_000), min_size=5, max_size=12))
def test_amount_rules_are_independent_of_history_order(amounts: list[int]) -> None:
    history = tuple(
        PaidInvoice(amount, TODAY - timedelta(days=index), PAYEE_ID, ADDRESS)
        for index, amount in enumerate(amounts)
    )
    kwargs = {
        "registered_addresses": (ADDRESS,),
        "prior_paid_to_payee": True,
        "previous_paid": history[0],
        "today": TODAY,
    }
    assert evaluate_anomalies(revision(), history, **kwargs) == evaluate_anomalies(
        revision(), tuple(reversed(history)), **kwargs
    )


class _Result:
    def __init__(self, rows=(), first_row=None) -> None:
        self.rows = rows
        self.first_row = first_row

    def __iter__(self):
        return iter(self.rows)

    def first(self):
        return self.first_row


class _FlagSession:
    def __init__(self) -> None:
        self.execute_results = [_Result(), _Result(first_row=None), _Result()]
        self.scalar_results = [None, ADDRESS, "USDC", "Sepolia"]
        self.added: list[RequestFlag] = []

    async def execute(self, statement):
        return self.execute_results.pop(0)

    async def scalar(self, statement):
        return self.scalar_results.pop(0)

    async def scalars(self, statement):
        return _Result((ADDRESS,))

    def add(self, flag: RequestFlag) -> None:
        self.added.append(flag)


def test_persisted_flags_are_revision_scoped_and_do_not_change_request() -> None:
    row = PaymentRequest(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        treasury_id=uuid.uuid4(),
        chain_id=11155111,
        vendor_id=uuid.uuid4(),
        payee_id=PAYEE_ID,
        invoice_no="INV-001",
        issue_date=date(2026, 10, 1),
        due_at=date(2026, 11, 1),
        amount=1000,
        asset_id=uuid.uuid4(),
        fingerprint=b"x" * 32,
        status=RequestStatus.DRAFT.value,
        current_revision=3,
    )
    initial_fields = (row.status, row.amount, row.invoice_no, row.due_at)
    session = _FlagSession()

    flags = asyncio.run(_recompute_flags(session, row))

    assert {flag["code"] for flag in flags} == {"FIRST_PAYMENT_TO_PAYEE", "NO_BASELINE"}
    assert all(flag.revision == 3 for flag in session.added)
    assert all(flag.source == "DETERMINISTIC" for flag in session.added)
    assert (row.status, row.amount, row.invoice_no, row.due_at) == initial_fields


def test_even_sized_history_uses_lower_middle_median() -> None:
    flags = evaluate_anomalies(
        revision(amount=1100),
        paid_history((1000, 1010, 1020, 1030, 1040, 1050)),
        registered_addresses=(ADDRESS,),
        prior_paid_to_payee=True,
        previous_paid=None,
        today=TODAY,
    )
    outlier = {flag.code: flag for flag in flags}["AMOUNT_OUTLIER"]
    assert outlier.evidence["median"] == 1020
    assert outlier.evidence["mad"] == 10
