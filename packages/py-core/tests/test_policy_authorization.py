from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

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
        "earlyAmount": 0,
        "earlyPayBy": 0,
        "deadline": NOW + 86_400,
        "termsHash": "0x" + request.terms_hash.hex(),
        "expiry": NOW + 14 * 86_400,
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
