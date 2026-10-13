from __future__ import annotations

import importlib.util
from pathlib import Path

from treasurypilot_core.domain import ApprovedRequest, PaymentTerms
from treasurypilot_core.engine import forecast
from treasurypilot_core.money import BaseUnits

_spec = importlib.util.spec_from_file_location(
    "scheduler_helpers", Path(__file__).with_name("test_scheduler.py")
)
assert _spec and _spec.loader
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
snapshot, policy, WALLET = _helpers.snapshot, _helpers.policy, _helpers.WALLET


def obligation(rid: str, amount: int, due: int, payee: str = "0xpayee") -> ApprovedRequest:
    return ApprovedRequest(
        id=rid,
        paying_wallet=WALLET,
        payee=payee,
        amount=BaseUnits(amount),
        approved_seq=1,
        terms=PaymentTerms(net_due_day=due),
    )


def test_same_day_items_replay_in_scheduling_order() -> None:
    # Review repro: z1 (earlier due) refills to target 100; a1 relies on that surplus.
    snap = snapshot(ops_balance=0, ops_buffer=0, ops_target=100)
    result = forecast(snap, [obligation("z1", 10, due=0), obligation("a1", 50, due=1)], policy())
    day0 = result.days[0]
    assert [r.request_id for r in day0.suggested_refills] == ["z1"]
    assert day0.balances[WALLET] == 50  # 0 + 110 refill - 10 - 50


def test_items_after_the_window_are_reported_and_shortfalls_visible() -> None:
    snap = snapshot(payees={"0xpayee": 10})
    result = forecast(snap, [obligation("r1", 100, due=3)], policy(), days=7)
    assert result.deferred_request_ids == ("r1",)
    assert result.shortfall_days == (3, 4, 5, 6)
    assert result.days[3].unpaid_due == 100
