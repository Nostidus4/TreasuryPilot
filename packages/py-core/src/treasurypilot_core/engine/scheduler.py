"""Deterministic baseline scheduler using earliest-due-first ordering."""

from __future__ import annotations

from collections.abc import Sequence

from treasurypilot_core.domain import (
    ApprovedRequest,
    Infeasible,
    PolicyView,
    Schedule,
    ScheduledItem,
    Snapshot,
)
from treasurypilot_core.engine.liquidity import decide_refill
from treasurypilot_core.engine.payment_terms import pay_amount, request_value
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy.reason_codes import PolicyReasonCode

_ZERO = BaseUnits(0)
# M07-D3: the rolling horizon always spans 30 UTC days, so a request that cannot be paid
# by its due day (cooling, caps, source) is still scheduled late rather than dropped.
HORIZON_DAYS = 30
# M07-D9: reported by the scheduler for requests above the per-request cap.
NEEDS_EXCEPTION = "NEEDS_EXCEPTION"

# Which constraint to show in the "Why" panel for each blocking reason.
_BINDING = {
    NEEDS_EXCEPTION: "PAY_PER_REQUEST_CAP",
    PolicyReasonCode.PAYEE_UNKNOWN: "PAYEE_UNKNOWN",
    PolicyReasonCode.PAYEE_COOLING: "PAYEE_COOLING",
    PolicyReasonCode.OVER_DAILY_LIMIT: "PAY_DAILY_CAP",
    PolicyReasonCode.OVER_REFILL_DAILY: "REFILL_DAILY_CAP",
    PolicyReasonCode.OVER_REFILL_PER_REQUEST: "REFILL_PER_REQUEST_CAP",
    PolicyReasonCode.REFILL_BOUND: "REFILL_BOUND",
    PolicyReasonCode.SOURCE_INSUFFICIENT: "SOURCE_CAPACITY",
    PolicyReasonCode.WRONG_REFILL_TARGET: "WRONG_REFILL_TARGET",
}


def _needs_exception(request: ApprovedRequest, day: int, policy: PolicyView) -> bool:
    # Checked against the amount actually paid that day: an early amount can fit
    # under the cap while the standard amount does not.
    return pay_amount(request, day) > policy.pay.per_request and not request.exception_granted


def _deadline_feasible(request: ApprovedRequest, snapshot: Snapshot, policy: PolicyView) -> bool:
    """Whether any solver could have paid ``request`` by its due day (objective term 2)."""

    due = request.terms.net_due_day
    active_day = snapshot.payee_active_day.get(request.payee)
    return (
        active_day is not None
        and due >= max(snapshot.day, active_day)
        and not _needs_exception(request, due, policy)
    )


def schedule_edf(
    requests: Sequence[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
) -> Schedule:
    """Build the rolling-horizon B1 schedule in due-day and approval order (section 8.3).

    Requests that do not fit today remain eligible on following days. The
    scheduler carries wallet balances, source drawdown, and daily usage forward
    so a later payment cannot spend the same funds twice. Ties on
    ``(net_due_day, approved_seq)`` are broken by request id, so identical inputs
    always give the same schedule (M07-D7).
    """

    ordered = sorted(
        requests,
        key=lambda request: (request.terms.net_due_day, request.approved_seq, request.id),
    )
    if not ordered:
        return Schedule(
            items=(),
            infeasible=(),
            objective=(0, 0, 0, 0),
            binding=(),
            solver="EDF",
            status="OPTIMAL",
        )
    if len({request.id for request in ordered}) != len(ordered):
        raise ValueError("request ids must be unique")

    for request in ordered:
        if request.paying_wallet not in snapshot.operational:
            raise ValueError(f"no operational wallet for request {request.id!r}")

    horizon_end = snapshot.day + HORIZON_DAYS - 1
    operational = dict(snapshot.operational)
    source = snapshot.source
    scheduled: list[ScheduledItem] = []
    blocked_reason: dict[str, str] = {}
    binding: set[str] = set()
    transaction_count = 0

    def block(request: ApprovedRequest, reason: str, *, overrides: bool = False) -> None:
        # The first blocker is reported, except for permanent ones that explain the outcome.
        if overrides:
            blocked_reason[request.id] = reason
        else:
            blocked_reason.setdefault(request.id, reason)
        binding.add(_BINDING[reason])

    remaining: list[ApprovedRequest] = []
    for request in ordered:
        # A payee missing from the snapshot was never read: never assume it is active.
        if request.payee not in snapshot.payee_active_day:
            block(request, PolicyReasonCode.PAYEE_UNKNOWN, overrides=True)
        else:
            remaining.append(request)

    for day in range(snapshot.day, horizon_end + 1):
        pay_used = int(snapshot.used_today["pay"]) if day == snapshot.day else 0
        refill_used = int(snapshot.used_today["refill"]) if day == snapshot.day else 0
        next_remaining: list[ApprovedRequest] = []

        for request in remaining:
            if _needs_exception(request, day, policy):
                # The paid amount only grows over time (early → standard), so this is final.
                block(request, NEEDS_EXCEPTION, overrides=True)
                continue

            if day < snapshot.payee_active_day[request.payee]:
                block(request, PolicyReasonCode.PAYEE_COOLING)
                next_remaining.append(request)
                continue

            amount = pay_amount(request, day)
            if pay_used + int(amount) > int(policy.pay.daily):
                block(request, PolicyReasonCode.OVER_DAILY_LIMIT)
                next_remaining.append(request)
                continue

            wallet = operational[request.paying_wallet]
            refill_request = request.model_copy(
                update={"amount": amount, "early_amount": None, "early_pay_by": None}
            )
            refill = decide_refill(
                refill_request,
                wallet,
                source,
                policy,
                BaseUnits(refill_used),
                _ZERO,
                source_protected=_ZERO,
            )
            if refill.kind == "stop":
                block(request, refill.reason)
                next_remaining.append(request)
                continue

            refill_amount = int(refill.amount)
            wallet_balance = int(wallet.balance) + refill_amount - int(amount)
            # decide_refill guarantees the buffer when it does not stop.
            assert wallet_balance >= int(wallet.buffer)

            operational[request.paying_wallet] = wallet.model_copy(
                update={"balance": BaseUnits(wallet_balance)}
            )
            if refill_amount:
                source = source.model_copy(
                    update={"balance": BaseUnits(int(source.balance) - refill_amount)}
                )
            pay_used += int(amount)
            refill_used += refill_amount
            scheduled.append(
                ScheduledItem(
                    request_id=request.id,
                    day=day,
                    refill=BaseUnits(refill_amount),
                    value=request_value(request, day, supply_rate_bps=snapshot.supply_rate_bps),
                )
            )
            transaction_count += 1 + int(refill_amount > 0)

        remaining = next_remaining
        if not remaining:
            break

    scheduled_by_id = {item.request_id: item for item in scheduled}
    infeasible: list[Infeasible] = []
    for request in ordered:
        if request.id in scheduled_by_id:
            continue
        reason = blocked_reason[request.id]
        if reason == NEEDS_EXCEPTION:
            first_day = max(snapshot.day, snapshot.payee_active_day.get(request.payee, 0))
            potential_value = request_value(
                request, first_day, supply_rate_bps=snapshot.supply_rate_bps
            )
            detail = (
                "Approved request exceeds the per-request pay cap; Owner exception required. "
                f"Potential value if granted: {potential_value}."
            )
        else:
            detail = (
                f"No feasible payment day in the {HORIZON_DAYS}-day horizon; "
                f"first blocker: {reason}."
            )
        infeasible.append(Infeasible(request_id=request.id, reason=reason, detail=detail))

    # Only deadlines some schedule could have met count against EDF (objective term 2).
    missed_deadlines = sum(
        1
        for request in ordered
        if _deadline_feasible(request, snapshot, policy)
        and (
            request.id not in scheduled_by_id
            or scheduled_by_id[request.id].day > request.terms.net_due_day
        )
    )
    total_value = sum(item.value for item in scheduled)
    return Schedule(
        items=tuple(scheduled),
        infeasible=tuple(infeasible),
        objective=(0, missed_deadlines, -total_value, transaction_count),
        binding=tuple(sorted(binding)),
        solver="EDF",
        status="FEASIBLE",
    )
