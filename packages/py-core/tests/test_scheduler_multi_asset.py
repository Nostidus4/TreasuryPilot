from __future__ import annotations

from collections import defaultdict

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.test_scheduler_oracle import _policy, _request, _snapshot
from treasurypilot_core.domain import ApprovedRequest, PaymentTerms
from treasurypilot_core.engine import AssetScheduleInput, multi_asset, schedule_cpsat_multi_asset
from treasurypilot_core.engine.payment_terms import pay_amount
from treasurypilot_core.money import BaseUnits


def test_assets_keep_balances_and_daily_caps_independent() -> None:
    low_cap_requests = [
        ApprovedRequest(
            id=f"low-{index}",
            paying_wallet="ops",
            payee="payee",
            amount=BaseUnits(60),
            approved_seq=index,
            terms=PaymentTerms(net_due_day=0),
        )
        for index in range(2)
    ]
    high_cap_requests = [
        ApprovedRequest(
            id=f"high-{index}",
            paying_wallet="ops",
            payee="payee",
            amount=BaseUnits(60),
            approved_seq=index,
            terms=PaymentTerms(net_due_day=0),
        )
        for index in range(2)
    ]

    result = schedule_cpsat_multi_asset(
        {
            "usd-coin": AssetScheduleInput(
                low_cap_requests,
                _snapshot(ops_balance=120),
                _policy(pay_daily=60),
                objective_value_scale=1,
            ),
            "euro-coin": AssetScheduleInput(
                high_cap_requests,
                _snapshot(ops_balance=120),
                _policy(pay_daily=120),
                objective_value_scale=1,
            ),
        }
    )

    by_asset_day: dict[tuple[str, int], int] = defaultdict(int)
    requests = {request.id: request for request in low_cap_requests + high_cap_requests}
    for item in result.items:
        by_asset_day[item.asset_id, item.day] += int(
            pay_amount(requests[item.request_id], item.day)
        )
        assert isinstance(item.refill, BaseUnits)
    assert (
        max(amount for (asset_id, _), amount in by_asset_day.items() if asset_id == "usd-coin")
        == 60
    )
    assert by_asset_day["euro-coin", 0] == 120
    assert len({item.asset_id for item in result.items}) == 2
    assert result.objective == (0, 1, 0, 3)


def test_request_ids_must_be_unique_across_assets() -> None:
    request = _request("same-id", seq=0, early_amount=80, early_pay_by=0)
    asset = AssetScheduleInput(
        [request], _snapshot(ops_balance=100), _policy(), objective_value_scale=1
    )

    with pytest.raises(ValueError, match="unique across all assets"):
        schedule_cpsat_multi_asset({"asset-a": asset, "asset-b": asset})


def test_objective_values_are_scaled_to_a_common_integer_unit() -> None:
    request_a = _request("a", seq=0, early_amount=80, early_pay_by=0)
    request_b = _request("b", seq=0, early_amount=90, early_pay_by=0)
    result = schedule_cpsat_multi_asset(
        {
            "six-decimal": AssetScheduleInput(
                [request_a],
                _snapshot(ops_balance=100),
                _policy(),
                objective_value_scale=10,
            ),
            "eighteen-decimal": AssetScheduleInput(
                [request_b],
                _snapshot(ops_balance=100),
                _policy(),
                objective_value_scale=20,
            ),
        }
    )

    assert result.objective == (0, 0, -400, 2)


def test_empty_assets_return_an_empty_optimal_schedule() -> None:
    result = schedule_cpsat_multi_asset({})

    assert result.items == ()
    assert result.infeasible == ()
    assert result.objective == (0, 0, 0, 0)
    assert result.status == "OPTIMAL"


def test_exhausted_asset_does_not_block_another_schedulable_asset() -> None:
    empty = AssetScheduleInput(
        [_request("a", seq=0, early_amount=80, early_pay_by=0)],
        _snapshot(ops_balance=0),
        _policy(),
        objective_value_scale=1,
    )
    funded = AssetScheduleInput(
        [_request("b", seq=0, early_amount=80, early_pay_by=0)],
        _snapshot(ops_balance=100),
        _policy(),
        objective_value_scale=1,
    )

    result = schedule_cpsat_multi_asset({"asset-a": empty, "asset-b": funded})

    assert [(item.asset_id, item.request_id) for item in result.items] == [("asset-b", "b")]
    assert [(item.asset_id, item.request_id) for item in result.infeasible] == [("asset-a", "a")]


@pytest.mark.parametrize("bad_id", ["", "  ", " usdc", "usdc "])
def test_asset_ids_must_be_non_empty_and_trimmed(bad_id: str) -> None:
    asset = AssetScheduleInput(
        [_request("a", seq=0, early_amount=80, early_pay_by=0)],
        _snapshot(ops_balance=100),
        _policy(),
        objective_value_scale=1,
    )

    with pytest.raises(ValueError, match="asset ids"):
        schedule_cpsat_multi_asset({"usdc": asset, bad_id: asset})


def test_invalid_input_is_rejected_before_any_asset_is_solved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object) -> None:
        raise AssertionError("solver must not run before validation completes")

    monkeypatch.setattr(multi_asset, "schedule_cpsat", fail)
    asset = AssetScheduleInput(
        [_request("a", seq=0, early_amount=80, early_pay_by=0)],
        _snapshot(ops_balance=100),
        _policy(),
        objective_value_scale=1,
    )

    with pytest.raises(ValueError, match="unique across all assets"):
        schedule_cpsat_multi_asset({"asset-a": asset, "asset-b": asset})


def test_merged_solver_reports_edf_when_any_asset_fell_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = multi_asset.schedule_cpsat

    def fake(requests, snapshot, policy):  # type: ignore[no-untyped-def]
        result = real(requests, snapshot, policy)
        if requests[0].id == "b":
            return result.model_copy(update={"solver": "EDF", "status": "FALLBACK"})
        return result

    monkeypatch.setattr(multi_asset, "schedule_cpsat", fake)
    inputs = {
        name: AssetScheduleInput(
            [_request(name, seq=0, early_amount=80, early_pay_by=0)],
            _snapshot(ops_balance=100),
            _policy(),
            objective_value_scale=1,
        )
        for name in ("a", "b")
    }

    result = schedule_cpsat_multi_asset(inputs)

    assert result.solver == "EDF"
    assert result.status == "FALLBACK"


@settings(max_examples=40, deadline=None)
@given(
    amount=st.integers(min_value=1, max_value=10**8),
    cap_extra=st.integers(min_value=0, max_value=10**8),
    other_amount=st.integers(min_value=1, max_value=10**8),
    other_cap_extra=st.integers(min_value=0, max_value=10**8),
)
def test_property_each_asset_obeys_its_own_limits_and_uses_base_units(
    amount: int, cap_extra: int, other_amount: int, other_cap_extra: int
) -> None:
    cap = amount + cap_extra
    other_cap = other_amount + other_cap_extra
    request_a = ApprovedRequest(
        id="a",
        paying_wallet="ops",
        payee="payee",
        amount=BaseUnits(amount),
        approved_seq=0,
        terms=PaymentTerms(net_due_day=2),
        early_amount=BaseUnits(amount),
        early_pay_by=0,
    )
    request_b = ApprovedRequest(
        id="b",
        paying_wallet="ops",
        payee="payee",
        amount=BaseUnits(other_amount),
        approved_seq=0,
        terms=PaymentTerms(net_due_day=2),
        early_amount=BaseUnits(other_amount),
        early_pay_by=0,
    )
    assets = {
        "asset-a": AssetScheduleInput(
            [request_a],
            _snapshot(ops_balance=amount),
            _policy(pay_daily=cap, pay_per_request=cap),
            objective_value_scale=1,
        ),
        "asset-b": AssetScheduleInput(
            [request_b],
            _snapshot(ops_balance=other_amount),
            _policy(pay_daily=other_cap, pay_per_request=other_cap),
            objective_value_scale=1,
        ),
    }

    result = schedule_cpsat_multi_asset(assets)

    caps = {"asset-a": cap, "asset-b": other_cap}
    balances = {"asset-a": amount, "asset-b": other_amount}
    requests = {"a": request_a, "b": request_b}
    daily_usage: dict[tuple[str, int], int] = defaultdict(int)
    for item in result.items:
        daily_usage[item.asset_id, item.day] += int(pay_amount(requests[item.request_id], item.day))
        assert isinstance(item.refill, BaseUnits)
    # Each request fits its own asset's cap and balance, so both must be scheduled.
    assert {item.asset_id for item in result.items} == set(assets)
    assert all(amount <= caps[asset_id] for (asset_id, _), amount in daily_usage.items())
    totals: dict[str, int] = defaultdict(int)
    for (asset_id, _), used in daily_usage.items():
        totals[asset_id] += used
    assert all(total <= balances[asset_id] for asset_id, total in totals.items())
