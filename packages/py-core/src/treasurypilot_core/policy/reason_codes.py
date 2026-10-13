"""Policy reason-code catalogue (M08 §6.4, API_SPEC §9).

One list shared by the validator, API errors, the UI and the contract's custom errors.
Declaration order is precedence: `primary` is the failing code declared first. These are
policy codes; the financial engine's free-form `domain.ReasonCode` strings are separate.
"""

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Literal

from eth_hash.auto import keccak


class Group(IntEnum):
    SAFETY_GATE = 1
    LIFECYCLE = 2
    APPROVAL = 3
    WALLET_PATH = 4
    REPLAY = 5
    PAYEE = 6
    LIMITS = 7
    LIQUIDITY = 8
    PLAN = 9
    SIMULATION = 10
    SIGNER = 11
    POST_EXECUTION = 12
    WARNING = 13


type DefaultDecision = Literal["BLOCK", "NEEDS_APPROVAL", "WARNING"]


@dataclass(frozen=True)
class ReasonInfo:
    group: Group
    default: DefaultDecision
    contract_errors: tuple[str, ...]  # full module error signatures decoded to this code
    rules: str
    note: str = ""


class PolicyReasonCode(StrEnum):
    PAUSE_REQUESTED = "PAUSE_REQUESTED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    UNKNOWN_OPERATION_PENDING = "UNKNOWN_OPERATION_PENDING"
    COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"
    SNAPSHOT_STALE = "SNAPSHOT_STALE"
    DATA_MISSING = "DATA_MISSING"
    CHAIN_MISMATCH = "CHAIN_MISMATCH"
    ASSET_MISMATCH = "ASSET_MISMATCH"
    MANDATE_NOT_ACTIVE = "MANDATE_NOT_ACTIVE"
    MANDATE_PAUSED = "MANDATE_PAUSED"
    MANDATE_REVOKED = "MANDATE_REVOKED"
    MANDATE_EXPIRED = "MANDATE_EXPIRED"
    EXECUTOR_MISMATCH = "EXECUTOR_MISMATCH"
    NOT_APPROVED = "NOT_APPROVED"
    APPROVAL_INVALID = "APPROVAL_INVALID"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    NOT_IN_APPROVER_SET = "NOT_IN_APPROVER_SET"
    APPROVAL_STALE = "APPROVAL_STALE"
    MAKER_CHECKER = "MAKER_CHECKER"
    FLAG_UNACKNOWLEDGED = "FLAG_UNACKNOWLEDGED"
    SCREENING_HIT = "SCREENING_HIT"
    WRONG_PAYMENT_OPTION = "WRONG_PAYMENT_OPTION"
    NOT_OPERATIONAL_WALLET = "NOT_OPERATIONAL_WALLET"
    WRONG_REFILL_TARGET = "WRONG_REFILL_TARGET"
    REQUEST_ALREADY_PAID = "REQUEST_ALREADY_PAID"
    STEP_ALREADY_EXECUTED = "STEP_ALREADY_EXECUTED"
    REQUEST_CANCELLED = "REQUEST_CANCELLED"
    ALREADY_REFILLED_FOR_REQUEST = "ALREADY_REFILLED_FOR_REQUEST"
    DUPLICATE_FINGERPRINT = "DUPLICATE_FINGERPRINT"
    PAYEE_UNKNOWN = "PAYEE_UNKNOWN"
    PAYEE_COOLING = "PAYEE_COOLING"
    OVER_DAILY_LIMIT = "OVER_DAILY_LIMIT"
    OVER_REFILL_PER_REQUEST = "OVER_REFILL_PER_REQUEST"
    OVER_REFILL_DAILY = "OVER_REFILL_DAILY"
    EXCEPTION_INVALID = "EXCEPTION_INVALID"
    OVER_SUPPLY_PER_TX = "OVER_SUPPLY_PER_TX"
    OVER_SUPPLY_DAILY = "OVER_SUPPLY_DAILY"
    OVER_PER_REQUEST_LIMIT = "OVER_PER_REQUEST_LIMIT"
    BUFFER_BREACH = "BUFFER_BREACH"
    SOURCE_BUFFER_BREACH = "SOURCE_BUFFER_BREACH"
    SOURCE_INSUFFICIENT = "SOURCE_INSUFFICIENT"
    REFILL_EXCEEDS_NEED = "REFILL_EXCEEDS_NEED"
    REFILL_BOUND = "REFILL_BOUND"
    SUPPLY_FLOOR_BREACH = "SUPPLY_FLOOR_BREACH"
    RESERVE_BREACH = "RESERVE_BREACH"
    INSUFFICIENT_POOL_LIQUIDITY = "INSUFFICIENT_POOL_LIQUIDITY"
    INSUFFICIENT_A_TOKEN = "INSUFFICIENT_A_TOKEN"
    BORROW_NOT_AUTHORIZED = "BORROW_NOT_AUTHORIZED"
    HEALTH_FACTOR_TOO_LOW = "HEALTH_FACTOR_TOO_LOW"
    PLAN_MALFORMED = "PLAN_MALFORMED"
    AI_PLAN_REJECTED = "AI_PLAN_REJECTED"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"
    SIMULATION_REVERTED = "SIMULATION_REVERTED"
    SIMULATION_UNAVAILABLE = "SIMULATION_UNAVAILABLE"
    ATTESTATION_INVALID = "ATTESTATION_INVALID"
    ATTESTATION_EXPIRED = "ATTESTATION_EXPIRED"
    NONCE_REUSED = "NONCE_REUSED"
    PAYLOAD_MISMATCH = "PAYLOAD_MISMATCH"
    TRANSFER_FAILED = "TRANSFER_FAILED"
    BALANCE_DELTA_MISMATCH = "BALANCE_DELTA_MISMATCH"
    ALLOWANCE_NOT_CLEARED = "ALLOWANCE_NOT_CLEARED"
    DEADLINE_MISSED = "DEADLINE_MISSED"
    DISCOUNT_MISSED = "DISCOUNT_MISSED"
    TARGET_NOT_REACHED = "TARGET_NOT_REACHED"
    BELOW_MIN_SUPPLY = "BELOW_MIN_SUPPLY"


def _info(
    group: Group, rules: str, *errors: str, default: DefaultDecision = "BLOCK", note: str = ""
) -> ReasonInfo:
    return ReasonInfo(group, default, errors, rules, note)


_G = Group
_RECEIPT_NOTE = "receipts; fail-closed if a simulation decodes it"

REASON_CODES: dict[PolicyReasonCode, ReasonInfo] = {
    PolicyReasonCode.PAUSE_REQUESTED: _info(_G.SAFETY_GATE, "BR-063"),
    PolicyReasonCode.CIRCUIT_OPEN: _info(_G.SAFETY_GATE, "BR-065"),
    PolicyReasonCode.UNKNOWN_OPERATION_PENDING: _info(_G.SAFETY_GATE, "BR-060"),
    PolicyReasonCode.COVERAGE_INCOMPLETE: _info(_G.SAFETY_GATE, "BR-018"),
    PolicyReasonCode.SNAPSHOT_STALE: _info(_G.SAFETY_GATE, "BR-051, M08-D6"),
    PolicyReasonCode.DATA_MISSING: _info(_G.SAFETY_GATE, "FR-411"),
    PolicyReasonCode.CHAIN_MISMATCH: _info(_G.SAFETY_GATE, "BR-014"),
    PolicyReasonCode.ASSET_MISMATCH: _info(
        _G.SAFETY_GATE, "BR-014", note="the contract reverts `ApprovalInvalid`"
    ),
    PolicyReasonCode.MANDATE_NOT_ACTIVE: _info(_G.LIFECYCLE, "BR-015, BR-062", "NotActive()"),
    PolicyReasonCode.MANDATE_PAUSED: _info(_G.LIFECYCLE, "BR-015, BR-062", "NotActive()"),
    PolicyReasonCode.MANDATE_REVOKED: _info(_G.LIFECYCLE, "BR-015, BR-062", "NotActive()"),
    PolicyReasonCode.MANDATE_EXPIRED: _info(_G.LIFECYCLE, "BR-015", "MandateExpired()"),
    PolicyReasonCode.EXECUTOR_MISMATCH: _info(_G.LIFECYCLE, "BR-092", "NotExecutor()"),
    PolicyReasonCode.NOT_APPROVED: _info(_G.APPROVAL, "BR-001"),
    PolicyReasonCode.APPROVAL_INVALID: _info(_G.APPROVAL, "BR-004", "ApprovalInvalid()"),
    PolicyReasonCode.APPROVAL_EXPIRED: _info(_G.APPROVAL, "BR-003", "ApprovalExpired()"),
    PolicyReasonCode.NOT_IN_APPROVER_SET: _info(_G.APPROVAL, "BR-001, OQ-08", "NotApprover()"),
    PolicyReasonCode.APPROVAL_STALE: _info(
        _G.APPROVAL,
        "BR-002",
        note="invoiceHash/termsHash/amount/earlyAmount/earlyPayBy/deadline/payee differ from the current request",
    ),
    PolicyReasonCode.MAKER_CHECKER: _info(_G.APPROVAL, "BR-005"),
    PolicyReasonCode.FLAG_UNACKNOWLEDGED: _info(_G.APPROVAL, "BR-066, FR-313"),
    PolicyReasonCode.SCREENING_HIT: _info(_G.APPROVAL, "BR-085"),
    PolicyReasonCode.WRONG_PAYMENT_OPTION: _info(_G.APPROVAL, "ADR-019", "WrongPaymentOption()"),
    PolicyReasonCode.NOT_OPERATIONAL_WALLET: _info(
        _G.WALLET_PATH, "BR-019", "NotOperationalWallet()"
    ),
    PolicyReasonCode.WRONG_REFILL_TARGET: _info(_G.WALLET_PATH, "BR-012", "WrongRefillTarget()"),
    PolicyReasonCode.REQUEST_ALREADY_PAID: _info(_G.REPLAY, "BR-061", "RequestAlreadyPaid()"),
    PolicyReasonCode.STEP_ALREADY_EXECUTED: _info(_G.REPLAY, "BR-061", "StepAlreadyExecuted()"),
    PolicyReasonCode.REQUEST_CANCELLED: _info(
        _G.REPLAY,
        "BR-077",
        "RequestCancelled()",
        note="off-chain status Cancelled or on-chain `requestCancelled`",
    ),
    PolicyReasonCode.ALREADY_REFILLED_FOR_REQUEST: _info(
        _G.REPLAY, "BR-036", "AlreadyRefilledForRequest()"
    ),
    PolicyReasonCode.DUPLICATE_FINGERPRINT: _info(_G.REPLAY, "BR-071", "DuplicateFingerprint()"),
    PolicyReasonCode.PAYEE_UNKNOWN: _info(_G.PAYEE, "BR-013", "PayeeUnknown()"),
    PolicyReasonCode.PAYEE_COOLING: _info(_G.PAYEE, "BR-017", "PayeeCooling()"),
    PolicyReasonCode.OVER_DAILY_LIMIT: _info(_G.LIMITS, "BR-022", "OverDailyLimit()"),
    PolicyReasonCode.OVER_REFILL_PER_REQUEST: _info(_G.LIMITS, "BR-023", "OverRefillPerRequest()"),
    PolicyReasonCode.OVER_REFILL_DAILY: _info(_G.LIMITS, "BR-023", "OverRefillDaily()"),
    PolicyReasonCode.EXCEPTION_INVALID: _info(_G.LIMITS, "BR-041", "ExceptionInvalid()"),
    PolicyReasonCode.OVER_SUPPLY_PER_TX: _info(_G.LIMITS, "ADR-019", "OverSupplyPerTx()"),
    PolicyReasonCode.OVER_SUPPLY_DAILY: _info(_G.LIMITS, "ADR-019", "OverSupplyDaily()"),
    PolicyReasonCode.OVER_PER_REQUEST_LIMIT: _info(
        _G.LIMITS, "BR-040", "OverPerRequestLimit()", default="NEEDS_APPROVAL"
    ),
    PolicyReasonCode.BUFFER_BREACH: _info(_G.LIQUIDITY, "BR-030", "BufferBreach()"),
    PolicyReasonCode.SOURCE_BUFFER_BREACH: _info(_G.LIQUIDITY, "BR-030", "SourceBufferBreach()"),
    PolicyReasonCode.SOURCE_INSUFFICIENT: _info(_G.LIQUIDITY, "BR-033"),
    PolicyReasonCode.REFILL_EXCEEDS_NEED: _info(_G.LIQUIDITY, "BR-036", "RefillExceedsNeed()"),
    PolicyReasonCode.REFILL_BOUND: _info(_G.LIQUIDITY, "BR-036", "RefillExceedsNeed()"),
    PolicyReasonCode.SUPPLY_FLOOR_BREACH: _info(_G.LIQUIDITY, "ADR-019", "SupplyFloorBreach()"),
    PolicyReasonCode.RESERVE_BREACH: _info(
        _G.LIQUIDITY, "ADR-019", note="off-chain PaymentReserve"
    ),
    PolicyReasonCode.INSUFFICIENT_POOL_LIQUIDITY: _info(_G.LIQUIDITY, "ADR-019"),
    PolicyReasonCode.INSUFFICIENT_A_TOKEN: _info(_G.LIQUIDITY, "ADR-019", "InsufficientAToken()"),
    PolicyReasonCode.BORROW_NOT_AUTHORIZED: _info(
        _G.LIQUIDITY, "ADR-019", "BorrowNotAuthorized()", "AuthorizationExpired()", note="P2"
    ),
    PolicyReasonCode.HEALTH_FACTOR_TOO_LOW: _info(
        _G.LIQUIDITY, "ADR-019", "HealthFactorTooLow()", note="P2"
    ),
    PolicyReasonCode.PLAN_MALFORMED: _info(
        _G.PLAN,
        "BR-056",
        note="wrong step order, >1 PAY, amount ≠ approval option, refill/withdraw not for this request",
    ),
    PolicyReasonCode.AI_PLAN_REJECTED: _info(_G.PLAN, "BR-056"),
    PolicyReasonCode.AI_UNAVAILABLE: _info(_G.PLAN, "BR-055"),
    PolicyReasonCode.SIMULATION_REVERTED: _info(
        _G.SIMULATION, "BR-067", note="every revert; known errors also add their own code"
    ),
    PolicyReasonCode.SIMULATION_UNAVAILABLE: _info(_G.SIMULATION, "BR-067"),
    PolicyReasonCode.ATTESTATION_INVALID: _info(_G.SIGNER, "BR-059"),
    PolicyReasonCode.ATTESTATION_EXPIRED: _info(_G.SIGNER, "BR-059"),
    PolicyReasonCode.NONCE_REUSED: _info(_G.SIGNER, "BR-059"),
    PolicyReasonCode.PAYLOAD_MISMATCH: _info(_G.SIGNER, "BR-059"),
    PolicyReasonCode.TRANSFER_FAILED: _info(
        _G.POST_EXECUTION, "M04-D8", "TransferFailed()", note=_RECEIPT_NOTE
    ),
    PolicyReasonCode.BALANCE_DELTA_MISMATCH: _info(
        _G.POST_EXECUTION, "M04-D8", "BalanceDeltaMismatch()", note=_RECEIPT_NOTE
    ),
    PolicyReasonCode.ALLOWANCE_NOT_CLEARED: _info(
        _G.POST_EXECUTION, "ADR-019", "AllowanceNotCleared()", note=_RECEIPT_NOTE
    ),
    PolicyReasonCode.DEADLINE_MISSED: _info(_G.WARNING, "M08-D7", default="WARNING"),
    PolicyReasonCode.DISCOUNT_MISSED: _info(_G.WARNING, "M08-D7", default="WARNING"),
    PolicyReasonCode.TARGET_NOT_REACHED: _info(_G.WARNING, "BR-032", default="WARNING"),
    PolicyReasonCode.BELOW_MIN_SUPPLY: _info(
        _G.WARNING, "ADR-019", default="WARNING", note="the SUPPLY step is dropped"
    ),
}

_PRECEDENCE = {code: rank for rank, code in enumerate(PolicyReasonCode)}


def precedence(code: PolicyReasonCode) -> int:
    """Lower wins when choosing `primary`."""

    return _PRECEDENCE[code]


def is_warning(code: PolicyReasonCode) -> bool:
    return REASON_CODES[code].default == "WARNING"


def error_selector(signature: str) -> bytes:
    """First four bytes of keccak256 of a Solidity error signature, e.g. `NotActive()`."""

    return keccak(signature.encode())[:4]


# Selectors hash the full signature, so an error that gains arguments must be listed with
# them (e.g. `OverDailyLimit(uint256,uint256)`). The first code declared for an error wins.
_BY_SELECTOR: dict[bytes, PolicyReasonCode] = {}
for _code, _reason in REASON_CODES.items():
    for _error in _reason.contract_errors:
        _BY_SELECTOR.setdefault(error_selector(_error), _code)


def decode_revert(data: bytes) -> tuple[PolicyReasonCode, ...]:
    """Map simulation revert data to codes (M08 §8.5 row 12).

    Always `SIMULATION_REVERTED` (BLOCK), plus the decoded code for a known module error.
    """

    decoded = _BY_SELECTOR.get(bytes(data[:4]))
    reverted = PolicyReasonCode.SIMULATION_REVERTED
    return (reverted,) if decoded is None else (reverted, decoded)


_DECISION_LABEL = {"BLOCK": "B", "NEEDS_APPROVAL": "**NA**", "WARNING": "W"}


def catalogue_markdown() -> str:
    """The M08 §6.4 table. Regenerate with `python -m treasurypilot_core.policy.reason_codes`."""

    lines = [
        "| # | Group | Code | Dec. | Contract error | Rule | Note |",
        "|---|---|---|---|---|---|---|",
    ]
    for code, reason in REASON_CODES.items():
        group = reason.group
        number = "—" if group is Group.WARNING else str(group.value)
        name = group.name.replace("_", " ").capitalize()
        errors = ", ".join(f"`{error}`" for error in reason.contract_errors) or "—"
        lines.append(
            f"| {number} | {name} | `{code}` | {_DECISION_LABEL[reason.default]} "
            f"| {errors} | {reason.rules} | {reason.note} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(catalogue_markdown(), end="")
