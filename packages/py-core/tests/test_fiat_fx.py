from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from treasurypilot_core.domain import FiatApproval, FxPolicy, FxQuote, FxRate
from treasurypilot_core.engine import FiatPaymentBlocked, propose_fiat_payment
from treasurypilot_core.money import BaseUnits


def rate(
    stablecoin_units: int = 11_000,
    fiat_minor_units: int = 1,
    *,
    fiat_currency: str = "EUR",
    stablecoin_asset: str = "USDC-sepolia",
) -> FxRate:
    return FxRate(
        fiat_currency=fiat_currency,
        stablecoin_asset=stablecoin_asset,
        stablecoin_units=stablecoin_units,
        fiat_minor_units=fiat_minor_units,
    )


def approval(
    *,
    fiat_amount: int = 100_000,
    max_stablecoin_amount: int = 1_200_000_000,
    fx_tolerance_bps: int = 100,
) -> FiatApproval:
    return FiatApproval(
        fiat_amount=BaseUnits(fiat_amount),
        reference_rate=rate(),
        max_stablecoin_amount=BaseUnits(max_stablecoin_amount),
        fx_tolerance_bps=fx_tolerance_bps,
    )


def quote(
    *,
    execution_rate: FxRate | None = None,
    price_micros: int = 1_000_000,
    observed_at: int = 1_000,
    source_id: str = "owner-fx-source",
) -> FxQuote:
    return FxQuote(
        source_id=source_id,
        rate=execution_rate or rate(),
        observed_at=observed_at,
        stablecoin_usd_price_micros=price_micros,
    )


def policy(*, max_quote_age_seconds: int = 60, depeg_threshold_bps: int = 100) -> FxPolicy:
    return FxPolicy(
        source_id="owner-fx-source",
        max_quote_age_seconds=max_quote_age_seconds,
        depeg_threshold_bps=depeg_threshold_bps,
    )


def assert_blocked(reason: str, a: FiatApproval, q: FxQuote, p: FxPolicy) -> None:
    with pytest.raises(FiatPaymentBlocked) as error:
        propose_fiat_payment(a, q, p, now_timestamp=1_060)
    assert error.value.reason == reason


def test_eur_invoice_converts_to_exact_token_units_and_serializes_as_strings() -> None:
    a = approval()
    assert propose_fiat_payment(a, quote(), policy(), now_timestamp=1_060) == BaseUnits(
        1_100_000_000
    )
    payload = json.loads(a.model_dump_json())
    assert payload["fiat_amount"] == "100000"
    assert payload["max_stablecoin_amount"] == "1200000000"


def test_rate_and_depeg_boundaries_are_inclusive() -> None:
    # Exactly +1% rate and exactly -1% peg are allowed.
    q = quote(execution_rate=rate(11_110), price_micros=990_000)
    assert propose_fiat_payment(approval(), q, policy(), now_timestamp=1_060) == BaseUnits(
        1_111_000_000
    )
    assert_blocked(
        "FX_OUTSIDE_TOLERANCE",
        approval(),
        quote(execution_rate=rate(11_111)),
        policy(),
    )
    assert_blocked("STABLECOIN_DEPEG", approval(), quote(price_micros=989_999), policy())
    assert_blocked("STABLECOIN_DEPEG", approval(), quote(price_micros=1_010_001), policy())


def test_rational_rate_comparison_and_conversion_round_up_without_clipping() -> None:
    # Same economic rate expressed with a different denominator.
    same_rate = rate(22_000, 2)
    assert propose_fiat_payment(
        approval(), quote(execution_rate=same_rate), policy(), now_timestamp=1_060
    ) == BaseUnits(1_100_000_000)

    a = approval(fiat_amount=1, max_stablecoin_amount=5_000)
    q = quote(execution_rate=rate(10_001, 2))
    # Large tolerance admits the quote, but rounding to 5,001 breaks the cap.
    a = a.model_copy(update={"fx_tolerance_bps": 10_000})
    assert_blocked("APPROVED_MAX_EXCEEDED", a, q, policy())
    assert propose_fiat_payment(
        a.model_copy(update={"max_stablecoin_amount": BaseUnits(5_001)}),
        q,
        policy(),
        now_timestamp=1_060,
    ) == BaseUnits(5_001)


def test_maximum_is_never_exceeded_across_many_valid_rates() -> None:
    a = approval(max_stablecoin_amount=1_105_000_000)
    for units in range(10_890, 11_111):
        q = quote(execution_rate=rate(units))
        try:
            amount = propose_fiat_payment(a, q, policy(), now_timestamp=1_060)
        except FiatPaymentBlocked as blocked:
            assert (
                blocked.reason == "APPROVED_MAX_EXCEEDED"
                or blocked.reason == "FX_OUTSIDE_TOLERANCE"
            )
        else:
            assert amount <= a.max_stablecoin_amount
            assert amount == a.fiat_amount * units


@pytest.mark.parametrize(
    ("changed_quote", "changed_policy", "reason"),
    [
        (quote(source_id="unknown"), policy(), "SOURCE_MISMATCH"),
        (quote(execution_rate=rate(fiat_currency="USD")), policy(), "PAIR_MISMATCH"),
        (quote(execution_rate=rate(stablecoin_asset="USDT")), policy(), "PAIR_MISMATCH"),
        (quote(observed_at=999), policy(), "STALE_FX_QUOTE"),
        (quote(observed_at=1_061), policy(), "STALE_FX_QUOTE"),
        (quote(price_micros=1_000_001), policy(depeg_threshold_bps=0), "STABLECOIN_DEPEG"),
    ],
)
def test_invalid_execution_quote_blocks(
    changed_quote: FxQuote, changed_policy: FxPolicy, reason: str
) -> None:
    assert_blocked(reason, approval(), changed_quote, changed_policy)


def test_invalid_inputs_are_rejected_at_schema_and_engine_boundaries() -> None:
    with pytest.raises(ValidationError):
        rate(0)
    with pytest.raises(ValidationError):
        approval(fiat_amount=0)
    with pytest.raises(ValidationError):
        approval(fx_tolerance_bps=10_001)
    with pytest.raises(ValidationError):
        quote(price_micros=0)
    with pytest.raises(ValidationError):
        policy(depeg_threshold_bps=10_001)

    forged = quote().model_copy(update={"stablecoin_usd_price_micros": -1})
    with pytest.raises(ValidationError):
        propose_fiat_payment(approval(), forged, policy(), now_timestamp=1_060)
    with pytest.raises(TypeError, match="now_timestamp"):
        propose_fiat_payment(approval(), quote(), policy(), now_timestamp=True)  # type: ignore[arg-type]


def test_policy_boundaries_at_zero_are_inclusive() -> None:
    now_quote = quote(observed_at=1_060)
    assert propose_fiat_payment(
        approval(), now_quote, policy(max_quote_age_seconds=0), now_timestamp=1_060
    ) == BaseUnits(1_100_000_000)
    assert propose_fiat_payment(
        approval(), quote(), policy(depeg_threshold_bps=0), now_timestamp=1_060
    ) == BaseUnits(1_100_000_000)


def test_wrong_argument_types_raise_type_error_not_a_review_block() -> None:
    a, q, p = approval(), quote(), policy()
    for args in (
        (a.model_dump(), q, p),
        (a, q.model_dump(), p),
        (a, q, p.model_dump()),
        (q, a, p),  # swapped models
    ):
        with pytest.raises(TypeError) as error:
            propose_fiat_payment(*args, now_timestamp=1_060)  # type: ignore[arg-type]
        assert not isinstance(error.value, FiatPaymentBlocked)
    assert not issubclass(FiatPaymentBlocked, ValueError)
