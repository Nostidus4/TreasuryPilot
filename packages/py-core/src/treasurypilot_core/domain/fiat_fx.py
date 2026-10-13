"""Immutable inputs for fiat invoice conversion; amounts use minor/base units."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from treasurypilot_core.domain.models import FrozenModel, NonNegativeInt, PositiveInt
from treasurypilot_core.money import BaseUnits


class FxRate(FrozenModel):
    """Exact ratio: stablecoin base units per fiat minor unit."""

    fiat_currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    # Peg guard in the engine assumes a USD-pegged asset (spec: USDC only).
    stablecoin_asset: Annotated[str, Field(min_length=1)]
    stablecoin_units: PositiveInt
    fiat_minor_units: PositiveInt


class FiatApproval(FrozenModel):
    """Fiat value and token ceiling bound by one human approval."""

    fiat_amount: BaseUnits
    reference_rate: FxRate
    max_stablecoin_amount: BaseUnits
    fx_tolerance_bps: Annotated[int, Field(ge=0, le=10_000)]

    @model_validator(mode="after")
    def validate_amounts(self) -> FiatApproval:
        if self.fiat_amount == 0 or self.max_stablecoin_amount == 0:
            raise ValueError("fiat amount and approved stablecoin maximum must be positive")
        return self


class FxQuote(FrozenModel):
    """Observed execution rate and USD price of one whole stablecoin."""

    source_id: Annotated[str, Field(min_length=1)]
    rate: FxRate
    observed_at: NonNegativeInt
    stablecoin_usd_price_micros: PositiveInt


class FxPolicy(FrozenModel):
    """Owner-configured source, freshness window and USD peg tolerance."""

    source_id: Annotated[str, Field(min_length=1)]
    max_quote_age_seconds: NonNegativeInt
    depeg_threshold_bps: Annotated[int, Field(ge=0, le=10_000)]
