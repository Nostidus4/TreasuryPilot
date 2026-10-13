from __future__ import annotations

import pytest

from treasurypilot_core.domain import (
    ApprovedRequest,
    BorrowProposal,
    Limits,
    LiquidityDecision,
    LiquidityPolicy,
    PaymentTerms,
    Schedule,
    ScheduledItem,
    Snapshot,
    WalletState,
)
from treasurypilot_core.engine import decide_liquidity, liquidity_position, propose_borrow
from treasurypilot_core.money import BaseUnits

DAY = 100


def snapshot(
    *,
    safe: int,
    floor: int = 1_000,
    a_usdc: int = 0,
    pool: int = 1_000_000,
    supplied_today: int = 0,
    withdrawn_today: int = 0,
    source_balance: int | None = None,
    supply_rate_bps: int = 0,
    borrow_rate_bps: int = 0,
    debt: int = 0,
    health_factor: int | None = None,
) -> Snapshot:
    return Snapshot(
        day=DAY,
        source=WalletState(
            address="0xsafe",
            balance=BaseUnits(safe if source_balance is None else source_balance),
            buffer=BaseUnits(floor),
            target=BaseUnits(floor),
        ),
        operational={},
        used_today={
            "pay": BaseUnits(0),
            "refill": BaseUnits(0),
            "supply": BaseUnits(supplied_today),
            "withdraw": BaseUnits(withdrawn_today),
        },
        payee_active_day={},
        safe_usdc=BaseUnits(safe),
        a_usdc=BaseUnits(a_usdc),
        pool_available=BaseUnits(pool),
        supply_rate_bps=supply_rate_bps,
        borrow_rate_bps=borrow_rate_bps,
        debt=BaseUnits(debt),
        health_factor=health_factor,
    )


def obligation(
    request_id: str,
    amount: int,
    *,
    due_in: int = 5,
    early_amount: int | None = None,
    early_in: int | None = None,
) -> ApprovedRequest:
    return ApprovedRequest(
        id=request_id,
        paying_wallet="0xops",
        payee="0xpayee",
        amount=BaseUnits(amount),
        approved_seq=1,
        terms=PaymentTerms(net_due_day=DAY + due_in),
        early_amount=None if early_amount is None else BaseUnits(early_amount),
        early_pay_by=None if early_in is None else DAY + early_in,
    )


def schedule(*days: tuple[str, int]) -> Schedule:
    return Schedule(
        items=[
            ScheduledItem(request_id=rid, day=DAY + offset, refill=BaseUnits(0), value=0)
            for rid, offset in days
        ],
        infeasible=[],
        objective=(0, 0, 0, 0),
        binding=[],
        solver="EDF",
        status="FEASIBLE",
    )


def policy(
    *, min_supply: int = 500, per_tx: int = 1_000_000, daily: int = 1_000_000, horizon: int = 30
) -> LiquidityPolicy:
    return LiquidityPolicy(
        supply=Limits(per_request=BaseUnits(per_tx), daily=BaseUnits(daily)),
        min_supply=BaseUnits(min_supply),
        reserve_horizon_days=horizon,
    )


def test_section_15_example_supplies_d2_and_withdraws_d3() -> None:
    requests = [obligation("r1", 2_000)]
    d2 = decide_liquidity(snapshot(safe=6_000), requests, schedule(), policy())
    assert (d2.kind, d2.amount) == ("SUPPLY", 3_000)
    assert d2.position.required_safe_reserve == 3_000

    requests.append(obligation("r2", 2_500))
    d3 = decide_liquidity(snapshot(safe=3_000, a_usdc=3_000), requests, schedule(), policy())
    assert (d3.kind, d3.amount) == ("WITHDRAW", 2_625)
    assert d3.position.deficit == 2_500


def test_horizon_includes_its_last_day_and_excludes_the_next() -> None:
    # Section 15: "due day <= today + 30" (inclusive).
    inside = obligation("r1", 700, due_in=30)
    outside = obligation("r2", 900, due_in=31)
    position = liquidity_position(snapshot(safe=6_000), [inside, outside], schedule(), policy())
    assert position.payment_reserve == 700


def test_early_payment_scheduled_inside_the_horizon_is_reserved() -> None:
    # Due after the 7-day horizon, but the schedule pays it early on day 5.
    early = obligation("r1", 1_000, due_in=40, early_amount=980, early_in=5)
    reserved = liquidity_position(
        snapshot(safe=6_000), [early], schedule(("r1", 5)), policy(horizon=7)
    )
    unscheduled = liquidity_position(snapshot(safe=6_000), [early], schedule(), policy(horizon=7))
    assert reserved.payment_reserve == 980
    assert unscheduled.payment_reserve == 0


def test_standard_amount_is_reserved_when_paid_after_the_early_deadline() -> None:
    late = obligation("r1", 1_000, due_in=10, early_amount=980, early_in=5)
    position = liquidity_position(snapshot(safe=6_000), [late], schedule(("r1", 8)), policy())
    assert position.payment_reserve == 1_000


def test_min_supply_is_checked_before_the_caps() -> None:
    # Available 3,000 >= min 500, but only 400 of the daily cap is left: supply 400.
    decision = decide_liquidity(
        snapshot(safe=6_000, supplied_today=600),
        [obligation("r1", 2_000)],
        schedule(),
        policy(daily=1_000),
    )
    assert (decision.kind, decision.amount) == ("SUPPLY", 400)


@pytest.mark.parametrize(
    ("snap", "pol", "reason"),
    [
        (snapshot(safe=3_000), policy(min_supply=0), "BELOW_MIN_SUPPLY"),
        (snapshot(safe=3_400), policy(), "BELOW_MIN_SUPPLY"),
        (snapshot(safe=6_000, supplied_today=1_000), policy(daily=1_000), "OVER_SUPPLY_DAILY"),
        (snapshot(safe=6_000), policy(per_tx=0), "OVER_SUPPLY_PER_TX"),
        (snapshot(safe=6_000, withdrawn_today=2_625), policy(), "WITHDRAWN_TODAY"),
    ],
)
def test_no_zero_supply_is_ever_returned(snap: Snapshot, pol: LiquidityPolicy, reason: str) -> None:
    decision = decide_liquidity(snap, [obligation("r1", 2_000)], schedule(), pol)
    assert (decision.kind, decision.amount, decision.reason) == ("NONE", 0, reason)


def test_insufficient_liquidity_reports_the_partial_withdrawal_and_shortfall() -> None:
    decision = decide_liquidity(
        snapshot(safe=1_000, a_usdc=1_500), [obligation("r1", 3_000)], schedule(), policy()
    )
    assert decision.kind == "INSUFFICIENT_LIQUIDITY"
    assert (decision.amount, decision.shortfall) == (1_500, 1_500)


def test_nothing_to_withdraw_is_a_zero_amount_insufficient_liquidity() -> None:
    decision = decide_liquidity(
        snapshot(safe=1_000, a_usdc=0), [obligation("r1", 3_000)], schedule(), policy()
    )
    assert (decision.kind, decision.amount, decision.shortfall) == (
        "INSUFFICIENT_LIQUIDITY",
        0,
        3_000,
    )


def test_zero_supply_or_withdraw_decisions_cannot_be_built() -> None:
    position = liquidity_position(snapshot(safe=6_000), [], schedule(), policy())
    for kind in ("SUPPLY", "WITHDRAW"):
        with pytest.raises(ValueError, match="positive amount"):
            LiquidityDecision(kind=kind, amount=BaseUnits(0), reason="x", position=position)


def test_source_wallet_must_be_safe_t() -> None:
    with pytest.raises(ValueError, match="safe_usdc"):
        liquidity_position(snapshot(safe=6_000, source_balance=5_000), [], schedule(), policy())


def test_borrow_proposal_covers_unwithdrawable_shortfall_and_estimates_costs() -> None:
    snap = snapshot(
        safe=1_000,
        a_usdc=500,
        pool=500,
        supply_rate_bps=300,
        borrow_rate_bps=500,
        debt=1_000,
        health_factor=1_200_000_000_000_000_000,
    )
    decision = decide_liquidity(snap, [obligation("r1", 3_000)], schedule(), policy())
    assert decision.kind == "INSUFFICIENT_LIQUIDITY"

    proposal = propose_borrow(snap, decision.shortfall, until_day=DAY + 365)

    assert proposal.amount == 2_500
    assert proposal.cost_to_repayment == 125
    assert proposal.withdraw_cost == 75
    assert proposal.health_factor_before == 1_200_000_000_000_000_000
    assert proposal.health_factor_after == 342_857_142_857_142_857
    assert "below 1.0" in proposal.reason
    assert isinstance(proposal, BorrowProposal)


def test_borrow_proposal_cannot_become_an_executable_schedule_item() -> None:
    proposal = propose_borrow(
        snapshot(safe=1_000, debt=1_000, health_factor=2 * 10**18), BaseUnits(100), DAY + 30
    )

    with pytest.raises(ValueError, match="ScheduledItem"):
        Schedule(
            items=[proposal],  # type: ignore[list-item]
            infeasible=[],
            objective=(0, 0, 0, 0),
            binding=[],
            solver="EDF",
            status="FEASIBLE",
        )


def test_borrow_proposal_marks_health_factor_unknown_without_existing_debt() -> None:
    proposal = propose_borrow(snapshot(safe=1_000), BaseUnits(100), DAY + 30)

    assert proposal.health_factor_before is None
    assert proposal.health_factor_after is None
    assert "unknown" in proposal.reason


@pytest.mark.parametrize(
    ("deficit", "until_day", "message"),
    [
        (0, DAY + 1, "positive deficit"),
        (100, DAY - 1, "cannot precede"),
    ],
)
def test_borrow_proposal_rejects_invalid_shortfalls(
    deficit: int, until_day: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        propose_borrow(snapshot(safe=1_000), BaseUnits(deficit), until_day)


def test_borrow_reason_always_compares_costs() -> None:
    # Review repro: no debt, cheaper borrowing; the comparison must still be stated.
    proposal = propose_borrow(
        snapshot(safe=1_000, borrow_rate_bps=100, supply_rate_bps=500),
        BaseUnits(10**9),
        DAY + 30,
    )
    assert (proposal.cost_to_repayment, proposal.withdraw_cost) == (821_917, 4_109_589)
    assert proposal.reason.startswith("Estimated borrowing cost is lower")
    assert "unknown" in proposal.reason


def test_borrow_reason_warns_just_above_health_factor_one() -> None:
    proposal = propose_borrow(
        snapshot(safe=1_000, debt=1_000, health_factor=15 * 10**17), BaseUnits(400), DAY + 30
    )
    assert proposal.health_factor_after is not None
    assert 10**18 <= proposal.health_factor_after < 11 * 10**17
    assert "below 1.1" in proposal.reason
