from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from treasurypilot_core.domain import ApprovedRequest, LateFee, PaymentTerms
from treasurypilot_core.engine import InvalidTerms, request_value, validate_terms
from treasurypilot_core.money import BaseUnits


def request(
    *,
    amount: int = 1_000,
    due_day: int = 30,
    discount_bps: int = 0,
    discount_day: int | None = None,
    late_fee: LateFee | None = None,
    early_amount: int | None = None,
    early_pay_by: int | None = None,
) -> ApprovedRequest:
    return ApprovedRequest(
        id="request-1",
        paying_wallet="0xoperational",
        payee="0xpayee",
        amount=BaseUnits(amount),
        approved_seq=1,
        terms=PaymentTerms(
            net_due_day=due_day,
            discount_bps=discount_bps,
            discount_deadline_day=discount_day,
            late_fee=late_fee,
        ),
        early_amount=BaseUnits(early_amount) if early_amount is not None else None,
        early_pay_by=early_pay_by,
    )


@pytest.mark.parametrize(
    ("payment_request", "pay_day", "expected"),
    [
        (request(discount_bps=200, discount_day=10), 8, 20),
        (request(discount_bps=200, discount_day=10), 12, 0),
        (
            request(late_fee=LateFee(kind="percent_per_period", rate_bps=150, period_days=7)),
            31,
            -15,
        ),
        (
            request(late_fee=LateFee(kind="percent_per_period", rate_bps=150, period_days=7)),
            45,
            -45,
        ),
        (
            request(late_fee=LateFee(kind="fixed", amount=BaseUnits(25), cap=BaseUnits(25))),
            60,
            -25,
        ),
    ],
)
def test_financial_engine_section_8_2_golden_rows(
    payment_request: ApprovedRequest,
    pay_day: int,
    expected: int,
) -> None:
    assert request_value(payment_request, pay_day) == expected


def test_exact_approved_saving_supersedes_bps_estimate() -> None:
    payment_request = request(
        amount=1_000,
        discount_bps=200,
        discount_day=10,
        early_amount=970,
        early_pay_by=10,
    )

    assert request_value(payment_request, 10) == 30
    assert request_value(payment_request, 11) == 0


def test_signed_approval_deadline_is_authoritative_for_exact_option() -> None:
    payment_request = request(
        amount=1_000,
        discount_bps=200,
        discount_day=10,
        early_amount=970,
        early_pay_by=9,
    )

    assert request_value(payment_request, 9) == 30
    assert request_value(payment_request, 10) == 0


def test_approval_option_serializes_money_as_decimal_text() -> None:
    payment_request = request(
        discount_bps=200,
        discount_day=10,
        early_amount=980,
        early_pay_by=10,
    )

    payload = json.loads(payment_request.model_dump_json())
    assert payload["amount"] == "1000"
    assert payload["early_amount"] == "980"
    assert payload["early_pay_by"] == 10


def test_early_value_deducts_fee_and_lost_supply_interest() -> None:
    payment_request = request(
        amount=4_000_000,
        due_day=30,
        discount_bps=500,
        discount_day=20,
        early_amount=3_650_000,
        early_pay_by=20,
    )

    # Lost interest = floor(3,650,000 * 1,000 bps * 10 days / (10,000 * 365)) = 10,000.
    assert (
        request_value(
            payment_request,
            20,
            fee_in_asset=BaseUnits(25_000),
            supply_rate_bps=1_000,
        )
        == 315_000
    )


def test_fee_and_interest_do_not_apply_after_early_option_expires() -> None:
    payment_request = request(
        amount=4_000_000,
        due_day=30,
        discount_bps=500,
        discount_day=20,
        early_amount=3_650_000,
        early_pay_by=20,
    )

    assert (
        request_value(
            payment_request,
            30,
            fee_in_asset=BaseUnits(25_000),
            supply_rate_bps=1_000,
        )
        == 0
    )


def test_zero_saving_approval_is_valid_but_not_preferred() -> None:
    payment_request = request(
        discount_bps=1,
        discount_day=10,
        early_amount=1_000,
        early_pay_by=10,
    )

    assert request_value(payment_request, 10, fee_in_asset=BaseUnits(1)) == -1


@pytest.mark.parametrize(
    ("pay_day", "expected_fee"),
    [(30, 0), (31, 15), (37, 15), (38, 30), (44, 30), (45, 45)],
)
def test_percent_fee_accrues_for_each_started_period(pay_day: int, expected_fee: int) -> None:
    payment_request = request(
        late_fee=LateFee(kind="percent_per_period", rate_bps=150, period_days=7)
    )

    assert request_value(payment_request, pay_day) == -expected_fee


def test_percent_fee_rounds_down_then_stops_at_total_cap() -> None:
    payment_request = request(
        amount=999,
        late_fee=LateFee(
            kind="percent_per_period",
            rate_bps=333,
            period_days=7,
            cap=BaseUnits(50),
        ),
    )

    assert request_value(payment_request, 31) == -33
    assert request_value(payment_request, 38) == -50
    assert request_value(payment_request, 300) == -50


def test_fixed_fee_is_charged_once_and_honours_cap() -> None:
    payment_request = request(
        late_fee=LateFee(kind="fixed", amount=BaseUnits(25), cap=BaseUnits(10))
    )

    assert request_value(payment_request, 30) == 0
    assert request_value(payment_request, 31) == -10
    assert request_value(payment_request, 300) == -10


def test_discount_and_percent_fee_calculations_remain_integral_for_large_amounts() -> None:
    large_amount = 10**60 + 123
    discounted = request(
        amount=large_amount,
        discount_bps=333,
        discount_day=10,
    )
    late = request(
        amount=large_amount,
        late_fee=LateFee(kind="percent_per_period", rate_bps=333, period_days=1),
    )

    assert request_value(discounted, 10) == large_amount * 333 // 10_000
    assert request_value(late, 31) == -(large_amount * 333 // 10_000)


@pytest.mark.parametrize(
    "terms",
    [
        PaymentTerms.model_construct(net_due_day=-1, discount_bps=0),
        PaymentTerms.model_construct(
            net_due_day=30,
            discount_bps=200,
            discount_deadline_day=31,
            late_fee=None,
        ),
        PaymentTerms.model_construct(
            net_due_day=30,
            discount_bps=0,
            discount_deadline_day=None,
            late_fee=LateFee.model_construct(
                kind="percent_per_period",
                amount=None,
                rate_bps=10_001,
                period_days=7,
                cap=None,
            ),
        ),
    ],
)
def test_engine_boundary_raises_invalid_terms_for_unchecked_models(terms: PaymentTerms) -> None:
    with pytest.raises(InvalidTerms):
        validate_terms(terms)


def test_schema_boundary_rejects_incomplete_or_inconsistent_approval_options() -> None:
    with pytest.raises(ValidationError, match="defined together"):
        request(
            discount_bps=200,
            discount_day=10,
            early_amount=980,
        )

    with pytest.raises(ValidationError, match="cannot exceed"):
        request(
            discount_bps=200,
            discount_day=10,
            early_amount=1_001,
            early_pay_by=10,
        )

    with pytest.raises(ValidationError, match="must be positive"):
        request(
            discount_bps=200,
            discount_day=10,
            early_amount=0,
            early_pay_by=10,
        )

    with pytest.raises(ValidationError, match="after the net due day"):
        request(
            discount_bps=200,
            discount_day=10,
            early_amount=980,
            early_pay_by=31,
        )

    with pytest.raises(ValidationError, match="less than or equal to 10000"):
        LateFee(kind="percent_per_period", rate_bps=10_001, period_days=7)


def test_engine_rejects_unchecked_zero_early_amount_instead_of_creating_saving() -> None:
    valid_request = request(discount_bps=200, discount_day=10)
    unchecked = valid_request.model_copy(update={"early_amount": BaseUnits(0), "early_pay_by": 10})

    with pytest.raises(InvalidTerms, match="must be positive"):
        request_value(unchecked, 10)


def test_request_value_rejects_non_integer_days_and_non_base_unit_fees() -> None:
    payment_request = request()

    with pytest.raises(TypeError, match="pay_day"):
        request_value(payment_request, True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="fee_in_asset"):
        request_value(payment_request, 30, fee_in_asset=1)  # type: ignore[arg-type]
    with pytest.raises(InvalidTerms, match="supply_rate_bps"):
        request_value(payment_request, 30, supply_rate_bps=-1)
