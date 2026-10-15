"""Deterministic fee policy math shared by planning, API, and execution services."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

WEI_PER_ETH = 10**18
BASIS_POINTS = 10_000
DEFAULT_PLAN_GAS = 21_000
POLICY_HISTORY_DAYS = 7


class FeePreset(StrEnum):
    ECONOMY = "ECONOMY"
    NORMAL = "NORMAL"
    FAST = "FAST"


class FeeDecision(StrEnum):
    PROCEED = "PROCEED"
    DEFER = "DEFER"
    AWAITING_FEE_ACCEPTANCE = "AWAITING_FEE_ACCEPTANCE"


@dataclass(frozen=True, slots=True)
class FeePresetConfig:
    max_fee_multiplier_bps: int
    tip_percentile: int
    resend_after_s: int
    bump_bps: int = 1_250


PRESETS: dict[FeePreset, FeePresetConfig] = {
    FeePreset.ECONOMY: FeePresetConfig(15_000, 25, 90),
    FeePreset.NORMAL: FeePresetConfig(20_000, 50, 60),
    FeePreset.FAST: FeePresetConfig(30_000, 75, 30),
}


@dataclass(frozen=True, slots=True)
class FeeProposal:
    preset: FeePreset
    max_fee_multiplier_bps: int
    tip_percentile: int
    resend_after_s: int
    bump_bps: int
    avg_plan_fee_7d_wei: int
    p90_plan_fee_7d_wei: int
    plans_per_day_7d: float
    per_plan_threshold_wei: int
    daily_budget_wei: int
    max_fee_per_gas_wei: int


@dataclass(frozen=True, slots=True)
class FeeAssessment:
    decision: FeeDecision
    reason_code: str | None
    estimated_fee_wei: int
    spent_today_wei: int
    daily_budget_wei: int


def percentile_nearest_rank(values: Sequence[int], percentile: int) -> int:
    """Return a deterministic nearest-rank percentile for nonnegative wei values."""

    if not values:
        raise ValueError("at least one value is required")
    if not 0 <= percentile <= 100:
        raise ValueError("percentile must be between 0 and 100")
    if any(value < 0 for value in values):
        raise ValueError("fee values must be nonnegative")
    ordered = sorted(values)
    rank = max(1, (len(ordered) * percentile + 99) // 100)
    return ordered[rank - 1]


def propose_fee_policy(
    *,
    plan_fees_wei: Sequence[int],
    plans_last_7d: int,
    base_fee_per_gas_wei: int,
    priority_fees_wei: Sequence[int],
    preset: FeePreset = FeePreset.NORMAL,
) -> FeeProposal:
    """Build a proposal from observed plan fees and the latest eth_feeHistory data.

    With no plan history, a plain-transfer gas baseline is used. This intentionally
    produces a conservative proposal: the plan's actual estimate is checked separately.
    """

    if base_fee_per_gas_wei < 0 or plans_last_7d < 0:
        raise ValueError("base fee and plan count must be nonnegative")
    if any(value < 0 for value in priority_fees_wei):
        raise ValueError("priority fees must be nonnegative")
    if plan_fees_wei and any(value < 0 for value in plan_fees_wei):
        raise ValueError("plan fees must be nonnegative")
    config = PRESETS[preset]
    if priority_fees_wei:
        tip = percentile_nearest_rank(priority_fees_wei, config.tip_percentile)
    else:
        tip = 0
    max_fee_per_gas = base_fee_per_gas_wei * config.max_fee_multiplier_bps // BASIS_POINTS + tip

    if plan_fees_wei:
        avg_fee = sum(plan_fees_wei) // len(plan_fees_wei)
        p90_fee = percentile_nearest_rank(plan_fees_wei, 90)
        observed_plans = plans_last_7d or len(plan_fees_wei)
        plans_per_day = observed_plans / POLICY_HISTORY_DAYS
        # Integer ceil of the 7-day average so a fractional plan/day is not rounded down.
        daily_by_volume = (3 * observed_plans * avg_fee + POLICY_HISTORY_DAYS - 1) // (
            POLICY_HISTORY_DAYS
        )
    else:
        avg_fee = DEFAULT_PLAN_GAS * max_fee_per_gas
        p90_fee = avg_fee
        plans_per_day = 1.0
        daily_by_volume = 3 * avg_fee

    threshold = max(3 * avg_fee, p90_fee)
    daily_budget = max(daily_by_volume, 2 * threshold)
    return FeeProposal(
        preset=preset,
        max_fee_multiplier_bps=config.max_fee_multiplier_bps,
        tip_percentile=config.tip_percentile,
        resend_after_s=config.resend_after_s,
        bump_bps=config.bump_bps,
        avg_plan_fee_7d_wei=avg_fee,
        p90_plan_fee_7d_wei=p90_fee,
        plans_per_day_7d=plans_per_day,
        per_plan_threshold_wei=threshold,
        daily_budget_wei=daily_budget,
        max_fee_per_gas_wei=max_fee_per_gas,
    )


def estimate_plan_fee_wei(gas_estimates: Sequence[int], max_fees_per_gas_wei: Sequence[int]) -> int:
    """Sum each step's gas estimate times its max fee, using integer wei throughout."""

    if len(gas_estimates) != len(max_fees_per_gas_wei) or not gas_estimates:
        raise ValueError("every plan step needs one gas estimate and max fee")
    if any(value < 0 for value in (*gas_estimates, *max_fees_per_gas_wei)):
        raise ValueError("gas estimates and max fees must be nonnegative")
    return sum(
        gas * max_fee for gas, max_fee in zip(gas_estimates, max_fees_per_gas_wei, strict=True)
    )


def assess_fee(
    *,
    estimated_fee_wei: int,
    per_plan_threshold_wei: int,
    spent_today_wei: int,
    daily_budget_wei: int,
    last_safe_execution_at: datetime,
    now: datetime | None = None,
) -> FeeAssessment:
    """Apply §8.7: proceed within both limits, defer while time remains, else ask."""

    values = (
        estimated_fee_wei,
        per_plan_threshold_wei,
        spent_today_wei,
        daily_budget_wei,
    )
    if any(value < 0 for value in values):
        raise ValueError("fee values must be nonnegative")
    current = now or datetime.now(UTC)
    current = current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)
    safe_at = (
        last_safe_execution_at.replace(tzinfo=UTC)
        if last_safe_execution_at.tzinfo is None
        else last_safe_execution_at.astimezone(UTC)
    )
    if (
        estimated_fee_wei <= per_plan_threshold_wei
        and spent_today_wei + estimated_fee_wei <= daily_budget_wei
    ):
        return FeeAssessment(
            FeeDecision.PROCEED, None, estimated_fee_wei, spent_today_wei, daily_budget_wei
        )
    if current < safe_at:
        reason = (
            "FEE_ABOVE_THRESHOLD"
            if estimated_fee_wei > per_plan_threshold_wei
            else "FEE_BUDGET_EXHAUSTED"
        )
        return FeeAssessment(
            FeeDecision.DEFER, reason, estimated_fee_wei, spent_today_wei, daily_budget_wei
        )
    return FeeAssessment(
        FeeDecision.AWAITING_FEE_ACCEPTANCE,
        "FEE_ABOVE_THRESHOLD"
        if estimated_fee_wei > per_plan_threshold_wei
        else "FEE_BUDGET_EXHAUSTED",
        estimated_fee_wei,
        spent_today_wei,
        daily_budget_wei,
    )


def fee_in_asset_base_units(estimated_fee_wei: int, reference_eth_price: int) -> int:
    """Convert a fee with the labelled asset-units-per-ETH setting (rounding down)."""

    if estimated_fee_wei < 0 or reference_eth_price <= 0:
        raise ValueError("fee must be nonnegative and reference ETH price must be positive")
    return estimated_fee_wei * reference_eth_price // WEI_PER_ETH


def discount_justifies_early_payment(
    *, discount_asset_base_units: int, estimated_fee_wei: int, reference_eth_price: int
) -> bool:
    """FEE-2: schedule early for a discount only when net savings are strictly positive."""

    if discount_asset_base_units < 0:
        raise ValueError("discount must be nonnegative")
    return discount_asset_base_units > fee_in_asset_base_units(
        estimated_fee_wei, reference_eth_price
    )


def enforce_fee_cap(*, actual_fee_wei: int, accepted_cap_wei: int) -> None:
    """Fail closed when a transaction or replacement exceeds its Owner-approved cap."""

    if actual_fee_wei < 0 or accepted_cap_wei < 0:
        raise ValueError("fee and accepted cap must be nonnegative")
    if actual_fee_wei > accepted_cap_wei:
        raise ValueError("FEE_CAP_EXCEEDED")
