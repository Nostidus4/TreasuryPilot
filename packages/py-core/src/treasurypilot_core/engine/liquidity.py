"""Integer-only liquidity formulas from BR-032 and financial-engine section 6."""

from treasurypilot_core.domain import (
    ApprovedRequest,
    PolicyView,
    RefillDecision,
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
