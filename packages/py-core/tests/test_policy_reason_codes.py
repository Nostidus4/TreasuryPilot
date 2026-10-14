import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from treasurypilot_core.policy import (
    REASON_CODES,
    Check,
    Decision,
    PolicyReasonCode,
    aggregate,
    catalogue_markdown,
    decode_revert,
    error_selector,
    precedence,
)

DOCS = Path(__file__).resolve().parents[3] / "docs"

# Executor custom error signatures from M04 §6.4 and §15 (all argument-free in
# contracts/src/libraries/TreasuryPilotErrors.sol). Governance-only errors are not validator
# codes. Follow-up: read these from the compiled module ABI once the contracts land (#271).
MODULE_ERRORS = {
    "NotExecutor()",
    "NotActive()",
    "MandateExpired()",
    "ApprovalInvalid()",
    "ApprovalExpired()",
    "NotApprover()",
    "RequestAlreadyPaid()",
    "RequestCancelled()",
    "StepAlreadyExecuted()",
    "WrongRefillTarget()",
    "AlreadyRefilledForRequest()",
    "OverRefillPerRequest()",
    "OverRefillDaily()",
    "SourceBufferBreach()",
    "RefillExceedsNeed()",
    "TransferFailed()",
    "BalanceDeltaMismatch()",
    "NotOperationalWallet()",
    "PayeeUnknown()",
    "PayeeCooling()",
    "DuplicateFingerprint()",
    "OverPerRequestLimit()",
    "ExceptionInvalid()",
    "OverDailyLimit()",
    "BufferBreach()",
    "WrongPaymentOption()",
    "OverSupplyPerTx()",
    "OverSupplyDaily()",
    "SupplyFloorBreach()",
    "AllowanceNotCleared()",
    "InsufficientAToken()",
    "BorrowNotAuthorized()",
    "HealthFactorTooLow()",
    "AuthorizationExpired()",
}


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else None]


def test_api_spec_error_codes_equal_the_catalogue() -> None:
    section = _section((DOCS / "API_SPEC.md").read_text(), "## 9. Error codes")
    api_codes = set(re.findall(r"`([A-Z][A-Z_]+)`", section))

    assert api_codes
    assert api_codes == {code.value for code in PolicyReasonCode}


def test_catalogue_describes_every_code_in_declaration_order() -> None:
    assert list(REASON_CODES) == list(PolicyReasonCode)


def test_every_module_error_has_a_code_and_no_unknown_error_is_named() -> None:
    named = {error for reason in REASON_CODES.values() for error in reason.contract_errors}

    assert named == MODULE_ERRORS


def test_precedence_follows_group_order() -> None:
    groups = [REASON_CODES[code].group for code in sorted(PolicyReasonCode, key=precedence)]

    assert groups == sorted(groups)


@pytest.mark.parametrize("error", sorted(MODULE_ERRORS))
def test_decode_revert_maps_every_module_error(error: str) -> None:
    reverted, code = decode_revert(error_selector(error) + b"\x00" * 32)

    assert reverted == PolicyReasonCode.SIMULATION_REVERTED
    assert error in REASON_CODES[code].contract_errors


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ("NotActive()", PolicyReasonCode.MANDATE_NOT_ACTIVE),
        ("ApprovalInvalid()", PolicyReasonCode.APPROVAL_INVALID),
        ("RefillExceedsNeed()", PolicyReasonCode.REFILL_EXCEEDS_NEED),
        ("AuthorizationExpired()", PolicyReasonCode.BORROW_NOT_AUTHORIZED),
    ],
)
def test_error_shared_by_several_codes_decodes_to_the_general_one(
    error: str, code: PolicyReasonCode
) -> None:
    assert decode_revert(error_selector(error)) == (PolicyReasonCode.SIMULATION_REVERTED, code)


def test_selector_matches_solidity() -> None:
    assert error_selector("Error(string)").hex() == "08c379a0"
    assert error_selector("Panic(uint256)").hex() == "4e487b71"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x08\xc3",
        bytes.fromhex("08c379a0") + b"\x00" * 64,
        bytes.fromhex("4e487b71") + b"\x00" * 32,
        error_selector("NotOwner()"),
        # Arguments change the selector: only the listed signature decodes.
        error_selector("OverDailyLimit(uint256,uint256)"),
    ],
)
def test_unknown_revert_data_fails_closed(data: bytes) -> None:
    assert decode_revert(data) == (PolicyReasonCode.SIMULATION_REVERTED,)


def test_post_execution_codes_block() -> None:
    for code in (PolicyReasonCode.TRANSFER_FAILED, PolicyReasonCode.BALANCE_DELTA_MISMATCH):
        assert REASON_CODES[code].default == "BLOCK"


def test_docs_table_is_generated_from_the_catalogue() -> None:
    readme = (DOCS / "modules/policy-engine/README.md").read_text()
    table = readme.split("<!-- reason-codes:start -->\n")[1].split("<!-- reason-codes:end -->")[0]

    # Regenerate with: uv run python -m treasurypilot_core.policy.reason_codes
    assert table == catalogue_markdown()


C = PolicyReasonCode


def _check(code: PolicyReasonCode | None, *, passed: bool = False) -> Check:
    return Check(name="check", passed=passed, code=code, expected=None, observed=None)


def _decision(**overrides: object) -> Decision:
    fields: dict[str, object] = {
        "decision": "BLOCK",
        "primary": C.PAUSE_REQUESTED,
        "codes": [C.BUFFER_BREACH, C.PAUSE_REQUESTED],
        "warnings": [C.DEADLINE_MISSED],
        "checks": [
            _check(C.PAUSE_REQUESTED),
            _check(C.BUFFER_BREACH),
            _check(C.DEADLINE_MISSED),
            _check(C.PAYEE_COOLING, passed=True),
        ],
        "stage": "PLAN",
        "step_seq": None,
        "policy_version": b"\x01" * 32,
        "snapshot_block": 7,
    }
    return Decision.model_validate(fields | overrides)


def test_decision_accepts_a_consistent_result() -> None:
    assert _decision().primary == C.PAUSE_REQUESTED
    allow = _decision(decision="ALLOW", primary=None, codes=[], warnings=[], checks=[])
    assert allow.codes == []
    approval = _decision(
        decision="NEEDS_APPROVAL",
        primary=C.OVER_PER_REQUEST_LIMIT,
        codes=[C.OVER_PER_REQUEST_LIMIT],
        warnings=[],
        checks=[_check(C.OVER_PER_REQUEST_LIMIT)],
        stage="PRE_STEP",
        step_seq=0,
    )
    assert approval.decision == "NEEDS_APPROVAL"


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        ([], ("ALLOW", None)),
        ([C.DEADLINE_MISSED], ("ALLOW", None)),
        ([C.OVER_PER_REQUEST_LIMIT], ("NEEDS_APPROVAL", C.OVER_PER_REQUEST_LIMIT)),
        ([C.OVER_PER_REQUEST_LIMIT, C.OVER_DAILY_LIMIT], ("BLOCK", C.OVER_DAILY_LIMIT)),
        ([C.TRANSFER_FAILED, C.SIMULATION_REVERTED], ("BLOCK", C.SIMULATION_REVERTED)),
    ],
)
def test_aggregate_follows_m08_8_2(
    codes: list[PolicyReasonCode], expected: tuple[str, PolicyReasonCode | None]
) -> None:
    assert aggregate(codes) == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"primary": C.BUFFER_BREACH},
        {"primary": None},
        {"codes": [], "primary": C.PAUSE_REQUESTED},
        {"codes": [C.DEADLINE_MISSED], "primary": C.DEADLINE_MISSED},
        {"warnings": [C.BUFFER_BREACH]},
        {"policy_version": b"\x01" * 31},
        {"stage": "LATER"},
        # decision must follow codes (fail-closed)
        {"decision": "ALLOW"},
        {"decision": "NEEDS_APPROVAL"},
        {"codes": [], "primary": None, "checks": [_check(C.DEADLINE_MISSED)]},
        {
            "primary": C.OVER_PER_REQUEST_LIMIT,
            "codes": [C.OVER_PER_REQUEST_LIMIT],
            "warnings": [],
            "checks": [_check(C.OVER_PER_REQUEST_LIMIT)],
        },
        # checks must agree with codes and warnings
        {"checks": [_check(C.PAUSE_REQUESTED), _check(C.DEADLINE_MISSED)]},
        {"checks": [*_decision().checks, _check(C.SNAPSHOT_STALE)]},
        {"checks": [*_decision().checks, _check(None)]},
        {
            "decision": "ALLOW",
            "primary": None,
            "codes": [],
            "warnings": [],
            "checks": [_check(C.BUFFER_BREACH)],
        },
        # step_seq only and always outside PLAN
        {"step_seq": 3},
        {"stage": "PRE_STEP"},
        {"stage": "SIMULATION"},
    ],
)
def test_decision_rejects_inconsistent_results(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _decision(**overrides)


def test_decision_round_trips_through_json_and_plain_dicts() -> None:
    decision = _decision(policy_version=bytes(range(200, 232)))

    as_json = decision.model_dump_json()
    assert bytes(range(200, 232)).hex() in as_json
    assert Decision.model_validate_json(as_json) == decision

    as_dict = decision.model_dump() | {"codes": ["BUFFER_BREACH", "PAUSE_REQUESTED"]}
    as_dict["checks"] = [check | {"code": str(check["code"])} for check in as_dict["checks"]]
    assert Decision.model_validate(as_dict) == decision
