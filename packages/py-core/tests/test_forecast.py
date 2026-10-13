from __future__ import annotations

import pytest

from treasurypilot_core.domain import (
    ApprovedRequest,
    LateFee,
    Limits,
    PaymentTerms,
    PolicyView,
    Snapshot,
    WalletState,
)
from treasurypilot_core.engine import forecast, refill_bound
from treasurypilot_core.money import BaseUnits

DAY = 100
WALLET = "0xops"


def snapshot(
    *,
    ops_balance: int = 20,
    ops_buffer: int = 10,
    ops_target: int = 50,
    source_balance: int = 1_000,
    source_buffer: int = 100,
    payees: dict[str, int] | None = None,
    refill_used: int = 0,
) -> Snapshot:
    return Snapshot(
        day=DAY,
        source=WalletState(
            address="0xsafe",
            balance=BaseUnits(source_balance),
            buffer=BaseUnits(source_buffer),
            target=BaseUnits(source_buffer),
        ),
        operational={
            WALLET: WalletState(
                address=WALLET,
                balance=BaseUnits(ops_balance),
                buffer=BaseUnits(ops_buffer),
                target=BaseUnits(max(ops_buffer, ops_target)),
            )
        },
        used_today={"pay": BaseUnits(0), "refill": BaseUnits(refill_used)},
        payee_active_day={"0xpayee": DAY} if payees is None else payees,
        safe_usdc=BaseUnits(source_balance),
        a_usdc=BaseUnits(0),
        pool_available=BaseUnits(0),
        supply_rate_bps=0,
        borrow_rate_bps=0,
        debt=BaseUnits(0),
    )


def policy(*, refill_per_request: int = 1_000, refill_daily: int = 1_000) -> PolicyView:
    return PolicyView(
        pay=Limits(per_request=BaseUnits(1_000), daily=BaseUnits(1_000)),
        refill=Limits(per_request=BaseUnits(refill_per_request), daily=BaseUnits(refill_daily)),
        cooling_seconds=0,
    )


def obligation(
    request_id: str,
    amount: int,
    *,
    due: int = DAY,
    seq: int = 1,
    payee: str = "0xpayee",
    early_amount: int | None = None,
    early_pay_by: int | None = None,
) -> ApprovedRequest:
    return ApprovedRequest(
        id=request_id,
        paying_wallet=WALLET,
        payee=payee,
        amount=BaseUnits(amount),
        approved_seq=seq,
        terms=PaymentTerms(net_due_day=due),
        early_amount=None if early_amount is None else BaseUnits(early_amount),
        early_pay_by=early_pay_by,
    )


def test_forecast_matches_hand_computed_balance_and_refill() -> None:
    result = forecast(snapshot(), [obligation("invoice-1", 40)], policy())

    day0 = result.days[0]
    assert day0.balances == {"0xsafe": 930, WALLET: 50}
    assert len(day0.suggested_refills) == 1
    refill = day0.suggested_refills[0]
    assert (refill.day, refill.request_id, refill.amount) == (DAY, "invoice-1", 70)
    assert (refill.source_wallet, refill.target_wallet) == ("0xsafe", WALLET)
    assert result.days[1].balances == day0.balances
    assert result.buffer_hit_days == {"0xsafe": (), WALLET: ()}


def test_refill_respects_per_request_daily_limits_and_source_buffer() -> None:
    snap = snapshot(
        ops_balance=0,
        ops_buffer=50,
        ops_target=400,
        source_balance=500,
        source_buffer=200,
    )
    limits = policy(refill_per_request=260, refill_daily=260)
    req = obligation("invoice-1", 200)
    result = forecast(snap, [req], limits)

    # The target top-up would be 600; limits cap it at the minimum safe refill.
    assert result.days[0].suggested_refills[0].amount == 250
    assert result.days[0].balances == {"0xsafe": 250, WALLET: 50}
    assert result.days[0].balances["0xsafe"] >= snap.source.buffer
    assert result.days[0].suggested_refills[0].amount <= snap.source.balance - snap.source.buffer
    assert result.days[0].suggested_refills[0].amount <= limits.refill.per_request
    assert result.days[0].suggested_refills[0].amount <= limits.refill.daily
    assert result.days[0].suggested_refills[0].amount <= refill_bound(
        snap.operational[WALLET], req.amount
    )


def test_same_day_schedule_order_is_preserved_when_replaying_balances() -> None:
    snap = snapshot(ops_balance=0, ops_buffer=0, ops_target=100)
    result = forecast(
        snap,
        [
            obligation("z1", 10, due=DAY, seq=1),
            obligation("a1", 50, due=DAY + 1, seq=2),
        ],
        policy(),
    )

    day0 = result.days[0]
    assert [refill.request_id for refill in day0.suggested_refills] == ["z1"]
    assert day0.balances[WALLET] == 50


def test_early_payment_and_future_due_shortfall_are_reported() -> None:
    snap = snapshot(payees={"0xpayee": DAY + 10})
    req = obligation("early", 100, due=DAY + 3, early_amount=80, early_pay_by=DAY + 2)
    result = forecast(snap, [req], policy(), days=7)

    # Cooling delays payment past the forecast's end; the obligation remains unpaid.
    assert result.shortfall_days == (DAY + 3, DAY + 4, DAY + 5, DAY + 6)
    assert result.days[3].unpaid_due == 100
    assert result.deferred_request_ids == ("early",)


def test_unpayable_due_obligation_is_reported_as_unplanned() -> None:
    req = obligation("unknown-payee", 40, due=DAY)
    result = forecast(snapshot(payees={}), [req], policy())

    assert result.unplanned_request_ids == ("unknown-payee",)
    assert result.shortfall_days == (DAY, DAY + 1, DAY + 2, DAY + 3, DAY + 4, DAY + 5, DAY + 6)
    assert result.days[0].unpaid_due == 40


@pytest.mark.parametrize("days", [0, 31])
def test_forecast_rejects_days_outside_supported_horizon(days: int) -> None:
    with pytest.raises(ValueError, match="days must be between"):
        forecast(snapshot(), [], policy(), days=days)


def test_forecast_rejects_non_integer_days() -> None:
    with pytest.raises(TypeError, match="days must be an integer"):
        forecast(snapshot(), [], policy(), days=True)  # type: ignore[arg-type]


def test_unpaid_due_includes_accrued_late_fees() -> None:
    # Review repro: 1,000 due today, 5% per day late, payee cooling until DAY + 5.
    late = ApprovedRequest(
        id="late",
        paying_wallet=WALLET,
        payee="0xpayee",
        amount=BaseUnits(1_000),
        approved_seq=1,
        terms=PaymentTerms(
            net_due_day=DAY,
            late_fee=LateFee(kind="percent_per_period", rate_bps=500, period_days=1),
        ),
    )
    result = forecast(snapshot(payees={"0xpayee": DAY + 5}), [late], policy())
    assert result.days[0].unpaid_due == 1_000
    assert result.days[3].unpaid_due == 1_150


def test_buffer_hit_reflects_an_obligation_the_scheduler_cannot_pay() -> None:
    # Review repro: balance 60, buffer 50, 40 due tomorrow, no refill capacity.
    snap = snapshot(ops_balance=60, ops_buffer=50, ops_target=50, source_balance=100)
    result = forecast(snap, [obligation("r1", 40, due=DAY + 1)], policy())
    assert result.unplanned_request_ids == ("r1",)
    assert result.days[0].buffer_hit_wallets == ()
    assert result.days[1].buffer_hit_wallets == (WALLET,)
    assert result.buffer_hit_days[WALLET] == tuple(range(DAY + 1, DAY + 7))


def test_forecast_requires_safe_t_as_the_source() -> None:
    snap = snapshot().model_copy(update={"safe_usdc": BaseUnits(5)})
    with pytest.raises(ValueError, match="safe_usdc"):
        forecast(snap, [], policy())
