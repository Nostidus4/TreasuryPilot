"""Pure fiat-to-stablecoin conversion and pre-PAY safety checks."""

from __future__ import annotations

from typing import Literal

from treasurypilot_core.domain.fiat_fx import FiatApproval, FxPolicy, FxQuote
from treasurypilot_core.money import BaseUnits

_BPS = 10_000
_USD_MICROS = 1_000_000
type FxBlockReason = Literal[
    "SOURCE_MISMATCH",
    "PAIR_MISMATCH",
    "STALE_FX_QUOTE",
    "FX_OUTSIDE_TOLERANCE",
    "STABLECOIN_DEPEG",
    "APPROVED_MAX_EXCEEDED",
]


class FiatPaymentBlocked(ValueError):
    """No amount may be proposed; the invoice needs review or a fresh quote."""

    def __init__(self, reason: FxBlockReason) -> None:
        self.reason = reason
        super().__init__(reason)


def propose_fiat_payment(
    approval: FiatApproval,
    quote: FxQuote,
    policy: FxPolicy,
    *,
    now_timestamp: int,
) -> BaseUnits:
    """Return a safe token amount, or block without returning a partial amount.

    Conversion rounds *up* to the smallest token unit so an invoice is not
    underpaid. A rounded result beyond the approved ceiling is blocked, never
    silently clamped to that ceiling. Call again with a fresh quote immediately
    before PAY; the caller must also bind the returned amount to its approval.
    """

    if isinstance(now_timestamp, bool) or not isinstance(now_timestamp, int):
        raise TypeError("now_timestamp must be an integer")
    if now_timestamp < 0:
        raise ValueError("now_timestamp cannot be negative")

    # Revalidate even model_construct/model_copy inputs at the engine boundary.
    approval = FiatApproval.model_validate(approval.model_dump(mode="python"))
    quote = FxQuote.model_validate(quote.model_dump(mode="python"))
    policy = FxPolicy.model_validate(policy.model_dump(mode="python"))

    if quote.source_id != policy.source_id:
        raise FiatPaymentBlocked("SOURCE_MISMATCH")
    reference = approval.reference_rate
    current = quote.rate
    if (
        current.fiat_currency != reference.fiat_currency
        or current.stablecoin_asset != reference.stablecoin_asset
    ):
        raise FiatPaymentBlocked("PAIR_MISMATCH")
    if quote.observed_at > now_timestamp or (
        now_timestamp - quote.observed_at > policy.max_quote_age_seconds
    ):
        raise FiatPaymentBlocked("STALE_FX_QUOTE")

    # Cross multiplication compares rational rates exactly, including different
    # quote denominators. Equality at the tolerance boundary is accepted.
    current_scaled = current.stablecoin_units * reference.fiat_minor_units
    reference_scaled = reference.stablecoin_units * current.fiat_minor_units
    if abs(current_scaled - reference_scaled) * _BPS > (
        reference_scaled * approval.fx_tolerance_bps
    ):
        raise FiatPaymentBlocked("FX_OUTSIDE_TOLERANCE")

    # Price is USD micros per whole token; 1,000,000 represents a $1 peg.
    if abs(quote.stablecoin_usd_price_micros - _USD_MICROS) * _BPS > (
        _USD_MICROS * policy.depeg_threshold_bps
    ):
        raise FiatPaymentBlocked("STABLECOIN_DEPEG")

    numerator = int(approval.fiat_amount) * current.stablecoin_units
    amount = BaseUnits((numerator + current.fiat_minor_units - 1) // current.fiat_minor_units)
    if amount > approval.max_stablecoin_amount:
        raise FiatPaymentBlocked("APPROVED_MAX_EXCEEDED")
    return amount
