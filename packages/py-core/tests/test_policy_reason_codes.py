import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from treasurypilot_core.policy import (
    REASON_CODES,
    Check,
    Decision,
    ReasonCode,
    catalogue_markdown,
    decode_revert,
    error_selector,
    precedence,
)

DOCS = Path(__file__).resolve().parents[3] / "docs"

# Executor custom errors from M04 §6.4 and §15. Governance-only errors are not validator
# codes. Follow-up: read these from the compiled module ABI once the contracts land (#271).
MODULE_ERRORS = {
    "NotExecutor",
    "NotActive",
    "MandateExpired",
    "ApprovalInvalid",
    "ApprovalExpired",
    "NotApprover",
    "RequestAlreadyPaid",
    "RequestCancelled",
    "StepAlreadyExecuted",
    "WrongRefillTarget",
    "AlreadyRefilledForRequest",
    "OverRefillPerRequest",
    "OverRefillDaily",
    "SourceBufferBreach",
    "RefillExceedsNeed",
    "TransferFailed",
    "BalanceDeltaMismatch",
    "NotOperationalWallet",
    "PayeeUnknown",
    "PayeeCooling",
    "DuplicateFingerprint",
    "OverPerRequestLimit",
    "ExceptionInvalid",
    "OverDailyLimit",
    "BufferBreach",
    "WrongPaymentOption",
    "OverSupplyPerTx",
    "OverSupplyDaily",
    "SupplyFloorBreach",
    "AllowanceNotCleared",
    "InsufficientAToken",
    "BorrowNotAuthorized",
    "HealthFactorTooLow",
    "AuthorizationExpired",
}


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else None]


def test_every_api_spec_error_code_is_in_the_catalogue() -> None:
    section = _section((DOCS / "API_SPEC.md").read_text(), "## 9. Error codes")
    api_codes = set(re.findall(r"`([A-Z][A-Z_]+)`", section))

    assert api_codes
    assert api_codes <= {code.value for code in ReasonCode}


def test_catalogue_describes_every_code_in_declaration_order() -> None:
    assert list(REASON_CODES) == list(ReasonCode)


def test_every_module_error_has_a_code_and_no_unknown_error_is_named() -> None:
    named = {error for reason in REASON_CODES.values() for error in reason.contract_errors}

    assert named == MODULE_ERRORS


def test_precedence_follows_group_order() -> None:
    groups = [REASON_CODES[code].group for code in sorted(ReasonCode, key=precedence)]

    assert groups == sorted(groups)


@pytest.mark.parametrize("error", sorted(MODULE_ERRORS))
def test_decode_revert_maps_every_module_error(error: str) -> None:
    code = decode_revert(error_selector(f"{error}()") + b"\x00" * 32)

    assert error in REASON_CODES[code].contract_errors


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ("NotActive", ReasonCode.MANDATE_NOT_ACTIVE),
        ("ApprovalInvalid", ReasonCode.APPROVAL_INVALID),
        ("RefillExceedsNeed", ReasonCode.REFILL_EXCEEDS_NEED),
        ("AuthorizationExpired", ReasonCode.BORROW_NOT_AUTHORIZED),
    ],
)
def test_error_shared_by_several_codes_decodes_to_the_general_one(
    error: str, code: ReasonCode
) -> None:
    assert decode_revert(error_selector(f"{error}()")) == code


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
    ],
)
def test_unknown_revert_data_fails_closed(data: bytes) -> None:
    assert decode_revert(data) == ReasonCode.SIMULATION_REVERTED


def test_post_execution_codes_block() -> None:
    for code in (ReasonCode.TRANSFER_FAILED, ReasonCode.BALANCE_DELTA_MISMATCH):
        assert REASON_CODES[code].default == "BLOCK"


def test_docs_table_is_generated_from_the_catalogue() -> None:
    readme = (DOCS / "modules/policy-engine/README.md").read_text()
    table = readme.split("<!-- reason-codes:start -->\n")[1].split("<!-- reason-codes:end -->")[0]

    # Regenerate with: uv run python -m treasurypilot_core.policy.reason_codes
    assert table == catalogue_markdown()


def _decision(**overrides: object) -> Decision:
    fields: dict[str, object] = {
        "decision": "BLOCK",
        "primary": ReasonCode.PAUSE_REQUESTED,
        "codes": [ReasonCode.BUFFER_BREACH, ReasonCode.PAUSE_REQUESTED],
        "warnings": [ReasonCode.DEADLINE_MISSED],
        "checks": [
            Check(
                name="pause",
                passed=False,
                code=ReasonCode.PAUSE_REQUESTED,
                expected=None,
                observed=None,
            )
        ],
        "stage": "PLAN",
        "step_seq": None,
        "policy_version": b"\x01" * 32,
        "snapshot_block": 7,
    }
    return Decision.model_validate(fields | overrides)


def test_decision_accepts_a_consistent_result() -> None:
    assert _decision().primary == ReasonCode.PAUSE_REQUESTED
    assert _decision(decision="ALLOW", primary=None, codes=[]).codes == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"primary": ReasonCode.BUFFER_BREACH},
        {"primary": None},
        {"codes": [], "primary": ReasonCode.PAUSE_REQUESTED},
        {"codes": [ReasonCode.DEADLINE_MISSED], "primary": ReasonCode.DEADLINE_MISSED},
        {"warnings": [ReasonCode.BUFFER_BREACH]},
        {"policy_version": b"\x01" * 31},
        {"stage": "LATER"},
    ],
)
def test_decision_rejects_inconsistent_results(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _decision(**overrides)
