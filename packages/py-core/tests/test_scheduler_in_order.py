from tests.test_scheduler import obligation, policy, snapshot

from treasurypilot_core.engine import schedule_edf, schedule_in_order

REQS = [obligation("a", 100, due=1, seq=1), obligation("b", 100, due=2, seq=2)]


def test_edf_order_reproduces_edf_items() -> None:
    edf = schedule_edf(REQS, snapshot(), policy(pay_daily=100))
    assert schedule_in_order(["a", "b"], {}, REQS, snapshot(), policy(pay_daily=100)) == edf.items


def test_unnamed_requests_are_never_paid() -> None:
    items = schedule_in_order(["a"], {}, REQS, snapshot(), policy())
    assert [i.request_id for i in items] == ["a"]


def test_not_before_delays_payment() -> None:
    items = schedule_in_order(["a", "b"], {"a": 3}, REQS, snapshot(), policy())
    assert {i.request_id: i.day for i in items} == {"a": 3, "b": 0}


def test_caps_respected_when_order_is_reversed() -> None:
    pol = policy(pay_daily=100)
    items = schedule_in_order(["b", "a"], {}, REQS, snapshot(), pol)
    assert [(i.request_id, i.day) for i in items] == [("b", 0), ("a", 1)]
