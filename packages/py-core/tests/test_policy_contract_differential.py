from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from treasurypilot_core.eip712 import payment_approval_typed_data
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import (
    Action,
    ApprovalView,
    ChainSnapshot,
    ExceptionView,
    ExecutionPlan,
    Limits,
    MandateView,
    PayeeView,
    PlanStep,
    PolicyReasonCode,
    PolicyState,
    RequestView,
    ValidationContext,
    decode_revert,
    error_selector,
    validate_step,
)

NOW = 1_800_000_000
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
MATRIX_PATH = (
    Path(__file__).resolve().parents[3] / "contracts/test/vectors/policy_contract_differential.json"
)
CONTRACT_TEST = (
    Path(__file__).resolve().parents[3]
    / "contracts/test/scenarios/PolicyContractDifferential.t.sol"
)
CASES: dict[str, dict[str, Any]] = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
UNKNOWN_PAYEE = "0x" + "00" * 18 + "abcd"


def _request(*, amount: int, payee: str) -> RequestView:
    return RequestView.model_validate(
        {
            "request_id": REQUEST_ID,
            "status": "Approved",
            "invoice_hash": b"\x02" * 32,
            "fingerprint": b"\x03" * 32,
            "terms_hash": b"\x04" * 32,
            "paying_wallet": O1,
            "payee": payee,
            "amount": BaseUnits(amount),
            "early_amount": BaseUnits(0),
            "early_pay_by": 0,
            "deadline": NOW + 86_400,
        }
    )


def _approval(request: RequestView, expiry: int) -> ApprovalView:
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
        "expiry": expiry,
    }
    full = payment_approval_typed_data(typed, chain_id=CHAIN, verifying_contract=TREASURY)
    signature = APPROVER.sign_message(encode_typed_data(full_message=full)).signature
    return ApprovalView.model_validate(
        {
            "typed": typed,
            "signature": bytes(signature),
            "signer": APPROVER.address,
            "approved_at": datetime.fromtimestamp(NOW - 3600, UTC),
            "created_by": MAKER,
            "last_edited_by": MAKER,
            "approved_by_user": CHECKER,
            "acknowledged_flag_ids": [],
            "solo_mode": False,
        }
    )


def _mandate(status: str) -> MandateView:
    return MandateView.model_validate(
        {
            "status": status,
            "version": 1,
            "valid_from": NOW - 86_400,
            "expires_at": NOW + 86_400,
            "executor": EXECUTOR,
        }
    )


def _plan(amount: int, *, refill: int | None = None, payee: str = PAYEE) -> ExecutionPlan:
    steps: list[PlanStep] = []
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
            to=payee,
            asset=ASSET,
            amount=BaseUnits(amount),
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


def _context_and_plan(case_id: str) -> tuple[Any, Any, int]:
    amount = 1500 * 10**6
    payee = PAYEE
    active_from = NOW - 600
    mandate_status = "Active"
    approval_expiry = NOW + 14 * 86_400
    used_today = 0
    fingerprint_paid = False
    duplicate_allowed = False
    exception = None
    refill = None
    if case_id == "cap_exact":
        amount = 2000 * 10**6
    elif case_id == "cap_plus_one":
        amount = 2000 * 10**6 + 1
    elif case_id == "daily_limit":
        amount = 11 * 10**6
        used_today = 9990 * 10**6
    elif case_id == "unknown_payee":
        payee = UNKNOWN_PAYEE
    elif case_id == "cooling_before_edge":
        active_from = NOW + 1
    elif case_id == "cooling_at_edge":
        active_from = NOW
    elif case_id == "mandate_paused":
        mandate_status = "Paused"
    elif case_id == "approval_expired":
        approval_expiry = NOW - 1
    elif case_id == "refill_bound":
        amount = 100 * 10**6
        refill = 1 * 10**6
    elif case_id in {"valid_exception", "invalid_exception"}:
        amount = 2500 * 10**6
        exception_amount = amount if case_id == "valid_exception" else amount - 1
        exception = ExceptionView(
            amount=BaseUnits(exception_amount),
            payee=payee,
            expiry=NOW + 100,
            mandate_version=1,
        )
    elif case_id in {"duplicate_blocked", "duplicate_allowed"}:
        amount = 1 * 10**6
        fingerprint_paid = True
        duplicate_allowed = case_id == "duplicate_allowed"

    request = _request(amount=amount, payee=payee)
    approval = _approval(request, expiry=approval_expiry)
    snapshot = ChainSnapshot.model_validate(
        {
            "chain_id": CHAIN,
            "treasury": TREASURY,
            "block_number": 100,
            "read_at": NOW - 5,
            "safe_t": SAFE_T,
            "asset": ASSET,
            "mandate": _mandate(mandate_status),
            "approvers": [APPROVER.address],
            "payees": (
                {payee.lower(): PayeeView(active=True, active_from=active_from)}
                if case_id != "unknown_payee"
                else {}
            ),
            "request_cancelled": False,
        }
    )
    state = PolicyState(
        pay_limits=Limits(per_request=2000 * 10**6, daily=10000 * 10**6),
        refill_limits=Limits(per_request=2500 * 10**6, daily=12000 * 10**6),
        supply_limits=Limits(per_request=5000 * 10**6, daily=20000 * 10**6),
        balances={O1.lower(): BaseUnits(10000 * 10**6), SAFE_T.lower(): BaseUnits(30000 * 10**6)},
        buffers={O1.lower(): BaseUnits(10 * 10**6), SAFE_T.lower(): BaseUnits(1000 * 10**6)},
        targets={O1.lower(): BaseUnits(150 * 10**6)},
        used_today={"PAY": BaseUnits(used_today)},
        fingerprint_paid=fingerprint_paid,
        duplicate_allowed=duplicate_allowed,
        exception=exception,
    )
    context = ValidationContext.model_validate(
        {
            "now": NOW,
            "head_block": 101,
            "executor": EXECUTOR,
            "snapshot": snapshot,
            "request": request,
            "approval": approval,
            "flags": [],
            "coverage": "COMPLETE",
            "unknown_operations": 0,
            "pause_requested": False,
            "circuit_open": False,
            "screening_hit": False,
            "screening_clear": True,
            "policy_state": state,
        }
    )
    plan = _plan(amount, refill=refill, payee=payee)
    seq = 0
    return plan, context, seq


def test_contract_suite_covers_every_shared_manifest_case() -> None:
    source = CONTRACT_TEST.read_text(encoding="utf-8")
    assert all(f'"{case_id}"' in source for case_id in CASES)


@pytest.mark.parametrize("case_id", CASES)
def test_validator_matches_contract_differential_matrix(case_id: str) -> None:
    case = CASES[case_id]
    plan, context, seq = _context_and_plan(case_id)

    decision = validate_step(plan, seq, context)
    assert decision.decision == case["validator_decision"]
    assert (decision.primary.value if decision.primary else None) == case["primary"]
    assert (decision.decision == "ALLOW") == case["contract_success"]

    signature = case["contract_error"]
    if signature is not None:
        decoded = decode_revert(error_selector(signature))
        assert decoded[-1] == PolicyReasonCode(case["primary"])
