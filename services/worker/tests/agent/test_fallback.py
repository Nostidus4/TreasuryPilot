from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from pydantic import BaseModel

from treasurypilot_core.eip712 import payment_approval_typed_data
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import (
    Action,
    ApprovalView,
    ChainSnapshot,
    FlagView,
    Limits,
    MandateView,
    PayeeView,
    PolicyState,
    RequestView,
    ValidationContext,
    validate_plan,
)
from treasurypilot_worker.agent import (
    AiAdapter,
    AiConfig,
    AiInputRejected,
    AiTask,
    AiTimeout,
    AiUnavailable,
    FakeClock,
    FakeProvider,
    FallbackPlan,
    FallbackRefusal,
    FallbackRefused,
    FallbackTemplate,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    PromptTemplate,
    ProviderRequest,
    ProviderResponse,
    plan_fallback,
)

NOW = 1_800_000_000
CHAIN = 11155111
TREASURY = "0x" + "11" * 20
SAFE_T = "0x" + "22" * 20
O1 = "0x" + "33" * 20
PAYEE = "0x" + "44" * 20
ASSET = "0x" + "55" * 20
EXECUTOR = "0x" + "66" * 20
APPROVER = Account.from_key("0x" + "7a" * 32)
MAKER, CHECKER = UUID(int=1), UUID(int=2)
OUTAGE = AiTimeout("provider timed out")


def _request(**update: Any) -> RequestView:
    fields = {
        "request_id": b"\x01" * 32,
        "status": "Approved",
        "invoice_hash": b"\x02" * 32,
        "fingerprint": b"\x03" * 32,
        "terms_hash": b"\x04" * 32,
        "paying_wallet": O1,
        "payee": PAYEE,
        "amount": BaseUnits(1_500),
        "fiat_amount_minor_units": None,
        "early_amount": BaseUnits(0),
        "early_pay_by": 0,
        "deadline": NOW + 86_400,
    }
    return RequestView.model_validate(fields | update)


def _approval(request: RequestView) -> ApprovalView:
    typed = {
        "requestId": "0x" + request.request_id.hex(),
        "invoiceHash": "0x" + request.invoice_hash.hex(),
        "fingerprint": "0x" + request.fingerprint.hex(),
        "treasury": TREASURY,
        "payingWallet": request.paying_wallet,
        "asset": ASSET,
        "payee": request.payee,
        "amount": request.amount,
        "earlyAmount": request.early_amount,
        "earlyPayBy": request.early_pay_by,
        "deadline": request.deadline,
        "termsHash": "0x" + request.terms_hash.hex(),
        "expiry": NOW + 14 * 86_400,
        "isFiat": request.fiat_amount_minor_units is not None,
    }
    full = payment_approval_typed_data(typed, chain_id=CHAIN, verifying_contract=TREASURY)
    return ApprovalView.model_validate(
        {
            "typed": typed,
            "signature": bytes(
                APPROVER.sign_message(encode_typed_data(full_message=full)).signature
            ),
            "signer": APPROVER.address,
            "approved_at": datetime.fromtimestamp(NOW - 3_600, UTC),
            "created_by": MAKER,
            "last_edited_by": MAKER,
            "approved_by_user": CHECKER,
            "acknowledged_flag_ids": [],
            "solo_mode": False,
        }
    )


def _state(**update: Any) -> PolicyState:
    fields = {
        "pay_limits": Limits(per_request=2_000, daily=10_000),
        "refill_limits": Limits(per_request=2_500, daily=12_000),
        "supply_limits": Limits(per_request=1_000, daily=10_000),
        "balances": {SAFE_T: BaseUnits(5_000), O1: BaseUnits(2_000)},
        "buffers": {SAFE_T: BaseUnits(1_000), O1: BaseUnits(10)},
        "targets": {O1: BaseUnits(150)},
        "used_today": {"PAY": BaseUnits(0), "REFILL": BaseUnits(0), "SUPPLY": BaseUnits(0)},
    }
    return PolicyState.model_validate(fields | update)


def _ctx(request: RequestView | None = None, **update: Any) -> ValidationContext:
    request = request or _request()
    snapshot = ChainSnapshot(
        chain_id=CHAIN,
        treasury=TREASURY,
        block_number=100,
        read_at=NOW - 5,
        safe_t=SAFE_T,
        asset=ASSET,
        mandate=MandateView(
            status="Active",
            version=1,
            valid_from=NOW - 86_400,
            expires_at=NOW + 86_400,
            executor=EXECUTOR,
        ),
        approvers=[APPROVER.address],
        payees={PAYEE: PayeeView(active=True, active_from=NOW - 600)},
        request_cancelled=False,
    )
    fields = {
        "now": NOW,
        "head_block": 101,
        "executor": EXECUTOR,
        "snapshot": snapshot,
        "request": request,
        "approval": _approval(request),
        "flags": [],
        "coverage": "COMPLETE",
        "unknown_operations": 0,
        "pause_requested": False,
        "circuit_open": False,
        "screening_hit": False,
        "screening_clear": True,
        "travel_rule_clear": True,
        "policy_state": _state(),
    }
    return ValidationContext.model_validate(fields | update)


def _fallback(ctx: ValidationContext, error: Exception = OUTAGE) -> FallbackPlan:
    result = plan_fallback(ctx, error)  # type: ignore[arg-type]
    assert isinstance(result, FallbackPlan), result
    return result


def _refusal(ctx: ValidationContext, error: Exception = OUTAGE) -> FallbackRefusal:
    result = plan_fallback(ctx, error)  # type: ignore[arg-type]
    assert isinstance(result, FallbackRefused), result
    return result.reason


def _actions(result: FallbackPlan) -> list[tuple[Action, int]]:
    return [(step.action, int(step.amount)) for step in result.plan.steps]


class _Plan(BaseModel):
    answer: str


def test_ai_timeout_with_complete_data_completes_via_a_pay_direct_template(
    repo_config: AiConfig, clock: FakeClock, october: datetime
) -> None:
    """AD-02: the plan task times out, the template plan is RULE_BASED and valid."""

    def slow(request: ProviderRequest, timeout_s: float) -> ProviderResponse:
        clock.advance(timeout_s + 0.001)
        raise AiTimeout("provider timed out")

    adapter = AiAdapter(
        provider=FakeProvider([slow]),
        config=repo_config,
        ledger=InMemoryBudgetLedger(),
        call_log=InMemoryAiCallLog(),
        clock=clock,
        sleep=clock.sleep,
        now=lambda: october,
    )
    prompt = PromptTemplate(version="plan.test.v1", system="Plan.", instructions="Go.").render()
    with pytest.raises(AiTimeout) as outage:
        adapter.run(AiTask.PLAN, org_id="org-1", prompt=prompt, output=_Plan)

    ctx = _ctx()
    result = _fallback(ctx, outage.value)

    assert result.template == FallbackTemplate.PAY_DIRECT
    assert _actions(result) == [(Action.PAY, 1_500)]
    assert result.plan.planner_source == "RULE_BASED"
    assert validate_plan(result.plan, ctx).decision == "ALLOW"


def test_refill_then_pay_tops_up_to_the_wallet_target() -> None:
    ctx = _ctx(policy_state=_state(balances={SAFE_T: BaseUnits(5_000), O1: BaseUnits(1_000)}))

    result = _fallback(ctx)

    assert result.template == FallbackTemplate.REFILL_THEN_PAY
    # amount 1,500 + target 150 - balance 1,000
    assert _actions(result) == [(Action.REFILL, 650), (Action.PAY, 1_500)]
    refill = result.plan.steps[0]
    assert (refill.from_wallet, refill.to) == (SAFE_T, O1)
    assert validate_plan(result.plan, ctx).decision == "ALLOW"


def test_refill_falls_back_to_the_shortage_when_the_target_is_out_of_reach() -> None:
    ctx = _ctx(
        policy_state=_state(
            balances={SAFE_T: BaseUnits(5_000), O1: BaseUnits(1_000)},
            refill_limits=Limits(per_request=600, daily=12_000),
        )
    )

    result = _fallback(ctx)

    # amount 1,500 + buffer 10 - balance 1,000
    assert _actions(result) == [(Action.REFILL, 510), (Action.PAY, 1_500)]
    assert validate_plan(result.plan, ctx).decision == "ALLOW"


def test_pays_the_early_amount_inside_the_early_window() -> None:
    request = _request(early_amount=BaseUnits(1_000), early_pay_by=NOW + 60)

    result = _fallback(_ctx(request))

    assert _actions(result) == [(Action.PAY, 1_000)]


def test_unknown_operation_blocks_every_fallback() -> None:
    """AD-03."""
    assert _refusal(_ctx(unknown_operations=1)) == FallbackRefusal.UNKNOWN_OPERATION


@pytest.mark.parametrize("alert", ["pause_requested", "circuit_open", "screening_hit"])
def test_safety_alerts_block_the_fallback(
    alert: Literal["pause_requested", "circuit_open", "screening_hit"],
) -> None:
    assert _refusal(_ctx().model_copy(update={alert: True})) == FallbackRefusal.SAFETY_ALERT


def test_a_high_flag_blocks_the_fallback_but_a_low_one_does_not() -> None:
    def flag(severity: Literal["LOW", "HIGH"]) -> FlagView:
        return FlagView(
            id=UUID(int=9), code="X", severity=severity, raised_at=datetime.fromtimestamp(NOW, UTC)
        )

    assert _refusal(_ctx(flags=[flag("HIGH")])) == FallbackRefusal.SAFETY_ALERT
    _fallback(_ctx(flags=[flag("LOW")]))


@pytest.mark.parametrize(
    "update",
    [
        {"coverage": "PARTIAL"},
        {"coverage": "PARTIAL_ACK"},
        {"policy_state": None},
        {"approval": None},
        {"request": None, "approval": None},
        {"screening_clear": False},
        {"travel_rule_clear": False},
    ],
)
def test_incomplete_data_blocks_the_fallback(update: dict[str, Any]) -> None:
    assert _refusal(_ctx(**update)) == FallbackRefusal.DATA_INCOMPLETE


def test_a_missing_wallet_balance_is_incomplete_data() -> None:
    ctx = _ctx(policy_state=_state(balances={SAFE_T: BaseUnits(5_000)}))

    assert _refusal(ctx) == FallbackRefusal.DATA_INCOMPLETE


def test_only_an_ai_outage_triggers_the_fallback() -> None:
    assert (
        _refusal(_ctx(), AiInputRejected(pattern="p", source="s")) == FallbackRefusal.NOT_AN_OUTAGE
    )
    _fallback(_ctx(), AiUnavailable("down", retryable=False))


@pytest.mark.parametrize(
    "state",
    [
        # the Safe cannot fund the refill without breaching its buffer
        {"balances": {SAFE_T: BaseUnits(1_100), O1: BaseUnits(1_000)}},
        # the payment itself exceeds the daily pay limit
        {"pay_limits": Limits(per_request=2_000, daily=1_000)},
    ],
)
def test_no_matching_template_is_refused(state: dict[str, Any]) -> None:
    assert _refusal(_ctx(policy_state=_state(**state))) == FallbackRefusal.NO_TEMPLATE
