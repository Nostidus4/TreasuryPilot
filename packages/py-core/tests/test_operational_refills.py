"""Refills funded by allowlisted operational wallets (ENG-L01, F-059)."""

from __future__ import annotations

import itertools

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from treasurypilot_core.domain import (
    ApprovedRequest,
    LateFee,
    Limits,
    PaymentTerms,
    PolicyView,
    Snapshot,
    WalletState,
)
from treasurypilot_core.engine import forecast, schedule_cpsat, schedule_edf
from treasurypilot_core.money import BaseUnits

SAFE = "0xsafe"
WALLETS = ("0xa", "0xb", "0xc")
BIG = 10**12


def _wallet(address: str, balance: int, buffer: int) -> WalletState:
    return WalletState(
        address=address,
        balance=BaseUnits(balance),
        buffer=BaseUnits(buffer),
        target=BaseUnits(buffer),
    )


def _snapshot(
    wallets: dict[str, tuple[int, int]],
    paths: tuple[tuple[str, str], ...],
    safe_balance: int = 0,
) -> Snapshot:
    return Snapshot(
        day=0,
        source=_wallet(SAFE, safe_balance, 0),
        operational={a: _wallet(a, bal, buf) for a, (bal, buf) in wallets.items()},
        used_today={"pay": BaseUnits(0), "refill": BaseUnits(0)},
        payee_active_day={"0xpayee": 0},
        safe_usdc=BaseUnits(safe_balance),
        a_usdc=BaseUnits(0),
        pool_available=BaseUnits(0),
        supply_rate_bps=0,
        borrow_rate_bps=0,
        debt=BaseUnits(0),
        refill_paths=paths,
    )


def _request(request_id: str, wallet: str, amount: int, seq: int = 0, due: int = 5, fee: int = 0):
    return ApprovedRequest(
        id=request_id,
        paying_wallet=wallet,
        payee="0xpayee",
        amount=BaseUnits(amount),
        approved_seq=seq,
        terms=PaymentTerms(
            net_due_day=due, late_fee=LateFee(kind="fixed", amount=BaseUnits(fee)) if fee else None
        ),
    )


POLICY = PolicyView(
    pay=Limits(per_request=BaseUnits(BIG), daily=BaseUnits(BIG)),
    refill=Limits(per_request=BaseUnits(BIG), daily=BaseUnits(BIG)),
    cooling_seconds=0,
)


def test_allowlisted_wallet_funds_a_short_wallet() -> None:
    snapshot = _snapshot({"0xa": (0, 0), "0xb": (500, 100)}, (("0xb", "0xa"),))
    schedule = schedule_edf([_request("r1", "0xa", 300)], snapshot, POLICY)
    (item,) = schedule.items
    assert (item.refill_from, int(item.refill)) == ("0xb", 300)


def test_safe_t_is_preferred_over_an_operational_source() -> None:
    snapshot = _snapshot({"0xa": (0, 0), "0xb": (500, 0)}, (("0xb", "0xa"),), safe_balance=1_000)
    (item,) = schedule_edf([_request("r1", "0xa", 300)], snapshot, POLICY).items
    assert item.refill_from is None


def test_no_path_means_no_operational_refill() -> None:
    snapshot = _snapshot({"0xa": (0, 0), "0xb": (500, 0)}, ())
    schedule = schedule_edf([_request("r1", "0xa", 300)], snapshot, POLICY)
    assert not schedule.items and schedule.infeasible[0].reason == "SOURCE_INSUFFICIENT"


def test_path_is_directional() -> None:
    snapshot = _snapshot({"0xa": (0, 0), "0xb": (500, 0)}, (("0xa", "0xb"),))
    assert not schedule_edf([_request("r1", "0xa", 300)], snapshot, POLICY).items


def test_source_keeps_buffer_and_its_own_obligations() -> None:
    # B holds 500, buffer 100 and owes 150: only 250 is surplus, so 300 cannot be lent.
    snapshot = _snapshot({"0xa": (0, 0), "0xb": (500, 100)}, (("0xb", "0xa"),))
    requests = [_request("a", "0xa", 300, due=1), _request("b", "0xb", 150, seq=1, due=9)]
    items = {i.request_id: i for i in schedule_edf(requests, snapshot, POLICY).items}
    assert "a" not in items and "b" in items


def test_obligation_is_released_once_the_source_has_paid() -> None:
    snapshot = _snapshot({"0xa": (0, 0), "0xb": (500, 100)}, (("0xb", "0xa"),))
    requests = [_request("b", "0xb", 150, due=1), _request("a", "0xa", 250, seq=1, due=2)]
    items = {i.request_id: i for i in schedule_edf(requests, snapshot, POLICY).items}
    assert items["a"].refill_from == "0xb" and int(items["a"].refill) == 250


def test_late_fee_of_the_lenders_own_payment_stays_reserved() -> None:
    # B owes 150 + a 50 late fee when its payment is late (due day -1 is already past), so
    # only 500 - 100 - 200 = 200 is lendable and A's 250 must not be funded from B.
    snapshot = _snapshot({"0xa": (0, 0), "0xb": (500, 100)}, (("0xb", "0xa"),))
    snapshot = snapshot.model_copy(update={"day": 3})
    requests = [_request("a", "0xa", 250, due=2), _request("b", "0xb", 150, seq=1, due=2, fee=50)]
    items = {i.request_id: i for i in schedule_edf(requests, snapshot, POLICY).items}
    # A is only funded once B has paid (which releases the reserve), never before it.
    assert items["b"].day == 3 and items["a"].day > items["b"].day


def test_late_fee_reserve_is_released_after_the_payment() -> None:
    snapshot = _snapshot({"0xa": (0, 0), "0xb": (500, 100)}, (("0xb", "0xa"),))
    requests = [
        _request("b", "0xb", 150, due=1, fee=50),
        _request("a", "0xa", 250, seq=1, due=2),
    ]
    items = {i.request_id: i for i in schedule_edf(requests, snapshot, POLICY).items}
    assert items["a"].refill_from == "0xb" and int(items["a"].refill) == 250


def test_refill_paths_that_do_not_apply_change_nothing() -> None:
    wallets = {"0xa": (100, 0), "0xb": (500, 0), "0xc": (0, 0)}
    requests = [_request("r1", "0xa", 300), _request("r2", "0xb", 100, seq=1)]
    plain = schedule_edf(requests, _snapshot(wallets, (), 1_000), POLICY)
    other = schedule_edf(requests, _snapshot(wallets, (("0xa", "0xc"),), 1_000), POLICY)
    assert plain == other
    assert [(i.request_id, int(i.refill), i.refill_from) for i in plain.items] == [
        ("r1", 200, None),
        ("r2", 0, None),
    ]


def test_forecast_maps_the_lender_key_to_its_address() -> None:
    def wallet(address: str, balance: int) -> WalletState:
        return _wallet(address, balance, 0)

    base = _snapshot({}, ())
    snapshot = base.model_copy(
        update={
            "operational": {"0xa": wallet("0xa", 0), "lender-b": wallet("0xb", 500)},
            "refill_paths": (("lender-b", "0xa"),),
        }
    )
    request = _request("r1", "0xa", 300)
    (refill,) = forecast(snapshot, [request], POLICY, days=7).days[0].suggested_refills
    assert (refill.source_wallet, refill.target_wallet) == ("0xb", "0xa")


def test_larger_surplus_is_tried_first() -> None:
    paths = (("0xb", "0xa"), ("0xc", "0xa"))
    snapshot = _snapshot({"0xa": (0, 0), "0xb": (400, 0), "0xc": (900, 0)}, paths)
    (item,) = schedule_edf([_request("r1", "0xa", 300)], snapshot, POLICY).items
    assert item.refill_from == "0xc"


def test_self_path_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _snapshot({"0xa": (0, 0)}, (("0xa", "0xa"),))


def test_cpsat_defers_to_edf_when_paths_exist() -> None:
    snapshot = _snapshot({"0xa": (0, 0), "0xb": (500, 0)}, (("0xb", "0xa"),))
    schedule = schedule_cpsat([_request("r1", "0xa", 300)], snapshot, POLICY)
    assert schedule.status == "FALLBACK" and schedule.items[0].refill_from == "0xb"


_PAIRS = list(itertools.permutations(WALLETS, 2))


@settings(max_examples=1_000, deadline=None)
@given(
    balances=st.lists(st.integers(0, 2_000), min_size=3, max_size=3),
    buffers=st.lists(st.integers(0, 500), min_size=3, max_size=3),
    safe_balance=st.integers(0, 1_000),
    paths=st.sets(st.sampled_from(_PAIRS)),
    amounts=st.lists(
        st.tuples(
            st.sampled_from(WALLETS), st.integers(1, 1_500), st.integers(0, 12), st.integers(0, 200)
        ),
        max_size=6,
    ),
)
def test_every_refill_leaves_its_source_funded(
    balances: list[int],
    buffers: list[int],
    safe_balance: int,
    paths: set[tuple[str, str]],
    amounts: list[tuple[str, int, int, int]],
) -> None:
    wallets = dict(zip(WALLETS, zip(balances, buffers, strict=True), strict=True))
    snapshot = _snapshot(wallets, tuple(sorted(paths)), safe_balance)
    requests = [
        _request(f"r{i}", w, amt, i, due, fee) for i, (w, amt, due, fee) in enumerate(amounts)
    ]
    by_id = {r.id: r for r in requests}
    schedule = schedule_edf(requests, snapshot, POLICY)

    balance = {a: bal for a, (bal, _buf) in wallets.items()}
    buffer = {a: buf for a, (_bal, buf) in wallets.items()}
    unpaid = {r.id for r in requests}
    for item in schedule.items:
        request = by_id[item.request_id]
        refill = int(item.refill)
        if item.refill_from is not None:
            source = item.refill_from
            assert refill > 0 and source != request.paying_wallet
            assert (source, request.paying_wallet) in paths
            balance[source] -= refill
            # Independent of the engine: every unpaid request of the lender, worst case
            # (a fixed late fee is the most it can add, whenever it is paid).
            owed = sum(
                amounts[int(i[1:])][1] + amounts[int(i[1:])][3]
                for i in unpaid
                if amounts[int(i[1:])][0] == source
            )
            assert balance[source] >= buffer[source] + owed
            balance[request.paying_wallet] += refill
        elif refill:
            balance[request.paying_wallet] += refill
        balance[request.paying_wallet] -= int(request.amount)
        assert balance[request.paying_wallet] >= buffer[request.paying_wallet]
        unpaid.discard(item.request_id)
    # Lending never costs the lender its own payments: whatever a lender pays without
    # any paths it still pays with them.
    lenders = {item.refill_from for item in schedule.items if item.refill_from}
    baseline = schedule_edf(requests, _snapshot(wallets, (), safe_balance), POLICY)
    paid = {item.request_id for item in schedule.items}
    for item in baseline.items:
        if by_id[item.request_id].paying_wallet in lenders:
            assert item.request_id in paid
