"""Property-based safety proofs for the single-request refill decision."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from hypothesis import example, given, seed, settings
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from treasurypilot_core.domain import (
    ApprovedRequest,
    Limits,
    PaymentTerms,
    PolicyView,
    RefillDecision,
    WalletState,
)
from treasurypilot_core.engine import decide_refill, preferred_refill, refill_bound
from treasurypilot_core.money import BaseUnits

PROPERTY_EXAMPLES = 1_000
_REPLAY_SEED = 20_261_012
_VERY_LARGE = 2**255


@dataclass(frozen=True)
class RefillCase:
    request: ApprovedRequest
    wallet: WalletState
    source: WalletState
    policy: PolicyView
    used_today: BaseUnits
    protected_other: BaseUnits

    def decide(self) -> RefillDecision:
        return decide_refill(
            self.request,
            self.wallet,
            self.source,
            self.policy,
            self.used_today,
            self.protected_other,
        )


def _money_values() -> SearchStrategy[BaseUnits]:
    """Cover ordinary amounts plus integer-only EVM-sized boundaries."""

    values = st.one_of(
        st.sampled_from((0, 1, 10**6, 10**18, 2**63 - 1, 2**128, _VERY_LARGE)),
        st.integers(min_value=0, max_value=10**30),
    )
    return values.map(BaseUnits)


@st.composite
def _wallet_states(
    draw: st.DrawFn,
    *,
    address: str,
    source_boundary: bool = False,
) -> WalletState:
    buffer = draw(_money_values())
    target_delta = draw(st.one_of(st.just(BaseUnits(0)), _money_values()))
    if source_boundary and draw(st.booleans()):
        balance = buffer
    else:
        balance = draw(_money_values())
    return WalletState(
        address=address,
        balance=balance,
        buffer=buffer,
        target=BaseUnits(buffer + target_delta),
    )


@st.composite
def _policies(draw: st.DrawFn) -> PolicyView:
    return PolicyView(
        pay=Limits(per_request=draw(_money_values()), daily=draw(_money_values())),
        refill=Limits(per_request=draw(_money_values()), daily=draw(_money_values())),
        cooling_seconds=draw(st.integers(min_value=0, max_value=2**31 - 1)),
    )


@st.composite
def _approved_requests(draw: st.DrawFn, *, paying_wallet: str) -> ApprovedRequest:
    return ApprovedRequest(
        id=f"request-{draw(st.integers(min_value=0, max_value=2**31 - 1))}",
        paying_wallet=paying_wallet,
        payee="0xpayee",
        amount=draw(_money_values()),
        approved_seq=draw(st.integers(min_value=0, max_value=2**31 - 1)),
        terms=PaymentTerms(net_due_day=draw(st.integers(min_value=0, max_value=2**31 - 1))),
        exception_granted=draw(st.booleans()),
    )


@st.composite
def _refill_cases(draw: st.DrawFn) -> RefillCase:
    wallet = draw(_wallet_states(address="0xoperational"))
    source = draw(_wallet_states(address="0xsource", source_boundary=True))
    policy = draw(_policies())
    request = draw(_approved_requests(paying_wallet=wallet.address))

    usage_kind = draw(st.sampled_from(("generated", "at_limit", "over_limit")))
    if usage_kind == "at_limit":
        used_today = policy.refill.daily
    elif usage_kind == "over_limit":
        used_today = BaseUnits(policy.refill.daily + draw(_money_values()) + 1)
    else:
        used_today = draw(_money_values())

    return RefillCase(
        request=request,
        wallet=wallet,
        source=source,
        policy=policy,
        used_today=used_today,
        protected_other=draw(_money_values()),
    )


def _case(
    *,
    balance: int,
    buffer: int,
    target: int,
    amount: int,
    protected_other: int,
    source_balance: int,
    source_buffer: int,
    per_request: int,
    daily: int,
    used_today: int,
) -> RefillCase:
    wallet = WalletState(
        address="0xoperational",
        balance=BaseUnits(balance),
        buffer=BaseUnits(buffer),
        target=BaseUnits(target),
    )
    return RefillCase(
        request=ApprovedRequest(
            id="boundary-request",
            paying_wallet=wallet.address,
            payee="0xpayee",
            amount=BaseUnits(amount),
            approved_seq=0,
            terms=PaymentTerms(net_due_day=0),
        ),
        wallet=wallet,
        source=WalletState(
            address="0xsource",
            balance=BaseUnits(source_balance),
            buffer=BaseUnits(source_buffer),
            target=BaseUnits(source_buffer),
        ),
        policy=PolicyView(
            pay=Limits(per_request=BaseUnits(0), daily=BaseUnits(0)),
            refill=Limits(per_request=BaseUnits(per_request), daily=BaseUnits(daily)),
            cooling_seconds=0,
        ),
        used_today=BaseUnits(used_today),
        protected_other=BaseUnits(protected_other),
    )


_ZERO_CASE = _case(
    balance=0,
    buffer=0,
    target=0,
    amount=0,
    protected_other=0,
    source_balance=0,
    source_buffer=0,
    per_request=0,
    daily=0,
    used_today=0,
)
_EXACT_LIMIT_CASE = _case(
    balance=100,
    buffer=10,
    target=50,
    amount=100,
    protected_other=0,
    source_balance=50,
    source_buffer=0,
    per_request=50,
    daily=60,
    used_today=10,
)
_EXHAUSTED_DAILY_CASE = _case(
    balance=0,
    buffer=10,
    target=10,
    amount=10,
    protected_other=0,
    source_balance=100,
    source_buffer=0,
    per_request=100,
    daily=100,
    used_today=100,
)
_OVERUSED_DAILY_SOURCE_AT_BUFFER_CASE = _case(
    balance=0,
    buffer=10,
    target=10,
    amount=10,
    protected_other=0,
    source_balance=25,
    source_buffer=25,
    per_request=100,
    daily=100,
    used_today=101,
)
_VERY_LARGE_CASE = _case(
    balance=_VERY_LARGE,
    buffer=_VERY_LARGE,
    target=_VERY_LARGE,
    amount=_VERY_LARGE,
    protected_other=0,
    source_balance=2 * _VERY_LARGE,
    source_buffer=_VERY_LARGE,
    per_request=_VERY_LARGE,
    daily=_VERY_LARGE,
    used_today=0,
)
_BOUND_REGRESSION_CASE = _case(
    balance=300,
    buffer=50,
    target=150,
    amount=400,
    protected_other=100,
    source_balance=10_000,
    source_buffer=0,
    per_request=10_000,
    daily=10_000,
    used_today=0,
)
_BOUNDARY_CASES = (
    _ZERO_CASE,
    _EXACT_LIMIT_CASE,
    _EXHAUSTED_DAILY_CASE,
    _OVERUSED_DAILY_SOURCE_AT_BUFFER_CASE,
    _VERY_LARGE_CASE,
)


def _with_boundary_examples(test: Callable[..., Any]) -> Callable[..., Any]:
    for boundary_case in _BOUNDARY_CASES:
        test = example(case=boundary_case)(test)
    return test


_property_settings = settings(
    max_examples=PROPERTY_EXAMPLES,
    deadline=None,
    database=None,
    derandomize=True,
)


@_property_settings
@_with_boundary_examples
@given(case=_refill_cases())
def test_allowed_refill_and_payment_preserve_operational_buffer(case: RefillCase) -> None:
    decision = case.decide()

    if decision.kind != "stop":
        post_payment = case.wallet.balance + decision.amount - case.request.amount
        assert post_payment >= case.wallet.buffer
        assert post_payment >= case.wallet.buffer + case.protected_other


@_property_settings
@_with_boundary_examples
@given(case=_refill_cases())
def test_refill_never_exceeds_available_cap(case: RefillCase) -> None:
    decision = case.decide()
    remaining_daily = max(0, case.policy.refill.daily - case.used_today)
    available_source = max(0, case.source.balance - case.source.buffer)

    assert decision.amount <= remaining_daily
    assert decision.amount <= available_source
    assert decision.amount <= case.policy.refill.per_request


@_property_settings
@_with_boundary_examples
@given(case=_refill_cases())
def test_refill_never_exceeds_contract_bound(case: RefillCase) -> None:
    decision = case.decide()

    assert decision.amount <= refill_bound(case.wallet, case.request.amount)


@_property_settings
@_with_boundary_examples
@given(case=_refill_cases())
def test_decision_amount_is_non_negative_base_units(case: RefillCase) -> None:
    decision = case.decide()

    assert type(decision.amount) is BaseUnits
    assert decision.amount >= 0


@_property_settings
@_with_boundary_examples
@given(case=_refill_cases())
def test_refill_decision_is_deterministic(case: RefillCase) -> None:
    first = case.decide()
    second = case.decide()

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def _buggy_refill_that_omits_contract_bound(case: RefillCase) -> BaseUnits:
    """Model the pre-M07-D4 defect so its counterexample remains replayable."""

    return preferred_refill(case.wallet, case.request.amount, case.protected_other)


@seed(_REPLAY_SEED)
@settings(max_examples=1, deadline=None, database=None)
@example(case=_BOUND_REGRESSION_CASE)
@given(case=_refill_cases())
def _buggy_bound_property(case: RefillCase) -> None:
    assert _buggy_refill_that_omits_contract_bound(case) <= refill_bound(
        case.wallet, case.request.amount
    ), "intentionally buggy refill breached bound"


def test_seeded_counterexample_replays_the_contract_bound_regression() -> None:
    with pytest.raises(AssertionError, match="intentionally buggy refill breached bound"):
        _buggy_bound_property()

    actual = _BOUND_REGRESSION_CASE.decide()
    assert actual.amount == BaseUnits(250)
    assert actual.amount <= refill_bound(
        _BOUND_REGRESSION_CASE.wallet,
        _BOUND_REGRESSION_CASE.request.amount,
    )
