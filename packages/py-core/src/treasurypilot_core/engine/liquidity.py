"""Integer-only liquidity formulas from BR-032 and financial-engine section 6."""

from __future__ import annotations

from collections.abc import Sequence

from treasurypilot_core.domain import (
    ApprovedRequest,
    BorrowProposal,
    LiquidityDecision,
    LiquidityPolicy,
    LiquidityPosition,
    PolicyView,
    RefillDecision,
    Schedule,
    Snapshot,
    WalletState,
)
from treasurypilot_core.engine.payment_terms import _BASIS_POINTS_SCALE, _DAYS_PER_YEAR, pay_amount
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
OVER_SUPPLY_DAILY = "OVER_SUPPLY_DAILY"
OVER_SUPPLY_PER_TX = "OVER_SUPPLY_PER_TX"
WITHDRAWN_TODAY = "WITHDRAWN_TODAY"


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


def _used_today(snapshot: Snapshot, counter: str) -> int:
    return int(snapshot.used_today.get(counter, _ZERO))  # type: ignore[call-overload]


def liquidity_position(
    snapshot: Snapshot,
    requests: Sequence[ApprovedRequest],
    schedule: Schedule,
    policy: LiquidityPolicy,
) -> LiquidityPosition:
    """Calculate the reserves and liquidity available for one planning cycle.

    ``requests`` must contain the approved, unpaid obligations for this cycle.
    An obligation is reserved when it is due, or scheduled to be paid, on or before
    ``today + reserve_horizon_days`` (inclusive, as in section 15: "due day <= today
    + 30"). The schedule decides whether the exact early-payment amount is used; an
    obligation absent from the schedule is reserved at its standard amount.
    """

    # The floor is Safe T's buffer and the balance is Safe T's USDC, so both must
    # describe the same wallet.
    if snapshot.source.balance != snapshot.safe_usdc:
        raise ValueError("snapshot.source must be Safe T: its balance differs from safe_usdc")

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

        pay_day = scheduled_days.get(request.id)
        # An early payment can fall inside the horizon while its due day does not.
        reserve_day = request.terms.net_due_day
        if pay_day is not None:
            reserve_day = min(pay_day, reserve_day)
        if reserve_day > horizon_end:
            continue

        payment_reserve += int(request.amount if pay_day is None else pay_amount(request, pay_day))

    safe_floor = snapshot.source.buffer
    required = (
        payment_reserve
        + int(safe_floor)
        + int(policy.debt_service_reserve)
        + int(policy.execution_holds)
    )
    safe_usdc = int(snapshot.safe_usdc)
    return LiquidityPosition(
        payment_reserve=BaseUnits(payment_reserve),
        safe_floor=safe_floor,
        debt_service_reserve=policy.debt_service_reserve,
        execution_holds=policy.execution_holds,
        required_safe_reserve=BaseUnits(required),
        deficit=BaseUnits(max(0, required - safe_usdc)),
        available_for_supply=BaseUnits(max(0, safe_usdc - required)),
        accessible_liquidity=BaseUnits(
            safe_usdc + min(int(snapshot.a_usdc), int(snapshot.pool_available))
        ),
    )


def decide_liquidity(
    snapshot: Snapshot,
    requests: Sequence[ApprovedRequest],
    schedule: Schedule,
    policy: LiquidityPolicy,
) -> LiquidityDecision:
    """Choose no action, SUPPLY, or a reserve-restoring WITHDRAW (section 15).

    A partial withdrawal is surfaced as ``INSUFFICIENT_LIQUIDITY`` together
    with its remaining shortfall so callers can request an unauthorized borrow
    proposal separately; this function never creates a borrow operation.
    """

    position = liquidity_position(snapshot, requests, schedule, policy)
    deficit = int(position.deficit)
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

    def none(reason: str) -> LiquidityDecision:
        return LiquidityDecision(kind="NONE", amount=_ZERO, reason=reason, position=position)

    # Section 15 compares min_supply with AvailableForSupply, before the caps.
    available_for_supply = int(position.available_for_supply)
    if available_for_supply == 0 or available_for_supply < int(policy.min_supply):
        return none(BELOW_MIN_SUPPLY)
    # The 5% withdraw margin would otherwise be supplied straight back the same day.
    if _used_today(snapshot, "withdraw") > 0:
        return none(WITHDRAWN_TODAY)
    remaining_daily = max(0, int(policy.supply.daily) - _used_today(snapshot, "supply"))
    if remaining_daily == 0:
        return none(OVER_SUPPLY_DAILY)
    if policy.supply.per_request == 0:
        return none(OVER_SUPPLY_PER_TX)
    return LiquidityDecision(
        kind="SUPPLY",
        amount=BaseUnits(
            min(available_for_supply, int(policy.supply.per_request), remaining_daily)
        ),
        reason=SUPPLY_AVAILABLE,
        position=position,
    )


_HEALTH_FACTOR_ONE = 10**18
# Advisory only: below this the reason warns about liquidation risk; no decision changes.
HEALTH_FACTOR_WARNING = 11 * 10**17


def propose_borrow(snapshot: Snapshot, deficit: BaseUnits, until_day: int) -> BorrowProposal:
    """Estimate a borrow for an uncovered shortfall without adding an executable action.

    Costs use integer base units and simple interest. Health factor after borrowing is
    estimated from the current health factor and debt; it remains unknown when the
    snapshot does not contain an existing debt position.
    """

    amount = int(deficit)
    if amount <= 0:
        raise ValueError("borrow proposal requires a positive deficit")
    if until_day < snapshot.day:
        raise ValueError("repayment day cannot precede the snapshot day")

    days = until_day - snapshot.day
    # Same simple-interest basis as the lost-interest term in request_value.
    denominator = _BASIS_POINTS_SCALE * _DAYS_PER_YEAR
    borrow_cost = amount * int(snapshot.borrow_rate_bps) * days // denominator
    withdraw_cost = amount * int(snapshot.supply_rate_bps) * days // denominator

    health_factor_before = snapshot.health_factor
    health_factor_after: int | None = None
    if snapshot.health_factor is not None and snapshot.debt > 0:
        health_factor_after = (
            int(snapshot.health_factor) * int(snapshot.debt) // (int(snapshot.debt) + amount)
        )

    # The cost comparison is the proposal's purpose (F-069), so it always leads; the
    # health-factor note follows as a second sentence.
    if borrow_cost < withdraw_cost:
        reason = "Estimated borrowing cost is lower than the supply interest lost by withdrawing."
    elif borrow_cost > withdraw_cost:
        reason = "Estimated borrowing cost is higher than the supply interest lost by withdrawing."
    else:
        reason = "Estimated borrowing cost equals the supply interest lost by withdrawing."
    if health_factor_after is None:
        reason += (
            " Health factor after borrowing is unknown because the snapshot has no existing"
            " debt position."
        )
    elif health_factor_after < _HEALTH_FACTOR_ONE:
        reason += (
            " Borrowing would put the estimated health factor below 1.0 and requires risk review."
        )
    elif health_factor_after < HEALTH_FACTOR_WARNING:
        reason += " The estimated health factor after borrowing is below 1.1; review the liquidation risk."

    return BorrowProposal(
        amount=BaseUnits(amount),
        cost_to_repayment=BaseUnits(borrow_cost),
        withdraw_cost=BaseUnits(withdraw_cost),
        health_factor_before=health_factor_before,
        health_factor_after=health_factor_after,
        reason=reason,
    )
