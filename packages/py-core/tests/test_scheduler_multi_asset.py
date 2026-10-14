from __future__ import annotations

from collections import defaultdict

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.test_scheduler_oracle import _policy, _request, _snapshot
from treasurypilot_core.domain import ApprovedRequest, PaymentTerms
from treasurypilot_core.engine import AssetScheduleInput, schedule_cpsat_multi_asset
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


@settings(max_examples=40, deadline=None)
@given(
    amount=st.integers(min_value=1, max_value=10**8),
    cap=st.integers(min_value=1, max_value=10**8),
    other_amount=st.integers(min_value=1, max_value=10**8),
    other_cap=st.integers(min_value=1, max_value=10**8),
)
def test_property_each_asset_obeys_its_own_limits_and_uses_base_units(
    amount: int, cap: int, other_amount: int, other_cap: int
) -> None:
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

    policies = {"asset-a": cap, "asset-b": other_cap}
    requests = {"a": request_a, "b": request_b}
    daily_usage: dict[tuple[str, int], int] = defaultdict(int)
    for item in result.items:
        daily_usage[item.asset_id, item.day] += int(pay_amount(requests[item.request_id], item.day))
        assert isinstance(item.refill, BaseUnits)
        assert isinstance(item.refill, int)
    assert all(amount <= policies[asset_id] for (asset_id, _), amount in daily_usage.items())
    assert all(isinstance(item.refill, BaseUnits) for item in result.items)
