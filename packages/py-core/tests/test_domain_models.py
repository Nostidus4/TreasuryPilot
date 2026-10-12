from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from treasurypilot_core.domain import (
    ApprovedRequest,
    Asset,
    Infeasible,
    LateFee,
    Limits,
    PaymentTerms,
    PolicyView,
    RefillDecision,
    Schedule,
    ScheduledItem,
    Snapshot,
    WalletState,
)
from treasurypilot_core.money import BaseUnits


def wallet(address: str, balance: int = 1_000_000) -> WalletState:
    return WalletState(
        address=address,
        balance=BaseUnits(balance),
        buffer=BaseUnits(100_000),
        target=BaseUnits(250_000),
    )


def snapshot() -> Snapshot:
    return Snapshot(
        day=20_000,
        source=wallet("0xsource", 6_000_000_000),
        operational={"0xoperational": wallet("0xoperational")},
        used_today={"pay": BaseUnits(100), "refill": BaseUnits(200)},
        payee_active_day={"0xpayee": 19_999},
        safe_usdc=BaseUnits(6_000_000_000),
        a_usdc=BaseUnits(2_000_000_000),
        pool_available=BaseUnits(100_000_000_000),
        supply_rate_bps=450,
        borrow_rate_bps=725,
        health_factor=1_800_000_000_000_000_000,
        debt=BaseUnits(500_000_000),
    )


def test_every_financial_model_is_frozen() -> None:
    asset = Asset(
        chain_id=11_155_111,
        address="0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8",
        decimals=6,
        symbol="USDC",
        is_test=True,
    )

    with pytest.raises(ValidationError, match="frozen"):
        asset.symbol = "DAI"


def test_late_fee_requires_fields_for_its_discriminator() -> None:
    assert LateFee(kind="fixed", amount=BaseUnits(25)).amount == 25
    assert LateFee(kind="percent_per_period", rate_bps=150, period_days=7).period_days == 7

    with pytest.raises(ValidationError, match="requires amount"):
        LateFee(kind="fixed")
    with pytest.raises(ValidationError, match="requires rate_bps and period_days"):
        LateFee(kind="percent_per_period")


def test_payment_terms_validate_discount_window() -> None:
    terms = PaymentTerms(
        net_due_day=100,
        discount_bps=200,
        discount_deadline_day=80,
        priority_note="confirmed by finance",
    )

    assert terms.discount_bps == 200

    with pytest.raises(ValidationError, match="after the net due day"):
        PaymentTerms(net_due_day=100, discount_bps=200, discount_deadline_day=101)


def test_wallet_target_cannot_be_lower_than_buffer() -> None:
    with pytest.raises(ValidationError, match="minimum buffer"):
        WalletState(
            address="0xwallet",
            balance=BaseUnits(100),
            buffer=BaseUnits(20),
            target=BaseUnits(19),
        )


def test_snapshot_requires_separate_pay_and_refill_counters() -> None:
    data = snapshot().model_dump()
    data["used_today"] = {"pay": BaseUnits(0)}

    with pytest.raises(ValidationError, match="pay and refill"):
        Snapshot.model_validate(data)


def test_snapshot_requires_health_factor_only_when_debt_exists() -> None:
    data = snapshot().model_dump()
    data["health_factor"] = None

    with pytest.raises(ValidationError, match="when debt exists"):
        Snapshot.model_validate(data)

    data["debt"] = BaseUnits(0)
    without_debt = Snapshot.model_validate(data)
    assert without_debt.health_factor is None


def test_models_reject_float_amounts_instead_of_coercing() -> None:
    with pytest.raises(ValidationError):
        Limits(per_request=1.5, daily=BaseUnits(100))  # type: ignore[arg-type]


def test_snapshot_json_uses_strings_only_for_monetary_amounts() -> None:
    value = snapshot()

    payload = json.loads(value.model_dump_json())

    assert payload["source"]["balance"] == "6000000000"
    assert payload["operational"]["0xoperational"]["target"] == "250000"
    assert payload["used_today"] == {"pay": "100", "refill": "200"}
    assert payload["safe_usdc"] == "6000000000"
    assert payload["a_usdc"] == "2000000000"
    assert payload["pool_available"] == "100000000000"
    assert payload["debt"] == "500000000"
    assert payload["day"] == 20_000
    assert payload["supply_rate_bps"] == 450
    assert payload["borrow_rate_bps"] == 725
    assert payload["health_factor"] == 1_800_000_000_000_000_000


def test_model_json_round_trip_preserves_base_units_types() -> None:
    original = snapshot()

    restored = Snapshot.model_validate_json(original.model_dump_json())

    assert restored == original
    assert isinstance(restored.safe_usdc, BaseUnits)
    assert isinstance(restored.operational["0xoperational"].balance, BaseUnits)


def test_model_dict_round_trip_through_python_mode_validation() -> None:
    """Downstream consumers (FastAPI body parsing, Celery JSON args) validate a
    dict produced by ``mode="json"`` dumping, not raw JSON bytes. That path must
    accept the same canonical strings the wire format uses."""

    original = snapshot()

    via_json_loads = Snapshot.model_validate(json.loads(original.model_dump_json()))
    via_mode_json_dump = Snapshot.model_validate(original.model_dump(mode="json"))

    assert via_json_loads == original
    assert via_mode_json_dump == original
    assert isinstance(via_json_loads.safe_usdc, BaseUnits)
    assert isinstance(via_mode_json_dump.safe_usdc, BaseUnits)


def test_request_policy_refill_and_schedule_models_compose() -> None:
    terms = PaymentTerms(
        net_due_day=20_010,
        late_fee=LateFee(kind="fixed", amount=BaseUnits(25_000_000)),
    )
    request = ApprovedRequest(
        id="request-1",
        paying_wallet="0xoperational",
        payee="0xpayee",
        amount=BaseUnits(1_000_000_000),
        approved_seq=1,
        terms=terms,
    )
    policy = PolicyView(
        pay=Limits(per_request=BaseUnits(2_000_000_000), daily=BaseUnits(5_000_000_000)),
        refill=Limits(per_request=BaseUnits(2_000_000_000), daily=BaseUnits(5_000_000_000)),
        cooling_seconds=86_400,
    )
    decision = RefillDecision(
        kind="preferred", amount=BaseUnits(250_000_000), reason="TARGET_REACHED"
    )
    schedule = Schedule(
        items=[
            ScheduledItem(
                request_id=request.id,
                day=20_001,
                refill=decision.amount,
                value=20_000_000,
            )
        ],
        infeasible=[
            Infeasible(request_id="request-2", reason="NEEDS_EXCEPTION", detail="over cap")
        ],
        objective=(0, 0, -20_000_000, 2),
        binding=["daily_refill"],
        solver="EDF",
        status="FEASIBLE",
    )

    assert request.exception_granted is False
    assert policy.cooling_seconds == 86_400
    assert json.loads(schedule.model_dump_json())["items"][0]["refill"] == "250000000"


def test_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Limits(per_request=BaseUnits(1), daily=BaseUnits(2), weekly=BaseUnits(3))  # type: ignore[call-arg]
