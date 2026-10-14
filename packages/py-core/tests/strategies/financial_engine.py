"""Small, bounded financial-engine inputs shared by solver property tests."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.strategies import DrawFn

from treasurypilot_core.domain import (
    ApprovedRequest,
    Limits,
    PaymentTerms,
    PolicyView,
    Snapshot,
    WalletState,
)
from treasurypilot_core.money import BaseUnits

type SchedulerScenario = tuple[list[ApprovedRequest], Snapshot, PolicyView]


@st.composite
def small_scheduler_scenarios(
    draw: DrawFn,
    *,
    max_requests: int = 8,
    max_due_offset: int = 4,
) -> SchedulerScenario:
    """Generate an instance within the exhaustive solver's N≤8, H≤5 bounds."""

    request_count = draw(st.integers(min_value=1, max_value=max_requests))
    payee_names = ("payee-0", "payee-1")
    payees = {
        name: draw(st.integers(min_value=0, max_value=max_due_offset)) for name in payee_names
    }
    requests: list[ApprovedRequest] = []
    for index in range(request_count):
        due = draw(st.integers(min_value=0, max_value=max_due_offset))
        amount = draw(st.integers(min_value=1, max_value=200))
        has_early_option = draw(st.booleans())
        early_amount = (
            draw(st.integers(min_value=1, max_value=amount)) if has_early_option else None
        )
        early_pay_by = draw(st.integers(min_value=0, max_value=due)) if has_early_option else None
        requests.append(
            ApprovedRequest(
                id=f"request-{index}",
                paying_wallet="ops",
                payee=draw(st.sampled_from((*payee_names, "unknown-payee"))),
                amount=BaseUnits(amount),
                approved_seq=draw(st.integers(min_value=0, max_value=request_count - 1)),
                terms=PaymentTerms(net_due_day=due),
                early_amount=None if early_amount is None else BaseUnits(early_amount),
                early_pay_by=early_pay_by,
                exception_granted=draw(st.booleans()),
            )
        )

    ops_buffer = draw(st.integers(min_value=0, max_value=30))
    source_buffer = draw(st.integers(min_value=0, max_value=30))
    source_balance = draw(st.integers(min_value=0, max_value=600))
    snapshot = Snapshot(
        day=0,
        source=WalletState(
            address="safe",
            balance=BaseUnits(source_balance),
            buffer=BaseUnits(source_buffer),
            target=BaseUnits(source_buffer),
        ),
        operational={
            "ops": WalletState(
                address="ops",
                balance=BaseUnits(draw(st.integers(min_value=0, max_value=300))),
                buffer=BaseUnits(ops_buffer),
                target=BaseUnits(ops_buffer + draw(st.integers(min_value=0, max_value=100))),
            )
        },
        used_today={
            "pay": BaseUnits(draw(st.integers(min_value=0, max_value=100))),
            "refill": BaseUnits(draw(st.integers(min_value=0, max_value=100))),
        },
        payee_active_day=payees,
        safe_usdc=BaseUnits(source_balance),
        a_usdc=BaseUnits(0),
        pool_available=BaseUnits(0),
        supply_rate_bps=draw(st.integers(min_value=0, max_value=500)),
        borrow_rate_bps=0,
        debt=BaseUnits(0),
    )
    policy = PolicyView(
        pay=Limits(
            per_request=BaseUnits(draw(st.integers(min_value=1, max_value=250))),
            daily=BaseUnits(draw(st.integers(min_value=1, max_value=300))),
        ),
        refill=Limits(
            per_request=BaseUnits(draw(st.integers(min_value=0, max_value=300))),
            daily=BaseUnits(draw(st.integers(min_value=0, max_value=400))),
        ),
        cooling_seconds=0,
    )
    return requests, snapshot, policy
