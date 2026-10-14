from __future__ import annotations

import random
from collections import defaultdict

from hypothesis import given, settings
from hypothesis import strategies as st

from treasurypilot_core.domain import (
    ApprovedRequest,
    Limits,
    PaymentTerms,
    PolicyView,
    Snapshot,
    WalletState,
)
from treasurypilot_core.engine import pay_amount, request_value, schedule_edf
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy.reason_codes import PolicyReasonCode

DAY = 0
WALLET = "0xops"


def snapshot(
    *,
    ops_balance: int = 0,
    ops_buffer: int = 0,
    ops_target: int = 0,
    source_balance: int = 1_000_000,
    source_buffer: int = 0,
    payees: dict[str, int] | None = None,
    pay_used: int = 0,
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
        used_today={"pay": BaseUnits(pay_used), "refill": BaseUnits(refill_used)},
        payee_active_day={"0xpayee": DAY} if payees is None else payees,
        safe_usdc=BaseUnits(source_balance),
        a_usdc=BaseUnits(0),
        pool_available=BaseUnits(0),
        supply_rate_bps=0,
        borrow_rate_bps=0,
        debt=BaseUnits(0),
    )


def policy(
    *,
    pay_per_request: int = 1_000_000,
    pay_daily: int = 1_000_000,
    refill_per_request: int = 1_000_000,
    refill_daily: int = 1_000_000,
) -> PolicyView:
    return PolicyView(
        pay=Limits(per_request=BaseUnits(pay_per_request), daily=BaseUnits(pay_daily)),
        refill=Limits(per_request=BaseUnits(refill_per_request), daily=BaseUnits(refill_daily)),
        cooling_seconds=0,
    )


def obligation(
    request_id: str,
    amount: int,
    *,
    due: int = 5,
    seq: int = 1,
    payee: str = "0xpayee",
    terms: PaymentTerms | None = None,
    early_amount: int | None = None,
    early_pay_by: int | None = None,
    exception_granted: bool = False,
) -> ApprovedRequest:
    return ApprovedRequest(
        id=request_id,
        paying_wallet=WALLET,
        payee=payee,
        amount=BaseUnits(amount),
        approved_seq=seq,
        terms=terms or PaymentTerms(net_due_day=due),
        early_amount=None if early_amount is None else BaseUnits(early_amount),
        early_pay_by=early_pay_by,
        exception_granted=exception_granted,
    )


def test_request_payable_only_after_its_due_day_is_scheduled_late() -> None:
    # Review repro: due day 1, payee active day 3 used to give a 2-day horizon.
    result = schedule_edf([obligation("r1", 100, due=1)], snapshot(payees={"0xpayee": 3}), policy())
    assert [(item.request_id, item.day) for item in result.items] == [("r1", 3)]
    # No solver could have met that deadline, so EDF is not charged for it.
    assert result.objective[1] == 0


def test_overdue_request_rolls_to_the_next_day_when_today_is_capped() -> None:
    result = schedule_edf(
        [obligation("r1", 100, due=0, seq=1), obligation("r2", 100, due=0, seq=2)],
        snapshot(),
        policy(pay_daily=150),
    )
    assert [(item.request_id, item.day) for item in result.items] == [("r1", 0), ("r2", 1)]


def test_legacy_discount_debits_the_discounted_amount() -> None:
    # Review repro: 1,000 on 2/10 net 30 paid on day 0 is worth 20 and debits 980.
    terms = PaymentTerms(net_due_day=30, discount_bps=200, discount_deadline_day=10)
    request = obligation("r1", 1_000, terms=terms)
    result = schedule_edf([request], snapshot(ops_balance=980), policy(pay_daily=980))
    assert [(item.day, item.value, item.refill) for item in result.items] == [(0, 20, 0)]
    assert pay_amount(request, 0) == 980


def test_per_request_cap_uses_the_amount_actually_paid() -> None:
    request = obligation("r1", 1_020, due=20, early_amount=990, early_pay_by=5)
    result = schedule_edf([request], snapshot(), policy(pay_per_request=1_000))
    assert [(item.request_id, item.day) for item in result.items] == [("r1", 0)]


def test_needs_exception_reports_the_value_if_granted() -> None:
    result = schedule_edf([obligation("r1", 2_000)], snapshot(), policy(pay_per_request=1_000))
    assert result.items == ()
    assert result.infeasible[0].reason == "NEEDS_EXCEPTION"
    assert "PAY_PER_REQUEST_CAP" in result.binding
    assert result.objective[1] == 0


def test_unknown_payee_is_never_assumed_active() -> None:
    result = schedule_edf([obligation("r1", 100, payee="0xnew")], snapshot(), policy())
    assert result.items == ()
    assert result.infeasible[0].reason == PolicyReasonCode.PAYEE_UNKNOWN


def test_reason_codes_come_from_the_catalogue() -> None:
    result = schedule_edf(
        [obligation("r1", 100, due=0, seq=1), obligation("r2", 100, due=0, seq=2)],
        snapshot(),
        policy(pay_daily=100),
    )
    assert result.items[1].day == 1
    capped = schedule_edf([obligation("r1", 200, due=0)], snapshot(), policy(pay_daily=100))
    assert capped.infeasible[0].reason == PolicyReasonCode.OVER_DAILY_LIMIT
    assert capped.binding == ("PAY_DAILY_CAP",)


def test_every_refill_stop_reason_is_reported_as_binding() -> None:
    result = schedule_edf([obligation("r1", 500)], snapshot(), policy(refill_per_request=100))
    assert result.infeasible[0].reason == PolicyReasonCode.OVER_REFILL_PER_REQUEST
    assert result.binding == ("REFILL_PER_REQUEST_CAP",)


@st.composite
def scenarios(draw: st.DrawFn) -> tuple[list[ApprovedRequest], Snapshot, PolicyView]:
    payees = {f"0xp{index}": draw(st.integers(0, 6)) for index in range(3)}
    requests = []
    for index in range(draw(st.integers(1, 6))):
        amount = draw(st.integers(1, 400))
        due = draw(st.integers(0, 8))
        early = draw(st.booleans())
        requests.append(
            obligation(
                f"r{index}",
                amount,
                due=due,
                seq=draw(st.integers(0, 3)),
                payee=draw(st.sampled_from([*payees, "0xunknown"])),
                early_amount=max(1, amount - draw(st.integers(0, 20))) if early else None,
                early_pay_by=draw(st.integers(0, due)) if early else None,
                exception_granted=draw(st.booleans()),
            )
        )
    snap = snapshot(
        ops_balance=draw(st.integers(0, 300)),
        ops_buffer=draw(st.integers(0, 50)),
        ops_target=draw(st.integers(0, 300)),
        source_balance=draw(st.integers(0, 1_500)),
        source_buffer=draw(st.integers(0, 100)),
        payees=payees,
        pay_used=draw(st.integers(0, 200)),
        refill_used=draw(st.integers(0, 200)),
    )
    pol = policy(
        pay_per_request=draw(st.integers(1, 400)),
        pay_daily=draw(st.integers(1, 800)),
        refill_per_request=draw(st.integers(0, 600)),
        refill_daily=draw(st.integers(0, 800)),
    )
    return requests, snap, pol


@settings(max_examples=300, deadline=None)
@given(scenarios())
def test_schedules_respect_caps_cooling_and_buffers(
    scenario: tuple[list[ApprovedRequest], Snapshot, PolicyView],
) -> None:
    requests, snap, pol = scenario
    by_id = {request.id: request for request in requests}
    result = schedule_edf(requests, snap, pol)

    outcome_ids = [item.request_id for item in result.items] + [
        entry.request_id for entry in result.infeasible
    ]
    assert sorted(outcome_ids) == sorted(by_id)

    pay_by_day: dict[int, int] = defaultdict(int)
    refill_by_day: dict[int, int] = defaultdict(int)
    pay_by_day[snap.day] = int(snap.used_today["pay"])
    refill_by_day[snap.day] = int(snap.used_today["refill"])
    ops = snap.operational[WALLET]
    balance, source_left = int(ops.balance), int(snap.source.balance)
    for item in result.items:
        request = by_id[item.request_id]
        amount = int(pay_amount(request, item.day))
        assert item.day >= snap.payee_active_day[request.payee]  # cooling, known payee
        assert amount <= pol.pay.per_request or request.exception_granted
        assert item.refill <= pol.refill.per_request
        pay_by_day[item.day] += amount
        refill_by_day[item.day] += int(item.refill)
        balance += int(item.refill) - amount
        source_left -= int(item.refill)
        assert balance >= ops.buffer
        # A refill never takes Safe T below its buffer (it may start below it).
        assert item.refill == 0 or source_left >= snap.source.buffer
        assert item.value == request_value(request, item.day)
    for day, total in pay_by_day.items():
        assert total <= max(pol.pay.daily, snap.used_today["pay"] if day == snap.day else 0)
    for day, total in refill_by_day.items():
        assert total <= max(pol.refill.daily, snap.used_today["refill"] if day == snap.day else 0)


@settings(max_examples=200, deadline=None)
@given(scenarios(), st.randoms(use_true_random=False))
def test_schedule_does_not_depend_on_input_order(
    scenario: tuple[list[ApprovedRequest], Snapshot, PolicyView], rng: random.Random
) -> None:
    requests, snap, pol = scenario
    shuffled = list(requests)
    rng.shuffle(shuffled)
    assert schedule_edf(shuffled, snap, pol) == schedule_edf(requests, snap, pol)
