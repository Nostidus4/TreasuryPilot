from __future__ import annotations

import json
import re
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
    REASON_CODES,
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
OUTSIDER = Account.from_key("0x" + "7b" * 32)
OTHER_EXECUTOR = "0x" + "77" * 20
CHANGED_PAYEE = "0x" + "99" * 20
MATRIX_PATH = (
    Path(__file__).resolve().parents[3] / "contracts/test/vectors/policy_contract_differential.json"
)
CONTRACT_TEST = (
    Path(__file__).resolve().parents[3]
    / "contracts/test/scenarios/PolicyContractDifferential.t.sol"
)
REPORT = Path(__file__).resolve().parents[3] / "docs/testing/policy-contract-differential-report.md"
CASES: dict[str, dict[str, Any]] = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
UNKNOWN_PAYEE = "0x" + "00" * 18 + "abcd"
PER_REQUEST_LIMIT, DAILY_LIMIT = 2000 * 10**6, 10000 * 10**6
FIXTURE = Path(__file__).resolve().parents[3] / "contracts/test/helpers/TreasuryFixture.sol"


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
            "fiat_amount_minor_units": None,
        }
    )


def _approval(request: RequestView, expiry: int, signer: Any = APPROVER) -> ApprovalView:
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
        "isFiat": False,
    }
    full = payment_approval_typed_data(typed, chain_id=CHAIN, verifying_contract=TREASURY)
    signature = signer.sign_message(encode_typed_data(full_message=full)).signature
    return ApprovalView.model_validate(
        {
            "typed": typed,
            "signature": bytes(signature),
            "signer": signer.address,
            "approved_at": datetime.fromtimestamp(NOW - 3600, UTC),
            "created_by": MAKER,
            "last_edited_by": MAKER,
            "approved_by_user": CHECKER,
            "acknowledged_flag_ids": [],
            "solo_mode": False,
        }
    )


def _mandate(status: str, *, valid_from: int, expires_at: int) -> MandateView:
    return MandateView.model_validate(
        {
            "status": status,
            "version": 1,
            "valid_from": valid_from,
            "expires_at": expires_at,
            "executor": EXECUTOR,
        }
    )


def _plan(
    amount: int, *, refill: int | None = None, payee: str = PAYEE, step_id: bytes = b"\x0b" * 32
) -> ExecutionPlan:
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
            step_id=step_id,
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
    valid_from, expires_at = NOW - 86_400, NOW + 86_400
    approval_expiry = NOW + 14 * 86_400
    used_today = 0
    fingerprint_paid = False
    duplicate_allowed = False
    exception = None
    refill = None
    pay_amount = None
    o1_balance, safe_t_balance = 10000 * 10**6, 30000 * 10**6
    used_refill = 0
    request_paid = refilled = cancelled = False
    step_used: list[bytes] = []
    request_payee = None
    approvers = [APPROVER.address]
    approval_mode = "valid"
    executor = EXECUTOR
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
    elif case_id == "mandate_revoked":
        mandate_status = "Revoked"
    elif case_id == "mandate_expired":
        expires_at = NOW - 1
    elif case_id == "mandate_not_started":
        valid_from = NOW + 1
    elif case_id == "mandate_revoked_and_expired":
        mandate_status, expires_at = "Revoked", NOW - 1
    elif case_id == "mandate_paused_and_expired":
        mandate_status, expires_at = "Paused", NOW - 1
    elif case_id == "approval_expired":
        approval_expiry = NOW - 1
    elif case_id == "refill_bound":
        amount = 100 * 10**6
        refill = 1 * 10**6
    elif case_id == "refill_bound_exact":
        amount, refill, o1_balance = 100 * 10**6, 50 * 10**6, 200 * 10**6
    elif case_id == "refill_per_request":
        amount, refill, o1_balance = 3000 * 10**6, 2500 * 10**6 + 1, 0
    elif case_id == "refill_daily":
        amount, refill, o1_balance = 100 * 10**6, 1 * 10**6, 50 * 10**6
        used_refill = 12000 * 10**6
    elif case_id == "refill_already_done":
        amount, refill, o1_balance, refilled = 100 * 10**6, 1 * 10**6, 50 * 10**6, True
    elif case_id == "source_buffer_breach":
        amount, refill, o1_balance = 100 * 10**6, 1 * 10**6, 50 * 10**6
        safe_t_balance = 1000 * 10**6 + 500_000
    elif case_id == "daily_exact":
        amount, used_today = 1000 * 10**6, 9000 * 10**6
    elif case_id == "buffer_breach":
        o1_balance = 1505 * 10**6
    elif case_id == "wrong_payment_option":
        pay_amount = amount - 1
    elif case_id == "request_already_paid":
        request_paid = True
    elif case_id == "request_cancelled":
        cancelled = True
    elif case_id == "step_already_executed":
        step_used = [b"\x0b" * 32]
    elif case_id == "not_executor":
        executor = OTHER_EXECUTOR
    elif case_id == "approval_payee_changed":
        request_payee = CHANGED_PAYEE
    elif case_id == "approval_missing":
        approval_mode = "missing"
    elif case_id == "approval_bad_signature":
        approval_mode = "bad_signature"
    elif case_id == "approval_signer_not_approver":
        approval_mode = "outsider"
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

    request = _request(amount=amount, payee=request_payee or payee)
    if request_payee:
        payee = request_payee  # the request moved; the approval below signs the original payee
    approval: ApprovalView | None = (
        _approval(_request(amount=amount, payee=PAYEE), expiry=approval_expiry)
        if request_payee
        else _approval(request, expiry=approval_expiry)
    )
    if approval_mode == "missing":
        approval = None
    elif approval_mode == "bad_signature":
        other = _approval(_request(amount=amount + 1, payee=payee), expiry=approval_expiry)
        approval = approval.model_copy(update={"signature": other.signature})
    elif approval_mode == "outsider":
        approval = _approval(request, expiry=approval_expiry, signer=OUTSIDER)
    snapshot = ChainSnapshot.model_validate(
        {
            "chain_id": CHAIN,
            "treasury": TREASURY,
            "block_number": 100,
            "read_at": NOW - 5,
            "safe_t": SAFE_T,
            "asset": ASSET,
            "mandate": _mandate(mandate_status, valid_from=valid_from, expires_at=expires_at),
            "approvers": approvers,
            "payees": (
                {payee.lower(): PayeeView(active=True, active_from=active_from)}
                if case_id != "unknown_payee"
                else {}
            ),
            "request_cancelled": cancelled,
        }
    )
    state = PolicyState(
        pay_limits=Limits(per_request=PER_REQUEST_LIMIT, daily=DAILY_LIMIT),
        refill_limits=Limits(per_request=2500 * 10**6, daily=12000 * 10**6),
        supply_limits=Limits(per_request=5000 * 10**6, daily=20000 * 10**6),
        balances={O1.lower(): BaseUnits(o1_balance), SAFE_T.lower(): BaseUnits(safe_t_balance)},
        buffers={O1.lower(): BaseUnits(10 * 10**6), SAFE_T.lower(): BaseUnits(1000 * 10**6)},
        targets={O1.lower(): BaseUnits(150 * 10**6)},
        used_today={"PAY": BaseUnits(used_today), "REFILL": BaseUnits(used_refill)},
        request_paid=request_paid,
        refilled_for_request=refilled,
        step_used=step_used,
        fingerprint_paid=fingerprint_paid,
        duplicate_allowed=duplicate_allowed,
        exception=exception,
    )
    context = ValidationContext.model_validate(
        {
            "now": NOW,
            "head_block": 101,
            "executor": executor,
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
    plan = _plan(pay_amount or amount, refill=refill, payee=payee)
    seq = 0
    return plan, context, seq


def test_contract_suite_covers_every_shared_manifest_case() -> None:
    tests = [
        chunk
        for chunk in CONTRACT_TEST.read_text(encoding="utf-8").split("function ")
        if chunk.startswith("test")
    ]
    for case_id in CASES:
        pattern = re.compile(rf'_compare\w*\(\s*"{case_id}"')
        assert any(pattern.search(chunk) for chunk in tests), case_id


def test_report_lists_every_manifest_case() -> None:
    rows: dict[str, list[str]] = {}
    for line in REPORT.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 5 and re.fullmatch(r"`\w+`", cells[0]):
            rows[cells[0].strip("`")] = cells
    assert rows.keys() == CASES.keys(), rows.keys() ^ CASES.keys()
    for case_id, case in CASES.items():
        _, _, decision, code, module = rows[case_id]
        assert decision == case["validator_decision"], case_id
        assert code == (f"`{case['primary']}`" if case["primary"] else "—"), case_id
        expected = f"`{case['contract_error']}`" if case["contract_error"] else "success"
        assert module == expected, case_id


def test_python_fixture_limits_match_contract_fixture() -> None:
    source = FIXTURE.read_text(encoding="utf-8")
    expected = (
        f"I.Limits(uint128({PER_REQUEST_LIMIT // 10**6} * _assetUnit()), "
        f"uint128({DAILY_LIMIT // 10**6} * _assetUnit()))"
    )
    assert expected in source


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
        # contract_code: off-chain-only codes (APPROVAL_STALE, NOT_APPROVED) surface on-chain as
        # ApprovalInvalid, so the revert decodes to a different code than the validator's primary.
        code = PolicyReasonCode(case.get("contract_code", case["primary"]))
        assert decoded[-1] == code
        assert signature in REASON_CODES[code].contract_errors
