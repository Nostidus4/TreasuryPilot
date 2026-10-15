"""Deterministic daily balance projections based on the EDF schedule."""

from __future__ import annotations

from collections.abc import Sequence

from treasurypilot_core.domain import (
    ApprovedRequest,
    Forecast,
    ForecastDay,
    ForecastRefill,
    PolicyView,
    ScheduledItem,
    Snapshot,
)
from treasurypilot_core.engine.payment_terms import amount_due, pay_amount
from treasurypilot_core.engine.scheduler import HORIZON_DAYS, schedule_edf
from treasurypilot_core.money import BaseUnits

# Never project past what the scheduler plans.
_MAX_FORECAST_DAYS = HORIZON_DAYS


def forecast(
    snapshot: Snapshot,
    requests: Sequence[ApprovedRequest],
    policy: PolicyView,
    days: int = 7,
) -> Forecast:
    """Project end-of-day wallet balances and safe refill suggestions.

    The projection replays the scheduler's payment and refill decisions in their
    original order. This keeps same-day wallet balances consistent with the schedule
    and preserves the refill limits and source buffer enforced by the engine.

    The scheduler never plans a payment that breaks a buffer, so the projection also
    charges each wallet with what it still owes: an obligation due on or before a day
    and not paid by it counts against its paying wallet (``amount_due``, late fees
    included) when deciding buffer hits, and is reported as ``unpaid_due``.
    """

    if not isinstance(snapshot, Snapshot):
        raise TypeError("snapshot must be Snapshot")
    if isinstance(days, bool) or not isinstance(days, int):
        raise TypeError("days must be an integer")
    if not 1 <= days <= _MAX_FORECAST_DAYS:
        raise ValueError(f"days must be between 1 and {_MAX_FORECAST_DAYS}")

    source = snapshot.source
    # Same rule as liquidity_position: Safe T is the snapshot source.
    if source.balance != snapshot.safe_usdc:
        raise ValueError("snapshot.source must be Safe T: its balance differs from safe_usdc")
    balances = {source.address: int(source.balance)}
    buffers = {source.address: int(source.buffer)}
    for wallet in snapshot.operational.values():
        if wallet.address in balances:
            raise ValueError("wallet addresses in a snapshot must be unique")
        balances[wallet.address] = int(wallet.balance)
        buffers[wallet.address] = int(wallet.buffer)

    plan = schedule_edf(requests, snapshot, policy)
    request_by_id = {request.id: request for request in requests}
    scheduled_by_day: dict[int, list[ScheduledItem]] = {}
    paid_day = {item.request_id: item.day for item in plan.items}
    window_end = snapshot.day + days
    for item in plan.items:
        if snapshot.day <= item.day < window_end:
            # Schedule.items are emitted in the scheduler's decision order. Keep
            # that order: one payment can consume a refill made for an earlier item.
            scheduled_by_day.setdefault(item.day, []).append(item)

    # Only obligations due inside the window can be unpaid on a window day.
    overdue_candidates = [r for r in requests if r.terms.net_due_day < window_end]
    daily: list[ForecastDay] = []
    hit_days: dict[str, list[int]] = {address: [] for address in balances}
    shortfall_days: list[int] = []
    for day in range(snapshot.day, window_end):
        refills: list[ForecastRefill] = []
        for item in scheduled_by_day.get(day, []):
            request = request_by_id.get(item.request_id)
            if request is None:
                raise ValueError(f"schedule contains unknown request {item.request_id!r}")
            wallet = snapshot.operational[request.paying_wallet]
            source_address = item.refill_from or source.address
            target_address = wallet.address
            refill_amount = int(item.refill)
            if refill_amount:
                # decide_refill keeps the source buffer; the replay cannot break it.
                assert balances[source_address] - refill_amount >= buffers[source_address]
                balances[source_address] -= refill_amount
                balances[target_address] += refill_amount
                refills.append(
                    ForecastRefill(
                        day=day,
                        request_id=request.id,
                        source_wallet=source_address,
                        target_wallet=target_address,
                        amount=BaseUnits(refill_amount),
                    )
                )

            payment = int(pay_amount(request, day))
            assert balances[target_address] >= payment  # guaranteed by the scheduler
            balances[target_address] -= payment

        owed: dict[str, int] = {}
        for request in overdue_candidates:
            if request.terms.net_due_day <= day and paid_day.get(request.id, day + 1) > day:
                address = snapshot.operational[request.paying_wallet].address
                owed[address] = owed.get(address, 0) + int(amount_due(request, day))
        unpaid_due = sum(owed.values())
        if unpaid_due:
            shortfall_days.append(day)
        buffer_hits = tuple(
            sorted(
                address
                for address, balance in balances.items()
                if balance - owed.get(address, 0) < buffers[address]
            )
        )
        for address in buffer_hits:
            hit_days[address].append(day)
        daily.append(
            ForecastDay(
                day=day,
                balances={address: BaseUnits(balance) for address, balance in balances.items()},
                buffer_hit_wallets=buffer_hits,
                suggested_refills=tuple(refills),
                unpaid_due=BaseUnits(unpaid_due),
            )
        )

    return Forecast(
        days=tuple(daily),
        buffer_hit_days={address: tuple(days_hit) for address, days_hit in hit_days.items()},
        shortfall_days=tuple(shortfall_days),
        unplanned_request_ids=tuple(item.request_id for item in plan.infeasible),
        deferred_request_ids=tuple(
            item.request_id for item in plan.items if item.day >= window_end
        ),
    )
