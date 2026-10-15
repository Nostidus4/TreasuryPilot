"""Pure parts of the dashboard treasury state (TRS-009)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from treasurypilot_api.treasury.state import (
    STALE_AFTER,
    ChainRead,
    budgets_of,
    queue_roles,
    staleness_of,
    wallet_figures,
)

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
T, O1 = "0x" + "aa" * 20, "0x" + "bb" * 20


def _read(data: dict[str, object], age: timedelta = timedelta(seconds=5)) -> ChainRead:
    return ChainRead(block_number=7, observed_at=NOW - age, data=data)


def test_staleness_flips_after_three_missed_cycles() -> None:
    assert staleness_of(_read({}, STALE_AFTER), NOW).stale is False
    stale = staleness_of(_read({}, STALE_AFTER + timedelta(seconds=1)), NOW)
    assert stale.stale is True and stale.block_number == 7


def test_wallet_figures_skip_unread_wallets_and_floor_target_at_buffer() -> None:
    read = _read(
        {
            "balances": {T: "900", O1: "10"},
            "buffers": {T: "100", O1: "5"},
            "targets": {T: "0", O1: "50"},
        }
    )
    figures = wallet_figures(read, [T.upper().replace("0X", "0x"), O1, "0x" + "cc" * 20])
    assert (figures[T].balance, figures[T].buffer, figures[T].target) == ("900", "100", "100")
    assert figures[O1].target == "50" and len(figures) == 2


def test_budgets_need_the_mandate_and_the_counters() -> None:
    mandate = {
        "pay": {"per_request": "5", "daily": "9"},
        "refill": {"per_request": "1", "daily": "2"},
    }
    both = budgets_of(
        _read({"module": {"mandate": mandate, "used_today": {"PAY": "3", "REFILL": "0"}}})
    )
    assert [(b.action, b.used_today, b.daily_limit, b.per_request) for b in both] == [
        ("PAY", "3", "9", "5"),
        ("REFILL", "0", "2", "1"),
    ]
    assert budgets_of(_read({"module": {"used_today": {"PAY": "3"}}})) == []
    only_pay = budgets_of(_read({"module": {"mandate": mandate, "used_today": {"PAY": "3"}}}))
    assert [b.action for b in only_pay] == ["PAY"]


def test_queue_roles_follow_the_inbox_endpoints() -> None:
    assert queue_roles({"Approver"}) == (True, False)
    assert queue_roles({"Finance"}) == (False, True)
    assert queue_roles({"Auditor"}) == (False, False)
    assert queue_roles({"Owner"}) == (True, True)
