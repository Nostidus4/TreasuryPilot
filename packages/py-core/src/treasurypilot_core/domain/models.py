"""Frozen Pydantic models shared by the deterministic financial engine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    WrapSerializer,
    model_validator,
)

from treasurypilot_core.money import BaseUnits

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
BasisPoints = Annotated[int, Field(ge=0)]
type ReasonCode = str
type BindingConstraint = str


def _freeze_mapping(value: Mapping[Any, Any]) -> Mapping[Any, Any]:
    return MappingProxyType(dict(value))


def _serialize_mapping(value: Mapping[Any, Any], handler: SerializerFunctionWrapHandler) -> Any:
    return handler(dict(value))


# ``frozen=True`` only blocks attribute assignment, so container fields are
# converted to read-only views to keep shared snapshots immutable.
type FrozenMapping[K, V] = Annotated[
    Mapping[K, V], AfterValidator(_freeze_mapping), WrapSerializer(_serialize_mapping)
]
type FrozenSequence[T] = Annotated[Sequence[T], AfterValidator(tuple)]


class FrozenModel(BaseModel):
    """Strict value-object base class for engine inputs and outputs."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Asset(FrozenModel):
    chain_id: PositiveInt
    address: Annotated[str, Field(min_length=1)]
    decimals: Annotated[int, Field(ge=0, le=255)]
    symbol: Annotated[str, Field(min_length=1)]
    is_test: bool


class LateFee(FrozenModel):
    kind: Literal["fixed", "percent_per_period"]
    amount: BaseUnits | None = None
    rate_bps: Annotated[int, Field(ge=0, le=10_000)] | None = None
    period_days: PositiveInt | None = None
    cap: BaseUnits | None = None

    @model_validator(mode="after")
    def validate_kind_fields(self) -> LateFee:
        if self.kind == "fixed":
            if self.amount is None:
                raise ValueError("a fixed late fee requires amount")
            if self.rate_bps is not None or self.period_days is not None:
                raise ValueError("a fixed late fee cannot define rate_bps or period_days")
        else:
            if self.amount is not None:
                raise ValueError("a percent-per-period late fee cannot define amount")
            if self.rate_bps is None or self.period_days is None:
                raise ValueError("a percent-per-period late fee requires rate_bps and period_days")
            if self.rate_bps == 0:
                raise ValueError("a percent-per-period late fee requires a positive rate_bps")
        return self


class PaymentTerms(FrozenModel):
    net_due_day: NonNegativeInt
    discount_bps: Annotated[int, Field(ge=0, le=10_000)] = 0
    discount_deadline_day: NonNegativeInt | None = None
    late_fee: LateFee | None = None
    priority_note: str | None = None

    @model_validator(mode="after")
    def validate_discount(self) -> PaymentTerms:
        if self.discount_bps > 0 and self.discount_deadline_day is None:
            raise ValueError("discount_deadline_day is required when discount_bps is positive")
        if self.discount_deadline_day is not None:
            if self.discount_bps == 0:
                raise ValueError("discount_bps must be positive when a discount deadline is set")
            if self.discount_deadline_day > self.net_due_day:
                raise ValueError("discount deadline cannot be after the net due day")
        return self


class WalletState(FrozenModel):
    address: Annotated[str, Field(min_length=1)]
    balance: BaseUnits
    buffer: BaseUnits
    target: BaseUnits

    @model_validator(mode="after")
    def validate_target(self) -> WalletState:
        if self.target < self.buffer:
            raise ValueError("wallet target cannot be below its minimum buffer")
        return self


class Limits(FrozenModel):
    per_request: BaseUnits
    daily: BaseUnits


class PolicyView(FrozenModel):
    pay: Limits
    refill: Limits
    cooling_seconds: NonNegativeInt


class LiquidityPolicy(FrozenModel):
    """Supply controls and non-payment reserves for one liquidity cycle."""

    supply: Limits
    min_supply: BaseUnits
    debt_service_reserve: BaseUnits = BaseUnits(0)
    execution_holds: BaseUnits = BaseUnits(0)
    reserve_horizon_days: Annotated[int, Field(ge=1, le=30)] = 30


class Snapshot(FrozenModel):
    day: NonNegativeInt
    source: WalletState
    operational: FrozenMapping[str, WalletState]
    # "pay" and "refill" are required; "supply" and "withdraw" default to zero.
    used_today: FrozenMapping[Literal["pay", "refill", "supply", "withdraw"], BaseUnits]
    payee_active_day: FrozenMapping[str, NonNegativeInt]
    safe_usdc: BaseUnits
    a_usdc: BaseUnits
    pool_available: BaseUnits
    supply_rate_bps: BasisPoints
    borrow_rate_bps: BasisPoints
    health_factor: NonNegativeInt | None = None
    debt: BaseUnits
    # Owner-allowlisted operational (from, to) refill paths (SC-L06, F-059). Empty = Safe T only.
    refill_paths: FrozenSequence[tuple[str, str]] = ()

    @model_validator(mode="after")
    def validate_usage_counters(self) -> Snapshot:
        if any(source == target for source, target in self.refill_paths):
            raise ValueError("a refill path cannot start and end at the same wallet")
        if not {"pay", "refill"} <= set(self.used_today):
            raise ValueError("used_today must contain the pay and refill counters")
        if self.debt > 0 and self.health_factor is None:
            raise ValueError("health_factor is required when debt exists")
        return self


class ApprovedRequest(FrozenModel):
    id: Annotated[str, Field(min_length=1)]
    paying_wallet: Annotated[str, Field(min_length=1)]
    payee: Annotated[str, Field(min_length=1)]
    amount: BaseUnits
    approved_seq: NonNegativeInt
    terms: PaymentTerms
    early_amount: BaseUnits | None = None
    early_pay_by: NonNegativeInt | None = None
    exception_granted: bool = False

    @model_validator(mode="after")
    def validate_early_payment_option(self) -> ApprovedRequest:
        if (self.early_amount is None) != (self.early_pay_by is None):
            raise ValueError("early_amount and early_pay_by must be defined together")
        if self.early_amount is None or self.early_pay_by is None:
            return self
        if self.early_amount == 0:
            raise ValueError("early_amount must be positive when an early option is present")
        if self.early_amount > self.amount:
            raise ValueError("early_amount cannot exceed the standard amount")
        if self.early_pay_by > self.terms.net_due_day:
            raise ValueError("early_pay_by cannot be after the net due day")
        return self


class RefillDecision(FrozenModel):
    kind: Literal["none", "preferred", "shortage", "stop"]
    amount: BaseUnits
    reason: ReasonCode


class ScheduledItem(FrozenModel):
    request_id: Annotated[str, Field(min_length=1)]
    day: NonNegativeInt
    refill: BaseUnits
    value: int
    # ``default`` preserves the meaning of schedules produced by the single-asset API.
    asset_id: Annotated[str, Field(min_length=1)] = "default"
    # Operational wallet funding the refill; None means Safe T (the default source).
    refill_from: Annotated[str, Field(min_length=1)] | None = None


class Infeasible(FrozenModel):
    request_id: Annotated[str, Field(min_length=1)]
    reason: ReasonCode
    detail: str
    asset_id: Annotated[str, Field(min_length=1)] = "default"


class Schedule(FrozenModel):
    items: FrozenSequence[ScheduledItem]
    infeasible: FrozenSequence[Infeasible]
    objective: tuple[int, int, int, int]
    binding: FrozenSequence[BindingConstraint]
    solver: Literal["EDF", "CPSAT", "ORACLE"]
    status: Literal["OPTIMAL", "FEASIBLE", "FALLBACK"]


class BindingConstraintDetail(FrozenModel):
    """Numeric explanation of a constraint that a proposed plan reaches or breaks."""

    name: Literal[
        "PAY_DAILY_CAP",
        "REFILL_DAILY_CAP",
        "BUFFER",
        "SOURCE_CAPACITY",
        "REFILL_BOUND",
        "COOLING",
        "DEADLINE",
    ]
    request_id: Annotated[str, Field(min_length=1)]
    day: NonNegativeInt
    used: int
    limit: int


class ExceptionValue(FrozenModel):
    """Value currently blocked by the per-request cap if an Owner grants an exception."""

    request_id: Annotated[str, Field(min_length=1)]
    value: int


class LiquidityPosition(FrozenModel):
    payment_reserve: BaseUnits
    safe_floor: BaseUnits
    debt_service_reserve: BaseUnits
    execution_holds: BaseUnits
    required_safe_reserve: BaseUnits
    deficit: BaseUnits
    available_for_supply: BaseUnits
    accessible_liquidity: BaseUnits


class LiquidityDecision(FrozenModel):
    """One liquidity action per cycle.

    ``amount`` is what to SUPPLY or WITHDRAW. For ``INSUFFICIENT_LIQUIDITY`` it is the
    partial withdrawal still worth making before a borrow proposal, and it is zero
    when nothing can be withdrawn: callers must not submit a zero withdrawal.
    """

    kind: Literal["NONE", "SUPPLY", "WITHDRAW", "INSUFFICIENT_LIQUIDITY"]
    amount: BaseUnits
    shortfall: BaseUnits = BaseUnits(0)
    reason: str
    position: LiquidityPosition

    @model_validator(mode="after")
    def validate_amounts(self) -> LiquidityDecision:
        if self.kind in ("SUPPLY", "WITHDRAW") and self.amount == 0:
            raise ValueError(f"{self.kind} requires a positive amount")
        if self.kind == "NONE" and self.amount != 0:
            raise ValueError("NONE carries no amount")
        if (self.kind == "INSUFFICIENT_LIQUIDITY") != (self.shortfall > 0):
            raise ValueError("only INSUFFICIENT_LIQUIDITY carries a shortfall")
        return self


class BorrowProposal(FrozenModel):
    """A non-executable estimate for covering a liquidity shortfall with borrowing."""

    amount: BaseUnits
    cost_to_repayment: BaseUnits
    withdraw_cost: BaseUnits
    health_factor_before: NonNegativeInt | None
    health_factor_after: NonNegativeInt | None
    reason: str

    @model_validator(mode="after")
    def validate_proposal(self) -> BorrowProposal:
        if self.amount == 0:
            raise ValueError("borrow proposal requires a positive amount")
        if not self.reason.strip():
            raise ValueError("borrow proposal requires a reason")
        return self


class ForecastRefill(FrozenModel):
    day: NonNegativeInt
    request_id: Annotated[str, Field(min_length=1)]
    source_wallet: Annotated[str, Field(min_length=1)]
    target_wallet: Annotated[str, Field(min_length=1)]
    amount: BaseUnits


class ForecastDay(FrozenModel):
    day: NonNegativeInt
    balances: FrozenMapping[str, BaseUnits]
    buffer_hit_wallets: FrozenSequence[str]
    suggested_refills: FrozenSequence[ForecastRefill]
    unpaid_due: BaseUnits


class Forecast(FrozenModel):
    days: FrozenSequence[ForecastDay]
    buffer_hit_days: FrozenMapping[str, FrozenSequence[int]]
    shortfall_days: FrozenSequence[int]
    unplanned_request_ids: FrozenSequence[str]
    deferred_request_ids: FrozenSequence[str]
