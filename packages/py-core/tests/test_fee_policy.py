from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from treasurypilot_core.domain.fee_policy import (
    FeeDecision,
    FeePreset,
    assess_fee,
    discount_justifies_early_payment,
    enforce_fee_cap,
    estimate_plan_fee_wei,
    fee_in_asset_base_units,
    propose_fee_policy,
)


def test_fee_proposal_matches_documented_seven_day_example() -> None:
    avg_plan_fee = 400_000_000_000_000  # 0.0004 ETH
    proposal = propose_fee_policy(
        plan_fees_wei=[avg_plan_fee] * 70,
        plans_last_7d=70,
        base_fee_per_gas_wei=30_000_000_000,
        priority_fees_wei=[1_000_000_000, 2_000_000_000, 3_000_000_000],
    )

    assert proposal.preset is FeePreset.NORMAL
    assert proposal.avg_plan_fee_7d_wei == avg_plan_fee
    assert proposal.p90_plan_fee_7d_wei == avg_plan_fee
    assert proposal.plans_per_day_7d == 10
    assert proposal.per_plan_threshold_wei == 1_200_000_000_000_000
    assert proposal.daily_budget_wei == 12_000_000_000_000_000
    assert proposal.max_fee_per_gas_wei == 62_000_000_000


def test_fee_proposal_uses_highest_of_three_times_average_and_p90() -> None:
    proposal = propose_fee_policy(
        plan_fees_wei=[100, 100, 100, 100, 100, 100, 100, 100, 500],
        plans_last_7d=9,
        base_fee_per_gas_wei=10,
        priority_fees_wei=[1, 2, 3],
    )
    assert proposal.avg_plan_fee_7d_wei == 144
    assert proposal.p90_plan_fee_7d_wei == 500
    assert proposal.per_plan_threshold_wei == 500
    assert proposal.daily_budget_wei == 1_000


def test_new_treasury_gets_a_nonzero_fee_baseline_from_fee_history() -> None:
    proposal = propose_fee_policy(
        plan_fees_wei=[],
        plans_last_7d=0,
        base_fee_per_gas_wei=10,
        priority_fees_wei=[2],
    )
    assert proposal.avg_plan_fee_7d_wei == 42_000 * 10 + 21_000 * 2
    assert proposal.p90_plan_fee_7d_wei == proposal.avg_plan_fee_7d_wei
    assert proposal.plans_per_day_7d == 1
    assert proposal.daily_budget_wei == 6 * proposal.avg_plan_fee_7d_wei


def test_estimates_every_plan_step_as_integer_wei() -> None:
    assert estimate_plan_fee_wei([50_000, 21_000], [20, 30]) == 1_630_000
    with pytest.raises(ValueError):
        estimate_plan_fee_wei([50_000, 21_000], [20])


def test_daily_budget_and_plans_per_day_share_one_plan_count() -> None:
    # Fee samples without a count: both figures fall back to the sample count (14 plans -> 2/day).
    proposal = propose_fee_policy(
        plan_fees_wei=[1_000] * 14,
        plans_last_7d=0,
        base_fee_per_gas_wei=1,
        priority_fees_wei=[],
    )
    assert proposal.plans_per_day_7d == 2.0
    assert proposal.daily_budget_wei == 6_000


def test_fee_hold_auto_proceeds_only_when_both_limits_allow_it() -> None:
    now = datetime(2026, 10, 15, 10, tzinfo=UTC)
    safe_at = now + timedelta(days=1)
    within_limits = assess_fee(
        estimated_fee_wei=100,
        per_plan_threshold_wei=100,
        spent_today_wei=900,
        daily_budget_wei=1_000,
        last_safe_execution_at=safe_at,
        now=now,
    )
    over_plan_threshold = assess_fee(
        estimated_fee_wei=101,
        per_plan_threshold_wei=100,
        spent_today_wei=0,
        daily_budget_wei=1_000,
        last_safe_execution_at=safe_at,
        now=now,
    )
    over_daily_budget = assess_fee(
        estimated_fee_wei=100,
        per_plan_threshold_wei=100,
        spent_today_wei=901,
        daily_budget_wei=1_000,
        last_safe_execution_at=safe_at,
        now=now,
    )

    assert within_limits.decision is FeeDecision.PROCEED
    assert over_plan_threshold.decision is FeeDecision.DEFER
    assert over_plan_threshold.reason_code == "FEE_ABOVE_THRESHOLD"
    assert over_daily_budget.decision is FeeDecision.DEFER
    assert over_daily_budget.reason_code == "FEE_BUDGET_EXHAUSTED"


def test_fee_hold_escalates_only_at_last_safe_execution_time() -> None:
    now = datetime(2026, 10, 15, 10, tzinfo=UTC)
    assessment = assess_fee(
        estimated_fee_wei=200,
        per_plan_threshold_wei=100,
        spent_today_wei=0,
        daily_budget_wei=10_000,
        last_safe_execution_at=now,
        now=now,
    )
    assert assessment.decision is FeeDecision.AWAITING_FEE_ACCEPTANCE
    assert assessment.reason_code == "FEE_ABOVE_THRESHOLD"


def test_documented_spike_defers_then_prompts_at_the_last_safe_time() -> None:
    now = datetime(2026, 10, 15, 10, tzinfo=UTC)
    inputs = {
        "estimated_fee_wei": 2_000_000_000_000_000,
        "per_plan_threshold_wei": 1_200_000_000_000_000,
        "spent_today_wei": 0,
        "daily_budget_wei": 12_000_000_000_000_000,
    }
    before_deadline = assess_fee(**inputs, last_safe_execution_at=now + timedelta(days=1), now=now)
    at_deadline = assess_fee(**inputs, last_safe_execution_at=now, now=now)

    assert before_deadline.decision is FeeDecision.DEFER
    assert at_deadline.decision is FeeDecision.AWAITING_FEE_ACCEPTANCE
    assert fee_in_asset_base_units(2_000_000_000_000_000, 3_000 * 10**6) == 6_000_000


def test_fee_to_asset_and_discount_are_integer_and_strictly_positive() -> None:
    price = 3_000 * 10**6
    fee = 2 * 10**15
    assert fee_in_asset_base_units(fee, price) == 6_000_000
    assert not discount_justifies_early_payment(
        discount_asset_base_units=6_000_000,
        estimated_fee_wei=fee,
        reference_eth_price=price,
    )
    assert discount_justifies_early_payment(
        discount_asset_base_units=6_000_001,
        estimated_fee_wei=fee,
        reference_eth_price=price,
    )


def test_executor_cap_fails_closed_when_fee_is_over_the_accepted_limit() -> None:
    enforce_fee_cap(actual_fee_wei=1_000, accepted_cap_wei=1_000)
    with pytest.raises(ValueError, match="FEE_CAP_EXCEEDED"):
        enforce_fee_cap(actual_fee_wei=1_001, accepted_cap_wei=1_000)


def test_spec_8_7_example_end_to_end() -> None:
    """Mandate §8.7 (NORMAL): avg 0.0004 ETH, 10 plans/day, spike to 0.002 ETH."""
    eth = 10**18
    proposal = propose_fee_policy(
        plan_fees_wei=[4 * eth // 10_000] * (7 * 10),
        plans_last_7d=7 * 10,  # 10 plans/day over 7 days
        base_fee_per_gas_wei=30_000_000_000,
        priority_fees_wei=[1],
    )
    assert proposal.per_plan_threshold_wei == 12 * eth // 10_000  # 0.0012 ETH
    assert proposal.daily_budget_wei == 12 * eth // 1_000  # max(0.012, 0.0024)
    now = datetime(2026, 10, 15, 10, tzinfo=UTC)
    spike = {
        "estimated_fee_wei": 2 * eth // 1_000,
        "per_plan_threshold_wei": proposal.per_plan_threshold_wei,
        "spent_today_wei": 0,
        "daily_budget_wei": proposal.daily_budget_wei,
    }
    due_in_5_days = assess_fee(**spike, last_safe_execution_at=now + timedelta(days=5), now=now)
    due_today = assess_fee(**spike, last_safe_execution_at=now, now=now)
    assert (due_in_5_days.decision, due_in_5_days.reason_code) == (
        FeeDecision.DEFER,
        "FEE_ABOVE_THRESHOLD",
    )
    assert due_today.decision is FeeDecision.AWAITING_FEE_ACCEPTANCE
    assert fee_in_asset_base_units(spike["estimated_fee_wei"], 3_000 * 10**6) == 6 * 10**6
