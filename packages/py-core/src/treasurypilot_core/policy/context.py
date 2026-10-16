"""Validator inputs (M08 §4.1): the execution plan and the context the worker builds around it.

Only the fields POL-002 checks read are modelled; POL-003 adds balances, counters and limits.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from treasurypilot_core.domain.models import (
    FrozenMapping,
    FrozenModel,
    FrozenSequence,
    NonNegativeInt,
)
from treasurypilot_core.eip712 import PAY, PAYMENT_APPROVAL_TYPE, REFILL, SUPPLY, SWAP_IN, WITHDRAW
from treasurypilot_core.money import BaseUnits

type Address = Annotated[str, Field(pattern=r"^0x[0-9a-fA-F]{40}$")]
type Bytes32 = Annotated[bytes, Field(min_length=32, max_length=32)]

_APPROVAL_FIELDS = {field["name"] for field in PAYMENT_APPROVAL_TYPE}


class _HexModel(FrozenModel):
    model_config = ConfigDict(ser_json_bytes="hex", val_json_bytes="hex")


class Action(StrEnum):
    REFILL = "REFILL"
    PAY = "PAY"
    SUPPLY = "SUPPLY"
    WITHDRAW = "WITHDRAW"  # pool → Safe T ahead of a REFILL
    SWAP = "SWAP"  # swap-for-gas on the test router


# The module's uint8 action codes (M08 §8.4).
_ACTION_CODES = {
    Action.PAY: PAY,
    Action.REFILL: REFILL,
    Action.SUPPLY: SUPPLY,
    Action.WITHDRAW: WITHDRAW,
    Action.SWAP: SWAP_IN,
}


class PlanStep(_HexModel):
    seq: NonNegativeInt
    step_id: Bytes32
    action: Action
    from_wallet: Address
    to: Address  # payingWallet for REFILL, payee for PAY, Safe T for WITHDRAW
    asset: Address
    amount: BaseUnits  # amountIn for a SWAP
    # SWAP only: the engine's output bound and the labelled venue (TEST_ROUTER, or SIGNED_QUOTE for the production adapter).
    min_out: BaseUnits | None = None
    venue: Literal["TEST_ROUTER", "SIGNED_QUOTE"] | None = None


class ExecutionPlan(_HexModel):
    request_id: Bytes32
    treasury: Address  # module clone
    chain_id: int
    steps: FrozenSequence[PlanStep]
    planner_source: Literal["AI", "DETERMINISTIC", "RULE_BASED"]
    evidence_ids: FrozenSequence[str]

    def message(self) -> dict[str, Any]:
        """The §8.3 Plan mapping that ``plan_hash`` and the attestation take, steps in plan order."""
        message: dict[str, Any] = {
            "requestId": "0x" + self.request_id.hex(),
            "treasury": self.treasury,
            "chainId": self.chain_id,
            "steps": [
                {
                    "seq": s.seq,
                    "stepId": "0x" + s.step_id.hex(),
                    "action": _ACTION_CODES[s.action],
                    "from": s.from_wallet,
                    "to": s.to,
                    "asset": s.asset,
                    "amount": int(s.amount),
                }
                for s in self.steps
            ],
        }
        # Outside the hashed steps (the planHash fields are fixed): minOut/venue ride beside them.
        swaps = {
            "0x" + s.step_id.hex(): {"minOut": int(s.min_out or 0), "venue": s.venue}
            for s in self.steps
            if s.action == Action.SWAP
        }
        if swaps:
            message["swaps"] = swaps
        return message


class MandateView(FrozenModel):
    status: Literal["Active", "Paused", "Revoked"]
    version: NonNegativeInt
    valid_from: NonNegativeInt
    expires_at: NonNegativeInt
    executor: Address


class PayeeView(FrozenModel):
    active: bool
    active_from: NonNegativeInt


class ChainSnapshot(FrozenModel):
    chain_id: int
    treasury: Address
    block_number: NonNegativeInt
    read_at: NonNegativeInt  # unix seconds the worker finished reading
    safe_t: Address
    asset: Address
    mandate: MandateView | None  # None when the read failed: DATA_MISSING
    approvers: FrozenSequence[Address]
    payees: FrozenMapping[str, PayeeView]  # lowercase address; absent = never added
    request_cancelled: bool


class RequestView(_HexModel):
    request_id: Bytes32
    status: str
    invoice_hash: Bytes32
    fingerprint: Bytes32
    terms_hash: Bytes32
    paying_wallet: Address
    payee: Address
    amount: BaseUnits
    fiat_amount_minor_units: NonNegativeInt | None  # set exactly for a fiat request
    early_amount: BaseUnits  # 0 = no early option (ADR-019)
    early_pay_by: NonNegativeInt
    deadline: NonNegativeInt

    def approved_amount(self, now: int) -> int:
        """The option pay() selects: the early amount while it is open (ADR-019), else the normal one."""
        early = self.early_amount > 0 and now <= self.early_pay_by
        return int(self.early_amount if early else self.amount)

    def allows_pay_amount(self, amount: int, now: int) -> bool:
        """Mirror of pay(): the approved amount exactly, or 1..approved for a fiat request."""
        approved = self.approved_amount(now)
        return (
            0 < amount <= approved
            if self.fiat_amount_minor_units is not None
            else amount == approved
        )


class ApprovalView(FrozenModel):
    typed: FrozenMapping[str, Any]  # the signed PaymentApproval message, EIP-712 field names
    signature: bytes
    signer: Address
    approved_at: datetime
    created_by: UUID
    last_edited_by: UUID
    approved_by_user: UUID
    acknowledged_flag_ids: FrozenSequence[UUID]
    solo_mode: bool

    @field_validator("typed")
    @classmethod
    def validate_fields(cls, typed: Any) -> Any:
        if set(typed) != _APPROVAL_FIELDS:
            raise ValueError(
                f"typed must hold exactly the PaymentApproval fields {_APPROVAL_FIELDS}"
            )
        return typed


class FlagView(FrozenModel):
    id: UUID
    code: str
    severity: Literal["LOW", "HIGH"]
    raised_at: datetime


class PolicyConfig(FrozenModel):
    """M08 §9 defaults (M08-D6: Sepolia, 12 s blocks)."""

    snapshot_max_age_seconds: NonNegativeInt = 30
    snapshot_max_blocks_behind: NonNegativeInt = 2
    min_supply: NonNegativeInt = 0
    validator_version: str = "0.1.0"


class Limits(FrozenModel):
    per_request: NonNegativeInt
    daily: NonNegativeInt


class ExceptionView(FrozenModel):
    amount: BaseUnits
    payee: Address
    expiry: NonNegativeInt
    mandate_version: NonNegativeInt
    used: bool = False


class PolicyState(FrozenModel):
    """Contract state needed by POL-003; every mapping is keyed by lowercase address/action."""

    pay_limits: Limits
    refill_limits: Limits
    supply_limits: Limits
    balances: FrozenMapping[str, BaseUnits]
    buffers: FrozenMapping[str, BaseUnits]
    targets: FrozenMapping[str, BaseUnits]
    used_today: FrozenMapping[str, BaseUnits]
    request_paid: bool = False
    step_used: FrozenSequence[bytes] = ()
    fingerprint_paid: bool = False
    duplicate_allowed: bool = False
    refilled_for_request: bool = False
    exception: ExceptionView | None = None
    payment_reserve: BaseUnits = BaseUnits(0)
    available_for_supply: BaseUnits = BaseUnits(0)
    a_token_balance: BaseUnits = BaseUnits(0)
    pool_liquidity: BaseUnits = BaseUnits(0)


class ValidationContext(FrozenModel):
    now: NonNegativeInt
    head_block: NonNegativeInt
    executor: Address  # the worker's executor key; must equal mandate.executor
    snapshot: ChainSnapshot
    request: RequestView | None  # None when the request could not be loaded: DATA_MISSING
    approval: ApprovalView | None
    flags: FrozenSequence[FlagView]
    coverage: Literal["COMPLETE", "PARTIAL_ACK", "PARTIAL", "NONE"]
    unknown_operations: NonNegativeInt
    pause_requested: bool
    circuit_open: bool
    screening_hit: bool
    screening_clear: bool = False
    # None: Travel Rule preflight was not run (not enforced here). False: the service reports
    # the PAY held, which blocks. True: non-qualifying, attested self-hosted, or completed.
    travel_rule_clear: bool | None = None
    policy_state: PolicyState | None = None
    config: PolicyConfig = PolicyConfig()
