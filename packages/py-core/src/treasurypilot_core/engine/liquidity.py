"""Integer-only liquidity formulas from BR-032 and financial-engine section 6."""

from __future__ import annotations

from collections.abc import Sequence

from treasurypilot_core.domain import (
    ApprovedRequest,
    LiquidityDecision,
    LiquidityPolicy,
    LiquidityPosition,
    PolicyView,
    RefillDecision,
    Schedule,
    Snapshot,
    WalletState,
)
from treasurypilot_core.money import BaseUnits

_ZERO = BaseUnits(0)

NO_REFILL_REQUIRED = "NO_REFILL_REQUIRED"
TARGET_REACHED = "TARGET_REACHED"
TARGET_NOT_REACHED = "TARGET_NOT_REACHED"
REFILL_BOUND = "REFILL_BOUND"
SOURCE_INSUFFICIENT = "SOURCE_INSUFFICIENT"
OVER_REFILL_DAILY = "OVER_REFILL_DAILY"
OVER_REFILL_PER_REQUEST = "OVER_REFILL_PER_REQUEST"
WRONG_REFILL_TARGET = "WRONG_REFILL_TARGET"
RESERVE_DEFICIT = "RESERVE_DEFICIT"
SUPPLY_AVAILABLE = "SUPPLY_AVAILABLE"
BELOW_MIN_SUPPLY = "BELOW_MIN_SUPPLY"
INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"


def _require_base_units(value: BaseUnits, name: str) -> BaseUnits:
    """Reject callers that bypass the strict money boundary."""

    if not isinstance(value, BaseUnits):
        raise TypeError(f"{name} must be BaseUnits")
    return value


def _non_negative_difference(minuend: int, subtrahend: int) -> BaseUnits:
    """Subtract with a zero floor while preserving the money value type."""

    return BaseUnits(max(0, minuend - subtrahend))


def available(wallet: WalletState, protected_other: BaseUnits) -> BaseUnits:
    """Return funds usable without consuming other holds or the wallet buffer."""

    protected = _require_base_units(protected_other, "protected_other")
    return _non_negative_difference(
        wallet.balance,
        protected + wallet.buffer,
    )


def funding_deficit(wallet: WalletState, protected_other: BaseUnits) -> BaseUnits:
    """Return the amount needed to cover other holds and the wallet buffer."""

    protected = _require_base_units(protected_other, "protected_other")
    return _non_negative_difference(
        protected + wallet.buffer,
        wallet.balance,
    )


def shortage(
    wallet: WalletState,
    demand: BaseUnits,
    protected_other: BaseUnits,
) -> BaseUnits:
    """Return the minimum refill needed to meet demand and retain the buffer."""

    request_demand = _require_base_units(demand, "demand")
    protected = _require_base_units(protected_other, "protected_other")
    return _non_negative_difference(
        protected + request_demand + wallet.buffer,
        wallet.balance,
    )


def preferred_refill(
    wallet: WalletState,
    demand: BaseUnits,
    protected_other: BaseUnits,
) -> BaseUnits:
    """Return the refill needed to meet demand and finish at the soft target."""

    request_demand = _require_base_units(demand, "demand")
    protected = _require_base_units(protected_other, "protected_other")
    return _non_negative_difference(
        protected + request_demand + wallet.target,
        wallet.balance,
    )


def source_capacity(source: WalletState, protected_other: BaseUnits) -> BaseUnits:
    """Return source funds available for refill; the M1 source gas term is zero."""

    protected = _require_base_units(protected_other, "protected_other")
    return _non_negative_difference(
        source.balance,
        protected + source.buffer,
    )


def refill_bound(wallet: WalletState, amount: BaseUnits) -> BaseUnits:
    """Return the BR-036 maximum refill bound for one approved request."""

    request_amount = _require_base_units(amount, "amount")
    return _non_negative_difference(
        request_amount + wallet.target,
        wallet.balance,
    )


def cap(
    source_capacity: BaseUnits,
    remaining_refill_budget: BaseUnits,
    per_refill_limit: BaseUnits,
) -> BaseUnits:
    """Return the maximum refill allowed by source capacity and both limits."""

    capacity = _require_base_units(source_capacity, "source_capacity")
    remaining = _require_base_units(remaining_refill_budget, "remaining_refill_budget")
    per_refill = _require_base_units(per_refill_limit, "per_refill_limit")
    return BaseUnits(min(capacity, remaining, per_refill))


def decide_refill(
    request: ApprovedRequest,
    wallet: WalletState,
    source: WalletState,
    policy: PolicyView,
    used_today: BaseUnits,
    protected_other: BaseUnits,
    *,
    source_protected: BaseUnits,
) -> RefillDecision:
    """Apply the BR-032 refill decision table for one approved request.

    ``protected_other`` belongs to the paying wallet and ``source_protected``
    to the source wallet (its reservations and holds, ``R_T + L_T``). Source
    capacity also protects the source wallet's configured buffer.
    """

    refill_used_today = _require_base_units(used_today, "used_today")
    protected = _require_base_units(protected_other, "protected_other")
    source_held = _require_base_units(source_protected, "source_protected")

    # BR-012/BR-036: a refill only moves funds from the source to the
    # request's paying wallet.
    if wallet.address != request.paying_wallet or source.address == wallet.address:
        return RefillDecision(kind="stop", amount=_ZERO, reason=WRONG_REFILL_TARGET)

    minimum = shortage(wallet, request.amount, protected)
    if minimum == 0:
        return RefillDecision(kind="none", amount=_ZERO, reason=NO_REFILL_REQUIRED)

    bound = refill_bound(wallet, request.amount)
    if minimum > bound:
        return RefillDecision(kind="stop", amount=_ZERO, reason=REFILL_BOUND)

    preferred = preferred_refill(wallet, request.amount, protected)
    bounded_preferred = BaseUnits(min(preferred, bound))
    remaining_daily = _non_negative_difference(policy.refill.daily, refill_used_today)
    capacity = source_capacity(source, source_held)
    refill_cap = cap(capacity, remaining_daily, policy.refill.per_request)

    if refill_cap >= bounded_preferred:
        return RefillDecision(
            kind="preferred",
            amount=bounded_preferred,
            reason=TARGET_REACHED,
        )
    if refill_cap >= minimum:
        return RefillDecision(
            kind="shortage",
            amount=minimum,
            reason=TARGET_NOT_REACHED,
        )

    # Limit checks precede liquidity checks in policy-engine section 6.4:
    # daily, then per-request, then source capacity.
    if remaining_daily < minimum:
        reason = OVER_REFILL_DAILY
    elif policy.refill.per_request < minimum:
        reason = OVER_REFILL_PER_REQUEST
    else:
        reason = SOURCE_INSUFFICIENT
    return RefillDecision(kind="stop", amount=_ZERO, reason=reason)


def liquidity_position(
    snapshot: Snapshot,
    requests: Sequence[ApprovedRequest],
    schedule: Schedule,
    policy: LiquidityPolicy,
) -> LiquidityPosition:
    """Calculate the reserves and liquidity available for one planning cycle.

    ``requests`` must contain the approved, unpaid obligations for this cycle.
    The schedule determines whether an exact early-payment amount will be used;
    an obligation absent from the schedule is reserved at its standard amount.
    """

    if not isinstance(snapshot, Snapshot):
        raise TypeError("snapshot must be Snapshot")
    if not isinstance(schedule, Schedule):
        raise TypeError("schedule must be Schedule")
    if not isinstance(policy, LiquidityPolicy):
        raise TypeError("policy must be LiquidityPolicy")
    if not isinstance(snapshot.safe_usdc, BaseUnits):
        raise TypeError("snapshot.safe_usdc must be BaseUnits")
    if not isinstance(snapshot.a_usdc, BaseUnits):
        raise TypeError("snapshot.a_usdc must be BaseUnits")
    if not isinstance(snapshot.pool_available, BaseUnits):
        raise TypeError("snapshot.pool_available must be BaseUnits")

    scheduled_days: dict[str, int] = {}
    for item in schedule.items:
        if item.request_id in scheduled_days:
            raise ValueError(f"schedule contains duplicate request {item.request_id!r}")
        scheduled_days[item.request_id] = item.day

    request_ids = {request.id for request in requests}
    unknown_scheduled = set(scheduled_days) - request_ids
    if unknown_scheduled:
        raise ValueError("schedule contains requests absent from the approved request set")

    horizon_end = snapshot.day + policy.reserve_horizon_days
    payment_reserve = 0
    seen_request_ids: set[str] = set()
    for request in requests:
        if request.id in seen_request_ids:
            raise ValueError(f"approved request set contains duplicate id {request.id!r}")
        seen_request_ids.add(request.id)
        if request.terms.net_due_day > horizon_end:
            continue

        pay_day = scheduled_days.get(request.id)
        amount = request.amount
        if (
            pay_day is not None
            and request.early_amount is not None
            and request.early_pay_by is not None
            and pay_day <= request.early_pay_by
        ):
            amount = request.early_amount
        payment_reserve += int(amount)

    safe_floor = snapshot.source.buffer
    required = (
        payment_reserve
        + int(safe_floor)
        + int(policy.debt_service_reserve)
        + int(policy.execution_holds)
    )
    available_for_supply = max(0, int(snapshot.safe_usdc) - required)
    accessible_liquidity = int(snapshot.safe_usdc) + min(
        int(snapshot.a_usdc), int(snapshot.pool_available)
    )

    return LiquidityPosition(
        payment_reserve=BaseUnits(payment_reserve),
        safe_floor=safe_floor,
        debt_service_reserve=policy.debt_service_reserve,
        execution_holds=policy.execution_holds,
        required_safe_reserve=BaseUnits(required),
        available_for_supply=BaseUnits(available_for_supply),
        accessible_liquidity=BaseUnits(accessible_liquidity),
    )


def decide_liquidity(
    snapshot: Snapshot,
    requests: Sequence[ApprovedRequest],
    schedule: Schedule,
    policy: LiquidityPolicy,
) -> LiquidityDecision:
    """Choose no action, SUPPLY, or a reserve-restoring WITHDRAW.

    A partial withdrawal is surfaced as ``INSUFFICIENT_LIQUIDITY`` together
    with its remaining shortfall so callers can request an unauthorized borrow
    proposal separately; this function never creates a borrow operation.
    """

    position = liquidity_position(snapshot, requests, schedule, policy)
    deficit = max(
        0,
        int(position.required_safe_reserve) - int(snapshot.safe_usdc),
    )
    if deficit > 0:
        target = (deficit * 105 + 99) // 100
        withdrawal = min(target, int(snapshot.a_usdc), int(snapshot.pool_available))
        shortfall = max(0, deficit - withdrawal)
        if shortfall:
            return LiquidityDecision(
                kind="INSUFFICIENT_LIQUIDITY",
                amount=BaseUnits(withdrawal),
                shortfall=BaseUnits(shortfall),
                reason=INSUFFICIENT_LIQUIDITY,
                position=position,
            )
        return LiquidityDecision(
            kind="WITHDRAW",
            amount=BaseUnits(withdrawal),
            reason=RESERVE_DEFICIT,
            position=position,
        )

    remaining_daily = max(
        0,
        int(policy.supply.daily) - int(policy.supply_used_today),
    )
    supply_amount = min(
        int(position.available_for_supply),
        int(policy.supply.per_request),
        remaining_daily,
    )
    if supply_amount >= int(policy.min_supply):
        return LiquidityDecision(
            kind="SUPPLY",
            amount=BaseUnits(supply_amount),
            reason=SUPPLY_AVAILABLE,
            position=position,
        )

    return LiquidityDecision(
        kind="NONE",
        amount=_ZERO,
        reason=BELOW_MIN_SUPPLY,
        position=position,
    )
