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
    WalletState,
)
from treasurypilot_core.engine.liquidity import decide_refill
from treasurypilot_core.engine.payment_terms import request_value
from treasurypilot_core.money import BaseUnits

_ZERO = BaseUnits(0)
_MAX_HORIZON_DAYS = 30


def _payment_amount(request: ApprovedRequest, day: int) -> BaseUnits:
    if (
        request.early_amount is not None
        and request.early_pay_by is not None
        and day <= request.early_pay_by
    ):
        return request.early_amount
    return request.amount


def _remember_reason(reasons: dict[str, str], request_id: str, reason: str) -> None:
    reasons.setdefault(request_id, reason)


def schedule_edf(
    requests: Sequence[ApprovedRequest],
    snapshot: Snapshot,
    policy: PolicyView,
) -> Schedule:
    """Build the rolling-horizon B1 schedule in due-day and approval order.

    Requests that do not fit today remain eligible on following days. The
    scheduler carries wallet balances, source drawdown, and daily usage forward
    so a later payment cannot spend the same funds twice.
    """

    if not isinstance(snapshot, Snapshot):
        raise TypeError("snapshot must be Snapshot")
    if not isinstance(policy, PolicyView):
        raise TypeError("policy must be PolicyView")
    ordered = sorted(
        requests, key=lambda request: (request.terms.net_due_day, request.approved_seq)
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

    horizon_length = min(
        _MAX_HORIZON_DAYS,
        max(1, max(request.terms.net_due_day for request in ordered) - snapshot.day + 1),
    )
    horizon_end = snapshot.day + horizon_length - 1
    operational = dict(snapshot.operational)
    source_balance = int(snapshot.source.balance)
    pay_used: dict[int, int] = {}
    refill_used: dict[int, int] = {}
    scheduled: list[ScheduledItem] = []
    remaining = list(ordered)
    blocked_reason: dict[str, str] = {}
    binding: set[str] = set()
    transaction_count = 0

    for day in range(snapshot.day, horizon_end + 1):
        pay_used[day] = int(snapshot.used_today["pay"]) if day == snapshot.day else 0
        refill_used[day] = int(snapshot.used_today["refill"]) if day == snapshot.day else 0
        next_remaining: list[ApprovedRequest] = []

        for request in remaining:
            if request.amount > policy.pay.per_request and not request.exception_granted:
                blocked_reason[request.id] = "NEEDS_EXCEPTION"
                continue

            active_day = snapshot.payee_active_day.get(request.payee, snapshot.day)
            if day < active_day:
                _remember_reason(blocked_reason, request.id, "PAYEE_COOLING")
                next_remaining.append(request)
                binding.add("PAYEE_COOLING")
                continue

            pay_amount = _payment_amount(request, day)
            if pay_used[day] + int(pay_amount) > int(policy.pay.daily):
                _remember_reason(blocked_reason, request.id, "OVER_PAY_DAILY")
                next_remaining.append(request)
                binding.add("PAY_DAILY_CAP")
                continue

            wallet = operational[request.paying_wallet]
            source = WalletState(
                address=snapshot.source.address,
                balance=BaseUnits(source_balance),
                buffer=snapshot.source.buffer,
                target=snapshot.source.target,
            )
            refill_request = request.model_copy(
                update={"amount": pay_amount, "early_amount": None, "early_pay_by": None}
            )
            refill = decide_refill(
                refill_request,
                wallet,
                source,
                policy,
                BaseUnits(refill_used[day]),
                _ZERO,
                source_protected=_ZERO,
            )
            if refill.kind == "stop":
                _remember_reason(blocked_reason, request.id, refill.reason)
                next_remaining.append(request)
                if refill.reason == "OVER_REFILL_DAILY":
                    binding.add("REFILL_DAILY_CAP")
                elif refill.reason == "SOURCE_INSUFFICIENT":
                    binding.add("SOURCE_CAPACITY")
                continue

            refill_amount = int(refill.amount)
            wallet_balance = int(wallet.balance) + refill_amount - int(pay_amount)
            if wallet_balance < int(wallet.buffer):
                _remember_reason(blocked_reason, request.id, "SOURCE_INSUFFICIENT")
                next_remaining.append(request)
                binding.add("SOURCE_CAPACITY")
                continue

            operational[request.paying_wallet] = WalletState(
                address=wallet.address,
                balance=BaseUnits(wallet_balance),
                buffer=wallet.buffer,
                target=wallet.target,
            )
            source_balance -= refill_amount
            pay_used[day] += int(pay_amount)
            refill_used[day] += refill_amount
            value = request_value(
                request,
                day,
                supply_rate_bps=snapshot.supply_rate_bps,
            )
            scheduled.append(
                ScheduledItem(
                    request_id=request.id,
                    day=day,
                    refill=BaseUnits(refill_amount),
                    value=value,
                )
            )
            transaction_count += 1 + int(refill_amount > 0)

        remaining = next_remaining
        if not remaining:
            break

    scheduled_by_id = {item.request_id: item for item in scheduled}
    infeasible: list[Infeasible] = []
    for request in ordered:
        item = scheduled_by_id.get(request.id)
        if item is not None:
            continue
        reason = blocked_reason.get(request.id, "OUTSIDE_HORIZON")
        if reason == "NEEDS_EXCEPTION":
            detail = "Approved request exceeds the per-request pay cap; Owner exception required. "
            potential_value = request_value(
                request,
                max(snapshot.day, snapshot.payee_active_day.get(request.payee, snapshot.day)),
                supply_rate_bps=snapshot.supply_rate_bps,
            )
            detail += f"Potential value if granted: {potential_value}."
        else:
            detail = f"No feasible payment day in the {horizon_length}-day horizon; first blocker: {reason}."
        infeasible.append(Infeasible(request_id=request.id, reason=reason, detail=detail))

    missed_deadlines = sum(
        1
        for request in ordered
        if request.id not in scheduled_by_id
        or scheduled_by_id[request.id].day > request.terms.net_due_day
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
