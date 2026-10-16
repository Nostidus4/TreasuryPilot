"""FX provider boundary for fiat invoice requests.

Provider implementations are responsible only for fetching an observed quote.
The py-core engine validates the quote and calculates the payment using integer
base units; this module never rounds or clips a payment itself.
"""

from __future__ import annotations

import time
from typing import Protocol

from treasurypilot_core.domain import FiatApproval, FxPolicy, FxQuote, FxRate
from treasurypilot_core.engine import propose_fiat_payment
from treasurypilot_core.money import BaseUnits


class FxQuoteProvider(Protocol):
    async def quote(
        self,
        *,
        fiat_currency: str,
        fiat_amount_minor_units: int,
        stablecoin_asset: str,
    ) -> FxQuote: ...


class FxProviderUnavailable(Exception):
    """Provider adapters raise this for timeouts or unavailable quote sources."""


class FiatInvoiceLike(Protocol):
    amount: int
    fiat_amount_minor_units: int | None
    fiat_currency: str | None
    fx_reference_quote: dict[str, object] | None
    fx_tolerance_bps: int | None


class StaticTestFxQuoteProvider:
    """TEST ONLY: values a USD-pegged 6-decimal stablecoin 1:1 against USD, never a market rate.

    Lets the local stack attach a fiat valuation (needed by the Travel Rule gate) without an
    external feed. create_app enables it only from TP_FX_TEST_STATIC_PROVIDER in local/test.
    """

    def __init__(self, source_id: str, *, decimals: int = 6) -> None:
        self._source_id = source_id
        self._decimals = decimals

    async def quote(
        self,
        *,
        fiat_currency: str,
        fiat_amount_minor_units: int,
        stablecoin_asset: str,
    ) -> FxQuote:
        if fiat_currency != "USD":
            raise FxProviderUnavailable("the TEST static FX provider only quotes USD")
        return FxQuote(
            source_id=self._source_id,
            rate=FxRate(
                fiat_currency=fiat_currency,
                stablecoin_asset=stablecoin_asset,
                stablecoin_units=10 ** (self._decimals - 2),  # one cent in base units
                fiat_minor_units=1,
            ),
            observed_at=int(time.time()),
            stablecoin_usd_price_micros=1_000_000,
        )


def asset_key(address: bytes) -> str:
    """Canonical adapter key for the treasury's ERC-20 stablecoin."""
    if len(address) != 20:
        raise ValueError("stablecoin asset address must be 20 bytes")
    return "0x" + address.hex()


def fiat_approval(
    *,
    fiat_amount_minor_units: int,
    max_stablecoin_amount: int,
    reference_quote: FxQuote,
    tolerance_bps: int,
) -> FiatApproval:
    return FiatApproval(
        fiat_amount=BaseUnits(fiat_amount_minor_units),
        reference_rate=reference_quote.rate,
        max_stablecoin_amount=BaseUnits(max_stablecoin_amount),
        fx_tolerance_bps=tolerance_bps,
    )


async def capture_reference_quote(
    provider: FxQuoteProvider,
    *,
    fiat_currency: str,
    fiat_amount_minor_units: int,
    stablecoin_asset: str,
    max_stablecoin_amount: int,
    tolerance_bps: int,
    policy: FxPolicy,
    now_timestamp: int,
) -> FxQuote:
    """Capture an approved reference rate and fail if it cannot fit the signed cap."""
    quote = await provider.quote(
        fiat_currency=fiat_currency,
        fiat_amount_minor_units=fiat_amount_minor_units,
        stablecoin_asset=stablecoin_asset,
    )
    if not isinstance(quote, FxQuote):
        raise TypeError("FX provider must return FxQuote")
    approval = fiat_approval(
        fiat_amount_minor_units=fiat_amount_minor_units,
        max_stablecoin_amount=max_stablecoin_amount,
        reference_quote=quote,
        tolerance_bps=tolerance_bps,
    )
    # This also checks source, pair, quote age, peg, and whether rounded units exceed max.
    propose_fiat_payment(approval, quote, policy, now_timestamp=now_timestamp)
    return quote


async def propose_request_payment(
    row: FiatInvoiceLike,
    provider: FxQuoteProvider,
    *,
    policy: FxPolicy,
    now_timestamp: int,
) -> BaseUnits:
    """Get a fresh quote and propose a payment no larger than the signed request cap.

    Non-fiat requests continue to pay their exact approved amount. Fiat requests
    require the captured quote and tolerance in the request revision.
    """
    amount = int(row.amount)
    fiat_amount = row.fiat_amount_minor_units
    currency = row.fiat_currency
    reference_data = row.fx_reference_quote
    tolerance_bps = row.fx_tolerance_bps
    if (fiat_amount, currency, reference_data, tolerance_bps) == (None, None, None, None):
        return BaseUnits(amount)
    if fiat_amount is None or currency is None or reference_data is None or tolerance_bps is None:
        raise ValueError("fiat request is missing its captured FX approval data")

    reference_quote = FxQuote.model_validate(reference_data)
    quote = await provider.quote(
        fiat_currency=currency,
        fiat_amount_minor_units=int(fiat_amount),
        stablecoin_asset=reference_quote.rate.stablecoin_asset,
    )
    approval = fiat_approval(
        fiat_amount_minor_units=int(fiat_amount),
        max_stablecoin_amount=amount,
        reference_quote=reference_quote,
        tolerance_bps=int(tolerance_bps),
    )
    return propose_fiat_payment(approval, quote, policy, now_timestamp=now_timestamp)
