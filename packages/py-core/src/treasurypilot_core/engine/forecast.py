"""Deterministic daily balance projections based on the EDF schedule."""

from __future__ import annotations

from collections.abc import Sequence

from treasurypilot_core.domain import (
    ApprovedRequest,
    Forecast,
    ForecastDay,
    ForecastRefill,
    PolicyView,
    Snapshot,
)
from treasurypilot_core.engine.scheduler import run_edf
from treasurypilot_core.money import BaseUnits

_MAX_FORECAST_DAYS = 30


def forecast(
    snapshot: Snapshot,
    requests: Sequence[ApprovedRequest],
    policy: PolicyView,
    days: int = 7,
) -> Forecast:
    """Project each wallet's end-of-day balance and safe refill suggestions.

    The EDF scheduler's own movements are replayed in the order it decided them, so
    the projection can never disagree with the schedule (amounts, early payments,
    refills that top a wallet up for a later payment). Obligations the schedule does
    not pay by their due day show up as ``unpaid_due`` and ``shortfall_days``, since
    the scheduler never lets a balance drop below a buffer.
    """

    if isinstance(days, bool) or not isinstance(days, int):
        raise TypeError("days must be an integer")
    if not 1 <= days <= _MAX_FORECAST_DAYS:
        raise ValueError(f"days must be between 1 and {_MAX_FORECAST_DAYS}")

    run = run_edf(requests, snapshot, policy)
    window_end = snapshot.day + days
    source = snapshot.source.address
    balances = {source: int(snapshot.source.balance)}
    buffers = {source: int(snapshot.source.buffer)}
    for wallet in snapshot.operational.values():
        balances[wallet.address] = int(wallet.balance)
        buffers[wallet.address] = int(wallet.buffer)

    paid_day = {item.request_id: item.day for item in run.schedule.items}
    movements_by_day: dict[int, list[ForecastRefill]] = {}
    daily: list[ForecastDay] = []
    hit_days: dict[str, list[int]] = {address: [] for address in balances}
    shortfall_days: list[int] = []
    pending = list(run.movements)
    for day in range(snapshot.day, window_end):
        refills = movements_by_day.setdefault(day, [])
        while pending and pending[0].day == day:
            movement = pending.pop(0)
            if movement.refill:
                balances[source] -= movement.refill
                balances[movement.wallet] += movement.refill
                refills.append(
                    ForecastRefill(
                        day=day,
                        request_id=movement.request_id,
                        source_wallet=source,
                        target_wallet=movement.wallet,
                        amount=BaseUnits(movement.refill),
                    )
                )
            balances[movement.wallet] -= movement.payment

        unpaid_due = sum(
            int(request.amount)
            for request in requests
            if request.terms.net_due_day <= day
            and (request.id not in paid_day or paid_day[request.id] > day)
        )
        if unpaid_due:
            shortfall_days.append(day)
        buffer_hits = sorted(
            address for address, balance in balances.items() if balance < buffers[address]
        )
        for address in buffer_hits:
            hit_days[address].append(day)
        daily.append(
            ForecastDay(
                day=day,
                balances={address: BaseUnits(balance) for address, balance in balances.items()},
                buffer_hit_wallets=tuple(buffer_hits),
                suggested_refills=tuple(refills),
                unpaid_due=BaseUnits(unpaid_due),
            )
        )

    return Forecast(
        days=tuple(daily),
        buffer_hit_days={address: tuple(days_hit) for address, days_hit in hit_days.items()},
        shortfall_days=tuple(shortfall_days),
        unplanned_request_ids=tuple(item.request_id for item in run.schedule.infeasible),
        deferred_request_ids=tuple(
            item.request_id for item in run.schedule.items if item.day >= window_end
        ),
    )
