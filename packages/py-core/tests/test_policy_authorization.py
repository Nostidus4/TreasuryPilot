from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from treasurypilot_core.eip712 import ERC1271_MAGIC_VALUE, payment_approval_typed_data
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import (
    Action,
    ApprovalView,
    ChainSnapshot,
    Check,
    ExecutionPlan,
    FlagView,
    MandateView,
    PayeeView,
    PlanStep,
    PolicyReasonCode,
    RequestView,
    ValidationContext,
    aggregate,
    authorization_checks,
)

C = PolicyReasonCode
NOW = 1_800_000_000
APPROVED_AT = datetime.fromtimestamp(NOW - 3_600, UTC)
CHAIN = 11155111
TREASURY = "0x" + "11" * 20
SAFE_T = "0x" + "22" * 20
O1 = "0x" + "33" * 20
PAYEE = "0x" + "44" * 20
ASSET = "0x" + "55" * 20
EXECUTOR = "0x" + "66" * 20
REQUEST_ID = b"\x01" * 32
MAKER, CHECKER = UUID(int=1), UUID(int=2)
APPROVER = Account.from_key("0x" + "7a" * 32)


def _request(**update: Any) -> RequestView:
    fields = {
        "request_id": REQUEST_ID,
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


def _typed(request: RequestView, **update: Any) -> dict[str, Any]:
    return {
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
    } | update


def _approval(typed: dict[str, Any], **update: Any) -> ApprovalView:
    full = payment_approval_typed_data(typed, chain_id=CHAIN, verifying_contract=TREASURY)
    signature = APPROVER.sign_message(encode_typed_data(full_message=full)).signature
    fields = {
        "typed": typed,
        "signature": bytes(signature),
        "signer": APPROVER.address,
        "approved_at": APPROVED_AT,
        "created_by": MAKER,
        "last_edited_by": MAKER,
        "approved_by_user": CHECKER,
        "acknowledged_flag_ids": [],
        "solo_mode": False,
    }
    return ApprovalView.model_validate(fields | update)


def _plan(refill: int | None = None, pay: int = 1_500) -> ExecutionPlan:
    steps = []
    if refill is not None:
        steps.append(
            PlanStep(
                seq=0,
                step_id=b"\x0a" * 32,
                action=Action.REFILL,
                from_wallet=SAFE_T,
                to=O1,
                asset=ASSET,
                amount=BaseUnits(refill),
            )
        )
    steps.append(
        PlanStep(
            seq=len(steps),
            step_id=b"\x0b" * 32,
            action=Action.PAY,
            from_wallet=O1,
            to=PAYEE,
            asset=ASSET,
            amount=BaseUnits(pay),
        )
    )
    return ExecutionPlan(
        request_id=REQUEST_ID,
        treasury=TREASURY,
        chain_id=CHAIN,
        steps=steps,
        planner_source="DETERMINISTIC",
        evidence_ids=["snapshot-1"],
    )


def _mandate(**update: Any) -> MandateView:
    fields = {
        "status": "Active",
        "version": 1,
        "valid_from": NOW - 86_400,
        "expires_at": NOW + 86_400,
        "executor": EXECUTOR,
    }
    return MandateView.model_validate(fields | update)


def _snapshot(**update: Any) -> ChainSnapshot:
    fields = {
        "chain_id": CHAIN,
        "treasury": TREASURY,
        "block_number": 100,
        "read_at": NOW - 5,
        "safe_t": SAFE_T,
        "asset": ASSET,
        "mandate": _mandate(),
        "approvers": [APPROVER.address],
        "payees": {PAYEE: PayeeView(active=True, active_from=NOW - 600)},
        "request_cancelled": False,
    }
    return ChainSnapshot.model_validate(fields | update)


def _ctx(**update: Any) -> ValidationContext:
    request = _request()
    fields = {
        "now": NOW,
        "head_block": 101,
        "executor": EXECUTOR,
        "snapshot": _snapshot(),
        "request": request,
        "approval": _approval(_typed(request)),
        "flags": [],
        "coverage": "COMPLETE",
        "unknown_operations": 0,
        "pause_requested": False,
        "circuit_open": False,
        "screening_hit": False,
        "screening_clear": True,
        "travel_rule_clear": True,
    }
    return ValidationContext.model_validate(fields | update)


def _failing(checks: list[Check]) -> list[PolicyReasonCode]:
    return [c.code for c in checks if c.code is not None]


def _skipped(checks: list[Check]) -> list[str]:
    return [c.name for c in checks if c.skipped]


def test_a_valid_plan_passes_every_check() -> None:
    checks = authorization_checks(_plan(refill=100), _ctx())

    assert all(c.passed for c in checks), _failing(checks)
    assert {"approval_signature", "payee_active", "plan_shape"} <= {c.name for c in checks}


def test_fiat_plan_may_execute_the_fresh_quote_amount_under_the_signed_cap() -> None:
    request = _request(fiat_amount_minor_units=12_000)
    checks = authorization_checks(
        _plan(pay=1_201), _ctx(request=request, approval=_approval(_typed(request)))
    )

    assert _failing(checks) == []


def test_fiat_plan_cannot_exceed_the_signed_stablecoin_cap() -> None:
    request = _request(fiat_amount_minor_units=12_000)
    checks = authorization_checks(
        _plan(pay=1_501), _ctx(request=request, approval=_approval(_typed(request)))
    )

    assert _failing(checks) == [C.PLAN_MALFORMED]


def test_a_non_fiat_plan_must_pay_the_signed_amount_exactly() -> None:
    checks = authorization_checks(_plan(pay=1_499), _ctx())

    assert _failing(checks) == [C.PLAN_MALFORMED]


def test_the_signed_fiat_flag_must_match_the_request() -> None:
    fiat = _request(fiat_amount_minor_units=12_000)
    for request, typed in (
        (fiat, _typed(fiat, isFiat=False)),
        (_request(), _typed(_request(), isFiat=True)),
    ):
        checks = authorization_checks(
            _plan(pay=request.amount), _ctx(request=request, approval=_approval(typed))
        )

        assert C.APPROVAL_STALE in {c.code for c in checks}


def test_a_request_view_must_state_whether_it_is_fiat() -> None:
    fields = _request().model_dump()
    del fields["fiat_amount_minor_units"]

    with pytest.raises(ValidationError):
        RequestView.model_validate(fields)


def _flag(raised_at: datetime, severity: Literal["LOW", "HIGH"] = "HIGH") -> FlagView:
    return FlagView(id=UUID(int=9), code="ADDRESS_CHANGED", severity=severity, raised_at=raised_at)


def _with_approval(**update: Any) -> ValidationContext:
    return _ctx(approval=_approval(_typed(_request()), **update))


# One context per reason code, each differing from the valid one in a single condition.
CASES: dict[PolicyReasonCode, Callable[[], ValidationContext]] = {
    C.PAUSE_REQUESTED: lambda: _ctx(pause_requested=True),
    C.CIRCUIT_OPEN: lambda: _ctx(circuit_open=True),
    C.UNKNOWN_OPERATION_PENDING: lambda: _ctx(unknown_operations=1),
    C.COVERAGE_INCOMPLETE: lambda: _ctx(coverage="PARTIAL"),
    C.SNAPSHOT_STALE: lambda: _ctx(snapshot=_snapshot(read_at=NOW - 31)),
    C.DATA_MISSING: lambda: _ctx(snapshot=_snapshot(mandate=None)),
    C.CHAIN_MISMATCH: lambda: _ctx(snapshot=_snapshot(chain_id=1)),
    C.ASSET_MISMATCH: lambda: _ctx(snapshot=_snapshot(asset="0x" + "99" * 20)),
    C.REQUEST_CANCELLED: lambda: _ctx(snapshot=_snapshot(request_cancelled=True)),
    C.NOT_APPROVED: lambda: _ctx(approval=None),
    C.SCREENING_HIT: lambda: _ctx(screening_hit=True),
    C.MANDATE_PAUSED: lambda: _ctx(snapshot=_snapshot(mandate=_mandate(status="Paused"))),
    C.MANDATE_REVOKED: lambda: _ctx(snapshot=_snapshot(mandate=_mandate(status="Revoked"))),
    C.MANDATE_NOT_ACTIVE: lambda: _ctx(snapshot=_snapshot(mandate=_mandate(valid_from=NOW + 1))),
    C.MANDATE_EXPIRED: lambda: _ctx(snapshot=_snapshot(mandate=_mandate(expires_at=NOW - 1))),
    C.EXECUTOR_MISMATCH: lambda: _ctx(executor="0x" + "77" * 20),
    C.APPROVAL_STALE: lambda: _ctx(request=_request(terms_hash=b"\x05" * 32)),
    C.APPROVAL_INVALID: lambda: _with_approval(signature=b"\x00" * 65),
    C.NOT_IN_APPROVER_SET: lambda: _ctx(snapshot=_snapshot(approvers=["0x" + "88" * 20])),
    C.APPROVAL_EXPIRED: lambda: _ctx(approval=_approval(_typed(_request(), expiry=NOW - 1))),
    C.MAKER_CHECKER: lambda: _with_approval(last_edited_by=CHECKER),
    C.FLAG_UNACKNOWLEDGED: lambda: _ctx(flags=[_flag(APPROVED_AT - timedelta(hours=1))]),
    C.PAYEE_UNKNOWN: lambda: _ctx(snapshot=_snapshot(payees={})),
    C.PAYEE_COOLING: lambda: _ctx(
        snapshot=_snapshot(payees={PAYEE: PayeeView(active=True, active_from=NOW + 1)})
    ),
}


@pytest.mark.parametrize("code", CASES, ids=str)
def test_each_failed_condition_returns_its_own_code(code: PolicyReasonCode) -> None:
    checks = authorization_checks(_plan(), CASES[code]())

    assert _failing(checks) == [code]


@pytest.mark.parametrize(
    "plan",
    [
        _plan(pay=1_400),  # amount differs from the approved request
        _plan(refill=100).model_copy(update={"steps": list(reversed(_plan(refill=100).steps))}),
        _plan().model_copy(update={"steps": [*_plan().steps, *_plan().steps]}),
        _plan().model_copy(update={"request_id": b"\x09" * 32}),
        _plan(refill=100).model_copy(
            update={
                "steps": [
                    _plan(refill=100).steps[0].model_copy(update={"to": PAYEE}),
                    _plan().steps[0].model_copy(update={"seq": 1}),
                ]
            }
        ),
    ],
    ids=["amount", "order", "two-pays", "request", "refill-target"],
)
def test_a_malformed_plan_is_plan_malformed(plan: ExecutionPlan) -> None:
    assert C.PLAN_MALFORMED in _failing(authorization_checks(plan, _ctx()))


def test_cancelled_request_is_reported_once_as_request_cancelled() -> None:
    checks = authorization_checks(_plan(), _ctx(request=_request(status="Cancelled")))

    assert _failing(checks) == [C.REQUEST_CANCELLED]


def test_a_draft_request_is_not_approved() -> None:
    assert _failing(authorization_checks(_plan(), _ctx(request=_request(status="Draft")))) == [
        C.NOT_APPROVED
    ]


@pytest.mark.parametrize(
    "update",
    [{"head_block": 103}, {"head_block": 99}, {"snapshot": _snapshot(read_at=NOW + 1)}],
    ids=["blocks-behind", "head-behind-snapshot", "read-in-future"],
)
def test_snapshot_freshness_edges_are_stale(update: dict[str, Any]) -> None:
    assert _failing(authorization_checks(_plan(), _ctx(**update))) == [C.SNAPSHOT_STALE]


def test_a_deactivated_payee_is_reported_once_as_unknown() -> None:
    payees = {PAYEE: PayeeView(active=False, active_from=NOW + 600)}

    assert _failing(authorization_checks(_plan(), _ctx(snapshot=_snapshot(payees=payees)))) == [
        C.PAYEE_UNKNOWN
    ]


def test_a_failed_gate_skips_every_step_check() -> None:
    checks = authorization_checks(_plan(), _ctx(pause_requested=True, approval=None))

    ran = [c for c in checks if not c.skipped]
    assert [c.code for c in ran if not c.passed] == [C.PAUSE_REQUESTED]
    assert [c.name for c in ran][-1] == "asset_match"  # only the gates ran
    assert {"request_not_cancelled", "approval_signature", "payee_active"} <= set(_skipped(checks))


def test_a_missing_approval_skips_only_the_approval_checks() -> None:
    checks = authorization_checks(_plan(), _ctx(approval=None))

    assert _failing(checks) == [C.NOT_APPROVED]
    assert set(_skipped(checks)) == {
        "approval_matches_request",
        "approval_signature",
        "approver_in_current_set",
        "approval_not_expired",
        "maker_checker",
        "flags_acknowledged",
    }


def test_high_flags_need_acknowledgment_before_approval() -> None:
    before, after = APPROVED_AT - timedelta(hours=1), APPROVED_AT + timedelta(seconds=1)
    acked = _with_approval(acknowledged_flag_ids=[UUID(int=9)])

    def codes(ctx: ValidationContext) -> list[PolicyReasonCode]:
        return _failing(authorization_checks(_plan(), ctx))

    assert codes(acked.model_copy(update={"flags": [_flag(before)]})) == []
    # Raised after the approval: acknowledgment cannot cover it, re-approval is needed.
    assert codes(acked.model_copy(update={"flags": [_flag(after)]})) == [C.FLAG_UNACKNOWLEDGED]
    assert codes(_ctx(flags=[_flag(after, severity="LOW")])) == []


def test_solo_mode_allows_the_maker_to_approve() -> None:
    ctx = _with_approval(last_edited_by=CHECKER, created_by=CHECKER, solo_mode=True)

    assert _failing(authorization_checks(_plan(), ctx)) == []


def test_contract_signer_uses_erc1271() -> None:
    ctx = _with_approval(signature=b"\x01")

    def wallet(answer: bytes) -> Callable[[str, bytes, bytes], bytes]:
        return lambda signer, digest, signature: answer + bytes(28)

    assert _failing(authorization_checks(_plan(), ctx, erc1271=wallet(ERC1271_MAGIC_VALUE))) == []
    assert _failing(authorization_checks(_plan(), ctx, erc1271=wallet(b"\x00" * 4))) == [
        C.APPROVAL_INVALID
    ]


def test_pre_step_checks_only_that_step() -> None:
    plan = _plan(refill=100)
    ctx = _ctx(snapshot=_snapshot(payees={}))

    refill = authorization_checks(plan, ctx, seq=0)
    pay = authorization_checks(plan, ctx, seq=1)

    assert _failing(refill) == [] and "plan_shape" not in {c.name for c in refill}
    assert _failing(pay) == [C.PAYEE_UNKNOWN]


@pytest.mark.parametrize(
    ("ctx", "codes", "skips_steps"),
    [
        # Row 7: snapshot read 45 s ago.
        (lambda: _ctx(snapshot=_snapshot(read_at=NOW - 45)), [C.SNAPSHOT_STALE], True),
        # Row 8: another operation Unknown.
        (lambda: _ctx(unknown_operations=1), [C.UNKNOWN_OPERATION_PENDING], True),
        # Row 11: HIGH "address differs from history" flag not acknowledged.
        (
            lambda: _ctx(flags=[_flag(APPROVED_AT - timedelta(minutes=5))]),
            [C.FLAG_UNACKNOWLEDGED],
            False,
        ),
    ],
    ids=["row-7", "row-8", "row-11"],
)
def test_worked_examples_8_5(
    ctx: Callable[[], ValidationContext], codes: list[PolicyReasonCode], skips_steps: bool
) -> None:
    checks = authorization_checks(_plan(), ctx())

    assert _failing(checks) == codes
    assert aggregate(codes) == ("BLOCK", codes[0])
    assert bool(_skipped(checks)) is skips_steps


@pytest.mark.parametrize(
    "update",
    [{"early_amount": BaseUnits(1_400)}, {"early_pay_by": NOW}, {"deadline": NOW + 1}],
    ids=["early-amount", "early-pay-by", "deadline"],
)
def test_changed_early_terms_make_the_approval_stale(update: dict[str, Any]) -> None:
    assert _failing(authorization_checks(_plan(), _ctx(request=_request(**update)))) == [
        C.APPROVAL_STALE
    ]


EARLY = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "contracts"
        / "test"
        / "vectors"
        / "payment-approval-early.json"
    ).read_text()
)


def _early_ctx(now: int) -> tuple[ValidationContext, Callable[[int], ExecutionPlan]]:
    """The signed two-option approval from the contract vectors (ADR-019)."""
    m = EARLY["message"]
    request = _request(
        request_id=bytes.fromhex(m["requestId"][2:]),
        invoice_hash=bytes.fromhex(m["invoiceHash"][2:]),
        fingerprint=bytes.fromhex(m["fingerprint"][2:]),
        terms_hash=bytes.fromhex(m["termsHash"][2:]),
        paying_wallet=m["payingWallet"],
        payee=m["payee"],
        amount=BaseUnits(int(m["amount"])),
        early_amount=BaseUnits(int(m["earlyAmount"])),
        early_pay_by=m["earlyPayBy"],
        deadline=m["deadline"],
    )
    approval = _approval(
        m,
        signature=bytes.fromhex(EARLY["signature"][2:]),
        signer=EARLY["signer"],
    )
    snapshot = _snapshot(
        chain_id=EARLY["domain"]["chainId"],
        treasury=m["treasury"],
        asset=m["asset"],
        read_at=now - 5,
        approvers=[EARLY["signer"]],
        payees={m["payee"]: PayeeView(active=True, active_from=0)},
        mandate=_mandate(valid_from=0),
    )
    ctx = _ctx(now=now, snapshot=snapshot, request=request, approval=approval)

    def plan(pay: int) -> ExecutionPlan:
        step = PlanStep(
            seq=0,
            step_id=b"\x0b" * 32,
            action=Action.PAY,
            from_wallet=m["payingWallet"],
            to=m["payee"],
            asset=m["asset"],
            amount=BaseUnits(pay),
        )
        return _plan().model_copy(
            update={
                "request_id": request.request_id,
                "treasury": m["treasury"],
                "chain_id": EARLY["domain"]["chainId"],
                "steps": [step],
            }
        )

    return ctx, plan


def test_two_option_approval_pays_the_early_amount_until_early_pay_by() -> None:
    pay_by = EARLY["message"]["earlyPayBy"]
    early, standard = int(EARLY["message"]["earlyAmount"]), int(EARLY["message"]["amount"])

    ctx, plan = _early_ctx(now=pay_by)
    assert _failing(authorization_checks(plan(early), ctx)) == []
    assert _failing(authorization_checks(plan(standard), ctx)) == [C.PLAN_MALFORMED]

    ctx, plan = _early_ctx(now=pay_by + 1)
    assert _failing(authorization_checks(plan(standard), ctx)) == []
    assert _failing(authorization_checks(plan(early), ctx)) == [C.PLAN_MALFORMED]


def _withdraw_plan(to: str = SAFE_T) -> ExecutionPlan:
    refill, pay = _plan(refill=100).steps
    withdraw = PlanStep(
        seq=0,
        step_id=b"\x0c" * 32,
        action=Action.WITHDRAW,
        from_wallet="0x" + "aa" * 20,  # lending pool
        to=to,
        asset=ASSET,
        amount=BaseUnits(60),
    )
    steps = [withdraw, refill.model_copy(update={"seq": 1}), pay.model_copy(update={"seq": 2})]
    return _plan().model_copy(update={"steps": steps})


def test_withdraw_before_refill_is_a_valid_plan() -> None:
    assert _failing(authorization_checks(_withdraw_plan(), _ctx())) == []
    assert C.PLAN_MALFORMED in _failing(authorization_checks(_withdraw_plan(to=O1), _ctx()))
    # A WITHDRAW without the REFILL it funds is not a planner shape.
    no_refill = _withdraw_plan().model_copy(
        update={
            "steps": [_withdraw_plan().steps[0], _plan().steps[0].model_copy(update={"seq": 1})]
        }
    )
    assert C.PLAN_MALFORMED in _failing(authorization_checks(no_refill, _ctx()))


def test_an_unknown_step_seq_is_plan_malformed() -> None:
    assert _failing(authorization_checks(_plan(), _ctx(), seq=7)) == [C.PLAN_MALFORMED]


def test_unparseable_input_fails_with_data_missing() -> None:
    naive = _ctx(flags=[_flag(datetime(2026, 1, 1))])  # noqa: DTZ001 - the bad input under test
    signed = _approval(_typed(_request()))
    bad_amount = _ctx(approval=signed.model_copy(update={"typed": {**signed.typed, "amount": "x"}}))

    assert _failing(authorization_checks(_plan(), naive)) == [C.DATA_MISSING]
    assert C.DATA_MISSING in _failing(authorization_checks(_plan(), bad_amount))


def test_screening_provider_error_fails_with_data_missing() -> None:
    assert _failing(authorization_checks(_plan(), _ctx(screening_clear=False))) == [C.DATA_MISSING]


def test_missing_travel_rule_preflight_blocks_pay() -> None:
    checks = authorization_checks(_plan(), _ctx(travel_rule_clear=False))

    assert _failing(checks) == [C.DATA_MISSING]
    assert next(check for check in checks if check.name == "travel_rule_clear").passed is False


def test_unevaluated_travel_rule_preflight_does_not_block_pay() -> None:
    assert _failing(authorization_checks(_plan(), _ctx(travel_rule_clear=None))) == []


def test_screening_hit_reports_only_screening_hit() -> None:
    ctx = _ctx(screening_hit=True, screening_clear=False)
    assert _failing(authorization_checks(_plan(), ctx)) == [C.SCREENING_HIT]


def _policy_state(**update: Any):
    from treasurypilot_core.policy import Limits, PolicyState

    fields = {
        "pay_limits": Limits(per_request=2_000, daily=10_000),
        "refill_limits": Limits(per_request=2_500, daily=12_000),
        "supply_limits": Limits(per_request=1_000, daily=10_000),
        "balances": {SAFE_T.lower(): BaseUnits(5_000), O1.lower(): BaseUnits(1_600)},
        "buffers": {SAFE_T.lower(): BaseUnits(1_000), O1.lower(): BaseUnits(10)},
        "targets": {O1.lower(): BaseUnits(150)},
        "used_today": {"PAY": BaseUnits(0), "REFILL": BaseUnits(0), "SUPPLY": BaseUnits(0)},
        "available_for_supply": BaseUnits(2_000),
        "payment_reserve": BaseUnits(500),
    }
    return PolicyState.model_validate(fields | update)


def test_validate_plan_projects_refill_before_pay() -> None:
    from treasurypilot_core.policy import validate_plan

    ctx = _ctx(
        policy_state=_policy_state(
            balances={SAFE_T.lower(): BaseUnits(5_000), O1.lower(): BaseUnits(1_500)}
        )
    )
    result = validate_plan(_plan(refill=100), ctx)
    assert result.decision == "ALLOW", result.codes
    assert result.stage == "PLAN"


def test_validate_plan_fails_closed_without_policy_state() -> None:
    from treasurypilot_core.policy import validate_plan

    result = validate_plan(_plan(), _ctx())
    assert result.decision == "BLOCK"
    assert C.DATA_MISSING in result.codes


def test_valid_exception_only_lifts_per_request_limit() -> None:
    from treasurypilot_core.policy import ExceptionView, validate_plan

    state = _policy_state(
        pay_limits={"per_request": 1_000, "daily": 10_000},
        exception=ExceptionView(
            amount=BaseUnits(1_500), payee=PAYEE, expiry=NOW + 1, mandate_version=1, used=False
        ),
    )
    result = validate_plan(_plan(), _ctx(policy_state=state))
    assert result.decision == "ALLOW", result.codes
    assert C.OVER_PER_REQUEST_LIMIT not in result.codes


def _fiat_ctx(**state: Any) -> ValidationContext:
    request = _request(fiat_amount_minor_units=12_000)
    return _ctx(
        request=request,
        approval=_approval(_typed(request)),
        policy_state=_policy_state(**state),
    )


def test_validator_allows_a_fiat_payment_below_the_signed_cap() -> None:
    from treasurypilot_core.policy import validate_plan

    result = validate_plan(_plan(pay=1_201), _fiat_ctx())

    assert result.decision == "ALLOW", result.codes
    assert C.WRONG_PAYMENT_OPTION not in result.codes


@pytest.mark.parametrize("pay", [0, 1_501])
def test_validator_rejects_a_fiat_payment_outside_zero_to_cap(pay: int) -> None:
    from treasurypilot_core.policy import validate_plan

    result = validate_plan(_plan(pay=pay), _fiat_ctx())

    assert result.decision == "BLOCK"
    assert C.WRONG_PAYMENT_OPTION in result.codes


def test_validator_rejects_a_non_fiat_payment_below_the_signed_amount() -> None:
    from treasurypilot_core.policy import validate_plan

    result = validate_plan(_plan(pay=1_499), _ctx(policy_state=_policy_state()))

    assert result.decision == "BLOCK"
    assert C.WRONG_PAYMENT_OPTION in result.codes


def test_fiat_exception_matches_the_signed_amount_not_the_quoted_amount() -> None:
    from treasurypilot_core.policy import validate_plan

    limits = {"pay_limits": {"per_request": 1_000, "daily": 10_000}}
    granted = validate_plan(_plan(pay=1_201), _fiat_ctx(exception=_exception(1_500), **limits))
    quoted = validate_plan(_plan(pay=1_201), _fiat_ctx(exception=_exception(1_201), **limits))

    assert granted.decision == "ALLOW", granted.codes
    assert C.EXCEPTION_INVALID in quoted.codes


def test_supply_cannot_reduce_payment_reserve() -> None:
    from treasurypilot_core.policy import Action, PlanStep, validate_step

    plan = _plan().model_copy(
        update={
            "steps": [
                PlanStep(
                    seq=0,
                    step_id=b"\x0c" * 32,
                    action=Action.SUPPLY,
                    from_wallet=SAFE_T,
                    to=SAFE_T,
                    asset=ASSET,
                    amount=BaseUnits(4_600),
                )
            ]
        }
    )
    state = _policy_state(balances={SAFE_T.lower(): BaseUnits(5_000), O1.lower(): BaseUnits(1_500)})
    result = validate_step(plan, 0, _ctx(policy_state=state))
    assert C.RESERVE_BREACH in result.codes


def test_late_payment_is_allowed_with_deadline_warning() -> None:
    from treasurypilot_core.policy import validate_plan

    request = _request(deadline=NOW - 1)
    approval = _approval(_typed(request))
    result = validate_plan(
        _plan(), _ctx(request=request, approval=approval, policy_state=_policy_state())
    )
    assert result.decision == "ALLOW"
    assert result.warnings == [C.DEADLINE_MISSED]


def test_invalid_exception_does_not_mask_daily_limit_failure() -> None:
    from treasurypilot_core.policy import ExceptionView, validate_plan

    state = _policy_state(
        pay_limits={"per_request": 1_000, "daily": 1_000},
        used_today={"PAY": BaseUnits(1), "REFILL": BaseUnits(0), "SUPPLY": BaseUnits(0)},
        exception=ExceptionView(
            amount=BaseUnits(9_999), payee=PAYEE, expiry=NOW - 1, mandate_version=0, used=True
        ),
    )
    result = validate_plan(_plan(), _ctx(policy_state=state))
    assert C.EXCEPTION_INVALID in result.codes
    assert C.OVER_DAILY_LIMIT in result.codes
    assert result.decision == "BLOCK"


def _liquidity_plan(action: Action = Action.SUPPLY, from_wallet: str = SAFE_T) -> ExecutionPlan:
    step = PlanStep(
        seq=0,
        step_id=b"\x0d" * 32,
        action=action,
        from_wallet=from_wallet,
        to=SAFE_T,
        asset=ASSET,
        amount=BaseUnits(100),
    )
    return _plan().model_copy(update={"steps": [step]})


def test_liquidity_plans_keep_mandate_executor_and_screening_checks() -> None:
    for action in (Action.SUPPLY, Action.WITHDRAW):
        plan = _liquidity_plan(action)
        assert _failing(authorization_checks(plan, _ctx(request=None, approval=None))) == []
        assert (
            _failing(
                authorization_checks(
                    plan, _ctx(request=None, approval=None, travel_rule_clear=False)
                )
            )
            == []
        )
        bad = {
            C.MANDATE_REVOKED: {"snapshot": _snapshot(mandate=_mandate(status="Revoked"))},
            C.MANDATE_PAUSED: {"snapshot": _snapshot(mandate=_mandate(status="Paused"))},
            C.MANDATE_EXPIRED: {"snapshot": _snapshot(mandate=_mandate(expires_at=NOW - 1))},
            C.MANDATE_NOT_ACTIVE: {"snapshot": _snapshot(mandate=_mandate(valid_from=NOW + 1))},
            C.EXECUTOR_MISMATCH: {"executor": "0x" + "77" * 20},
            C.SCREENING_HIT: {"screening_hit": True},
        }
        for code, update in bad.items():
            ctx = _ctx(request=None, approval=None, **update)
            assert _failing(authorization_checks(plan, ctx)) == [code], (action, code)


def test_liquidity_plan_without_mandate_is_data_missing() -> None:
    ctx = _ctx(request=None, approval=None, snapshot=_snapshot(mandate=None))
    assert C.DATA_MISSING in _failing(authorization_checks(_liquidity_plan(), ctx))


def test_supply_must_spend_from_safe_t_and_step_ids_are_unique() -> None:
    ctx = _ctx(request=None, approval=None)
    wrong_source = _liquidity_plan(from_wallet="0x" + "aa" * 20)
    assert _failing(authorization_checks(wrong_source, ctx)) == [C.PLAN_MALFORMED]
    # WITHDRAW comes from the pool, so its source is not pinned to Safe T.
    pool_withdraw = _liquidity_plan(Action.WITHDRAW, "0x" + "aa" * 20)
    assert _failing(authorization_checks(pool_withdraw, ctx)) == []
    supply, withdraw = _liquidity_plan().steps[0], _liquidity_plan(Action.WITHDRAW).steps[0]
    dup = _plan().model_copy(update={"steps": [supply, withdraw.model_copy(update={"seq": 1})]})
    assert _failing(authorization_checks(dup, ctx)) == [C.PLAN_MALFORMED]


def test_withdraw_step_of_a_request_plan_keeps_request_and_mandate_checks() -> None:
    from treasurypilot_core.policy import validate_step

    plan = _withdraw_plan()
    cases = {
        C.MANDATE_REVOKED: _ctx(snapshot=_snapshot(mandate=_mandate(status="Revoked"))),
        C.REQUEST_CANCELLED: _ctx(snapshot=_snapshot(request_cancelled=True)),
        C.APPROVAL_EXPIRED: _ctx(approval=_approval(_typed(_request(), expiry=NOW - 1))),
        C.NOT_APPROVED: _ctx(approval=None),
        C.DATA_MISSING: _ctx(request=None),
    }
    for code, ctx in cases.items():
        assert code in _failing(authorization_checks(plan, ctx, seq=0)), code

    state = _policy_state(a_token_balance=BaseUnits(1_000), pool_liquidity=BaseUnits(1_000))
    revoked = _ctx(snapshot=_snapshot(mandate=_mandate(status="Revoked")), policy_state=state)
    result = validate_step(plan, 0, revoked)
    assert result.decision == "BLOCK"
    assert C.MANDATE_REVOKED in result.codes
    cancelled = _ctx(snapshot=_snapshot(request_cancelled=True), policy_state=state)
    assert C.REQUEST_CANCELLED in validate_step(plan, 0, cancelled).codes


def test_stale_exception_is_ignored_while_within_the_per_request_limit() -> None:
    from treasurypilot_core.policy import ExceptionView, validate_plan

    state = _policy_state(
        exception=ExceptionView(
            amount=BaseUnits(9_999), payee=PAYEE, expiry=NOW - 1, mandate_version=0, used=True
        )
    )
    result = validate_plan(_plan(), _ctx(policy_state=state))
    assert result.decision == "ALLOW", result.codes


def test_validate_step_and_plan_agree_on_late_pay_but_not_for_liquidity() -> None:
    from treasurypilot_core.policy import validate_plan, validate_step

    request = _request(deadline=NOW - 1)
    ctx = _ctx(request=request, approval=_approval(_typed(request)), policy_state=_policy_state())
    assert validate_step(_plan(), 0, ctx).warnings == [C.DEADLINE_MISSED]
    assert validate_plan(_plan(), ctx).warnings == [C.DEADLINE_MISSED]

    liquidity = _ctx(request=request, approval=None, policy_state=_policy_state())
    assert validate_plan(_liquidity_plan(), liquidity).warnings == []


def test_liquidity_figures_are_projected_across_steps() -> None:
    from treasurypilot_core.policy import validate_plan

    withdraw = _liquidity_plan(Action.WITHDRAW).steps[0]
    again = withdraw.model_copy(update={"seq": 1, "step_id": b"\x0e" * 32})
    twice = _plan().model_copy(update={"steps": [withdraw, again]})
    state = _policy_state(a_token_balance=BaseUnits(150), pool_liquidity=BaseUnits(150))
    result = validate_plan(twice, _ctx(request=None, approval=None, policy_state=state))
    assert C.INSUFFICIENT_A_TOKEN in result.codes
    assert C.INSUFFICIENT_POOL_LIQUIDITY in result.codes


def test_malformed_policy_state_fails_closed() -> None:
    from treasurypilot_core.policy import validate_plan

    state = _policy_state().model_copy(update={"balances": {SAFE_T.lower(): "x"}})
    result = validate_plan(_plan(), _ctx(policy_state=state))
    assert result.decision == "BLOCK"
    assert C.DATA_MISSING in result.codes


def _pay_case(amount: int, *, exception: Any = None, cooling: bool = False, **state: Any):
    """Context and plan for a PAY of ``amount`` (the request and its approval carry the same)."""
    request = _request(amount=BaseUnits(amount))
    payees = {PAYEE: PayeeView(active=True, active_from=NOW + 1 if cooling else NOW - 600)}
    ctx = _ctx(
        request=request,
        approval=_approval(_typed(request)),
        snapshot=_snapshot(payees=payees),
        policy_state=_policy_state(
            balances={SAFE_T.lower(): BaseUnits(5_000), O1.lower(): BaseUnits(20_000)},
            exception=exception,
            **state,
        ),
    )
    return _plan(pay=amount), ctx


def _used(pay: int) -> dict[str, BaseUnits]:
    return {"PAY": BaseUnits(pay), "REFILL": BaseUnits(0), "SUPPLY": BaseUnits(0)}


def _exception(amount: int = 3_000, **update: Any):
    from treasurypilot_core.policy import ExceptionView

    fields = {"amount": BaseUnits(amount), "payee": PAYEE, "expiry": NOW + 1, "mandate_version": 1}
    return ExceptionView.model_validate(fields | update)


@pytest.mark.parametrize(
    ("amount", "kwargs", "decision", "primary", "codes"),
    [
        (1_500, {"used_today": _used(3_000)}, "ALLOW", None, []),  # row 1
        (3_000, {"used_today": _used(2_000)}, "NEEDS_APPROVAL", C.OVER_PER_REQUEST_LIMIT, None),
        (  # row 3
            3_000,
            {"used_today": _used(8_000)},
            "BLOCK",
            C.OVER_DAILY_LIMIT,
            [C.OVER_DAILY_LIMIT, C.OVER_PER_REQUEST_LIMIT],
        ),
        (3_000, {"exception": _exception()}, "ALLOW", None, []),  # row 4
        (  # row 5
            3_000,
            {"exception": _exception(2_900)},
            "BLOCK",
            C.EXCEPTION_INVALID,
            [C.EXCEPTION_INVALID, C.OVER_PER_REQUEST_LIMIT],
        ),
        (  # row 6
            3_000,
            {"cooling": True},
            "BLOCK",
            C.PAYEE_COOLING,
            [C.PAYEE_COOLING, C.OVER_PER_REQUEST_LIMIT],
        ),
    ],
    ids=["row-1", "row-2", "row-3", "row-4", "row-5", "row-6"],
)
def test_worked_examples_8_5_limits(
    amount: int,
    kwargs: dict[str, Any],
    decision: str,
    primary: PolicyReasonCode | None,
    codes: list[PolicyReasonCode] | None,
) -> None:
    from treasurypilot_core.policy import validate_plan, validate_step

    plan, ctx = _pay_case(amount, **kwargs)
    for result in (validate_plan(plan, ctx), validate_step(plan, 0, ctx)):
        assert (result.decision, result.primary) == (decision, primary)
        assert sorted(result.codes) == sorted(codes if codes is not None else [primary])


def test_worked_example_8_5_row_10_refill_then_owner_moves_funds() -> None:
    from treasurypilot_core.policy import validate_plan, validate_step

    request = _request(amount=BaseUnits(100))
    plan = _plan(refill=90, pay=100)
    balances = {SAFE_T.lower(): BaseUnits(5_000), O1.lower(): BaseUnits(20)}
    ctx = _ctx(
        request=request,
        approval=_approval(_typed(request)),
        policy_state=_policy_state(balances=balances),
    )
    assert validate_plan(plan, ctx).decision == "ALLOW"  # 20 + 90 - 100 = buffer 10
    # The owner moved 50 out after the refill: PAY is checked against the fresh 60.
    moved = ctx.model_copy(
        update={"policy_state": _policy_state(balances=balances | {O1.lower(): BaseUnits(60)})}
    )
    result = validate_step(plan, 1, moved)
    assert (result.decision, result.primary) == ("BLOCK", C.BUFFER_BREACH)


def test_a_failed_gate_skips_the_limit_checks_of_validate_plan() -> None:
    from treasurypilot_core.policy import validate_plan, validate_step

    # Row 7: the over-limit PAY is not reported because the stale snapshot cannot be trusted.
    plan, ctx = _pay_case(3_000, used_today=_used(8_000))
    ctx = ctx.model_copy(update={"snapshot": _snapshot(read_at=NOW - 45)})
    for result in (validate_plan(plan, ctx), validate_step(plan, 0, ctx)):
        assert result.codes == [C.SNAPSHOT_STALE]
        assert result.decision == "BLOCK"
        assert any(c.name == "policy_state" and c.skipped for c in result.checks)


def test_gate_failures_and_unknown_operations_block_before_any_step_check() -> None:
    from treasurypilot_core.policy import validate_plan

    plan, ctx = _pay_case(1_500)
    for update, code in [
        ({"unknown_operations": 2}, C.UNKNOWN_OPERATION_PENDING),
        ({"coverage": "PARTIAL"}, C.COVERAGE_INCOMPLETE),
        ({"coverage": "PARTIAL_ACK"}, None),
    ]:
        result = validate_plan(plan, ctx.model_copy(update=update))
        assert (result.decision, result.primary) == (
            ("BLOCK", code) if code else ("ALLOW", None)
        ), update


def _mutations() -> dict[str, dict[str, Any]]:
    """Dropping or staling one input of the valid PAY context; each must never ALLOW."""
    return {
        "no_state": {"policy_state": None},
        "no_request": {"request": None},
        "no_approval": {"approval": None},
        "no_mandate": {"snapshot": _snapshot(mandate=None)},
        "stale_age": {"snapshot": _snapshot(read_at=NOW - 31)},
        "future_snapshot": {"snapshot": _snapshot(read_at=NOW + 5)},
        "stale_blocks": {"head_block": 200},
        "unknown_operations": {"unknown_operations": 1},
        "partial_coverage": {"coverage": "PARTIAL"},
        "screening_unknown": {"screening_clear": False},
        "bad_state": {"policy_state": _policy_state().model_copy(update={"balances": {"x": "y"}})},
        "empty_balances": {"policy_state": _policy_state(balances={})},
        "empty_buffers": {"policy_state": _policy_state(buffers={})},
        "no_payee": {"snapshot": _snapshot(payees={})},
        "no_approvers": {"snapshot": _snapshot(approvers=[])},
    }


@pytest.mark.parametrize("name", list(_mutations()))
@pytest.mark.parametrize("kind", ["plan", "step"])
def test_missing_or_stale_input_never_yields_allow(name: str, kind: str) -> None:
    from treasurypilot_core.policy import validate_plan, validate_step

    ctx = _ctx(policy_state=_policy_state()).model_copy(update=_mutations()[name])
    result = validate_plan(_plan(), ctx) if kind == "plan" else validate_step(_plan(), 0, ctx)
    assert result.decision == "BLOCK", name
    assert result.codes


def test_the_unmodified_context_is_allowed() -> None:
    from treasurypilot_core.policy import validate_plan

    assert validate_plan(_plan(), _ctx(policy_state=_policy_state())).decision == "ALLOW"


@settings(max_examples=200, deadline=None)
@given(
    amount=st.integers(1, 6_000),
    used=st.integers(0, 12_000),
    cooling=st.booleans(),
    exc_amount=st.integers(1, 6_000),
    exc_used=st.booleans(),
    exc_expired=st.booleans(),
    has_exception=st.booleans(),
)
def test_an_exception_removes_only_the_per_request_limit(
    amount: int,
    used: int,
    cooling: bool,
    exc_amount: int,
    exc_used: bool,
    exc_expired: bool,
    has_exception: bool,
) -> None:
    from treasurypilot_core.policy import validate_plan

    exception = (
        _exception(exc_amount, used=exc_used, expiry=NOW - 1 if exc_expired else NOW + 1)
        if has_exception
        else None
    )
    plan, ctx = _pay_case(amount, exception=exception, cooling=cooling, used_today=_used(used))
    result = validate_plan(plan, ctx)
    valid = has_exception and exc_amount == amount and not exc_used and not exc_expired
    over = amount > 2_000
    hard = cooling or used + amount > 10_000 or (has_exception and over and not valid)

    assert (C.OVER_PER_REQUEST_LIMIT in result.codes) == (over and not valid)
    assert (C.EXCEPTION_INVALID in result.codes) == (has_exception and over and not valid)
    assert (C.PAYEE_COOLING in result.codes) == cooling
    assert (C.OVER_DAILY_LIMIT in result.codes) == (used + amount > 10_000)
    expected = "BLOCK" if hard else "NEEDS_APPROVAL" if over and not valid else "ALLOW"
    assert result.decision == expected


def _swap_step(**update: Any) -> PlanStep:
    fields: dict[str, Any] = {
        "seq": 0,
        "step_id": b"\x0c" * 32,
        "action": Action.SWAP,
        "from_wallet": SAFE_T,
        "to": "0x" + "99" * 20,
        "asset": ASSET,
        "amount": BaseUnits(700),
        "min_out": BaseUnits(1_000),
        "venue": "TEST_ROUTER",
    }
    return PlanStep(**(fields | update))


def _with_swap(swap: PlanStep) -> ExecutionPlan:
    base = _plan(refill=100)
    shifted = [s.model_copy(update={"seq": s.seq + 1}) for s in base.steps]
    return base.model_copy(update={"steps": [swap, *shifted]})


def test_a_leading_swap_for_gas_is_a_well_formed_plan() -> None:
    checks = authorization_checks(_with_swap(_swap_step()), _ctx())

    assert _failing(checks) == []


@pytest.mark.parametrize(
    "update",
    [
        {"min_out": None},
        {"min_out": BaseUnits(0)},
        {"venue": None},
        {"from_wallet": O1},
    ],
)
def test_a_malformed_swap_step_is_rejected(update: dict[str, Any]) -> None:
    checks = authorization_checks(_with_swap(_swap_step(**update)), _ctx())

    assert _failing(checks) == [C.PLAN_MALFORMED]


def test_a_swap_after_the_payment_is_rejected() -> None:
    base = _plan()
    plan = base.model_copy(update={"steps": [*base.steps, _swap_step(seq=1)]})

    assert _failing(authorization_checks(plan, _ctx())) == [C.PLAN_MALFORMED]


def test_validate_plan_projects_the_swap_out_of_safe_t_before_refill() -> None:
    from treasurypilot_core.policy import validate_plan

    plan = _with_swap(_swap_step())
    rich = _ctx(
        policy_state=_policy_state(
            balances={SAFE_T.lower(): BaseUnits(5_000), O1.lower(): BaseUnits(1_500)}
        )
    )
    assert validate_plan(plan, rich).decision == "ALLOW"

    # 700 swapped + 100 refilled leaves 90 < the 100 buffer: the swap cannot hide a breach.
    poor = _ctx(
        policy_state=_policy_state(
            balances={SAFE_T.lower(): BaseUnits(890), O1.lower(): BaseUnits(1_500)},
            buffers={SAFE_T.lower(): BaseUnits(100)},
        )
    )
    result = validate_plan(plan, poor)
    assert result.decision == "BLOCK" and C.SOURCE_BUFFER_BREACH in result.codes
