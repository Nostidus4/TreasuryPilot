from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from treasurypilot_api.invoices.fx import propose_request_payment
from treasurypilot_core.domain import FiatApproval, FxPolicy, FxQuote, FxRate
from treasurypilot_core.engine import FiatPaymentBlocked
from treasurypilot_core.money import BaseUnits


def _quote(units: int, observed_at: int = 100) -> FxQuote:
    return FxQuote(
        source_id="approved-feed",
        rate=FxRate(
            fiat_currency="EUR",
            stablecoin_asset="0x" + "11" * 20,
            stablecoin_units=units,
            fiat_minor_units=100,
        ),
        observed_at=observed_at,
        stablecoin_usd_price_micros=1_000_000,
    )


class _Provider:
    def __init__(self, quote: FxQuote) -> None:
        self.quote_value = quote

    async def quote(self, **_: object) -> FxQuote:
        return self.quote_value


@dataclass
class _FiatRequest:
    amount: int = 120
    fiat_amount_minor_units: int | None = 100
    fiat_currency: str | None = "EUR"
    fx_reference_quote: dict[str, object] | None = None
    fx_tolerance_bps: int | None = 500

    def __post_init__(self) -> None:
        if self.fx_reference_quote is None:
            self.fx_reference_quote = _quote(100).model_dump(mode="json")


POLICY = FxPolicy(source_id="approved-feed", max_quote_age_seconds=60, depeg_threshold_bps=100)


def test_payment_proposal_is_recomputed_from_fresh_quote_and_within_approved_cap() -> None:
    amount = asyncio.run(
        propose_request_payment(
            _FiatRequest(), _Provider(_quote(101)), policy=POLICY, now_timestamp=110
        )
    )
    assert amount == BaseUnits(101)
    assert amount <= 120


def test_payment_proposal_blocks_quote_that_would_exceed_approved_cap() -> None:
    request = _FiatRequest(amount=100)
    # 100 minor units at 101 / 100 units per minor unit rounds to 101.
    with pytest.raises(FiatPaymentBlocked, match="APPROVED_MAX_EXCEEDED"):
        asyncio.run(
            propose_request_payment(
                request, _Provider(_quote(101)), policy=POLICY, now_timestamp=110
            )
        )


def test_payment_proposal_blocks_stale_quote_instead_of_returning_old_amount() -> None:
    with pytest.raises(FiatPaymentBlocked, match="STALE_FX_QUOTE"):
        asyncio.run(
            propose_request_payment(
                _FiatRequest(),
                _Provider(_quote(100, observed_at=1)),
                policy=POLICY,
                now_timestamp=110,
            )
        )


def test_approval_model_records_fiat_and_maximum_in_one_bound_object() -> None:
    reference = _quote(100).rate
    approval = FiatApproval(
        fiat_amount=BaseUnits(100),
        reference_rate=reference,
        max_stablecoin_amount=BaseUnits(120),
        fx_tolerance_bps=500,
    )
    assert approval.fiat_amount == 100
    assert approval.max_stablecoin_amount == 120
