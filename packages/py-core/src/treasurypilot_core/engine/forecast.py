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
from treasurypilot_core.engine.scheduler import schedule_edf
from treasurypilot_core.money import BaseUnits

_MAX_FORECAST_DAYS = 30


def forecast(
    snapshot: Snapshot,
    requests: Sequence[ApprovedRequest],
    policy: PolicyView,
    days: int = 7,
) -> Forecast:
    """Project each wallet's end-of-day balance and safe refill suggestions.

    Approved obligations are scheduled by the deterministic EDF baseline. The
    projection applies only those schedule items that fall within ``days``;
    refill amounts therefore already respect source capacity, buffers, contract
    bounds, and daily/per-request refill limits.
    """

    if isinstance(days, bool) or not isinstance(days, int):
        raise TypeError("days must be an integer")
    if not 1 <= days <= _MAX_FORECAST_DAYS:
        raise ValueError(f"days must be between 1 and {_MAX_FORECAST_DAYS}")
    if not isinstance(snapshot, Snapshot):
        raise TypeError("snapshot must be Snapshot")

    plan = schedule_edf(requests, snapshot, policy)
    request_by_id = {request.id: request for request in requests}
    balances: dict[str, int] = {snapshot.source.address: int(snapshot.source.balance)}
    buffers: dict[str, int] = {snapshot.source.address: int(snapshot.source.buffer)}
    for wallet in snapshot.operational.values():
        if wallet.address in balances:
            raise ValueError("wallet addresses in a snapshot must be unique")
        balances[wallet.address] = int(wallet.balance)
        buffers[wallet.address] = int(wallet.buffer)

    items_by_day: dict[int, list[ScheduledItem]] = {}
    for item in plan.items:
        if snapshot.day <= item.day < snapshot.day + days:
            items_by_day.setdefault(item.day, []).append(item)

    daily: list[ForecastDay] = []
    hit_days: dict[str, list[int]] = {address: [] for address in balances}
    for day in range(snapshot.day, snapshot.day + days):
        refills: list[ForecastRefill] = []
        for item in sorted(items_by_day.get(day, []), key=lambda scheduled: scheduled.request_id):
            request = request_by_id.get(item.request_id)
            if request is None:
                raise ValueError(f"schedule contains unknown request {item.request_id!r}")
            wallet = snapshot.operational[request.paying_wallet]
            source_address = snapshot.source.address
            target_address = wallet.address
            refill_amount = int(item.refill)
            if refill_amount:
                if balances[source_address] < refill_amount:
                    raise ValueError("schedule exceeds the projected source balance")
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

            pay_amount = request.amount
            if (
                request.early_amount is not None
                and request.early_pay_by is not None
                and day <= request.early_pay_by
            ):
                pay_amount = request.early_amount
            if balances[target_address] < int(pay_amount):
                raise ValueError("schedule exceeds the projected operational balance")
            balances[target_address] -= int(pay_amount)

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
            )
        )

    return Forecast(
        days=tuple(daily),
        buffer_hit_days={address: tuple(days_hit) for address, days_hit in hit_days.items()},
        unplanned_request_ids=tuple(item.request_id for item in plan.infeasible),
    )
