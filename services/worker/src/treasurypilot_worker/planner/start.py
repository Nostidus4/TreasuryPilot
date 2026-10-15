"""Request selection and the idempotent plan claim behind the execution cycle (EXE-004)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.domain import PaymentTerms
from treasurypilot_core.ids import uuid7
from treasurypilot_worker.planner.inputs import as_json
from treasurypilot_worker.trigger.cycles import RequestSelection, ScheduledRequest

# A plan that ended without a result (deferred, fee-deferred, crashed) is retried after this.
REPLAN_COOLDOWN = timedelta(minutes=15)
DRAFT_TIMEOUT = timedelta(minutes=10)
_OPEN = "'Draft', 'Blocked', 'AwaitingAuthority', 'AwaitingFeeAcceptance', 'Attested', 'Executing'"
_CANDIDATES = f"""
SELECT pr.id, pr.due_at, pr.terms
FROM payment_requests pr
WHERE pr.treasury_id = $1 AND pr.status IN ('Approved', 'Scheduled')
  AND pr.terms IS NOT NULL AND pr.terms_confirmed_by IS NOT NULL
  AND pr.onchain_request_id IS NOT NULL AND pr.paying_wallet_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM approvals a WHERE a.request_id = pr.id
              AND a.revision = pr.current_revision AND a.status = 'Valid')
  AND NOT EXISTS (SELECT 1 FROM plans p WHERE p.request_id = pr.id
                  AND (p.status IN ({_OPEN}) OR p.created_at > $2))
ORDER BY pr.due_at, pr.created_at, pr.id
LIMIT 100
"""


SCHEDULE_RETENTION = timedelta(days=30)


def _pay_by(due_at: date, terms: PaymentTerms) -> datetime:
    day = datetime.combine(due_at, datetime.min.time(), UTC)
    if terms.discount_deadline_day is not None:
        day = min(day, datetime.fromtimestamp(terms.discount_deadline_day * 86_400, UTC))
    return day


class DbScheduleWriter:
    """Append the advisory `schedules` row: requests in deadline order with window start.

    shortcut: solver "DUE_DATE" is the order the provider uses, not the M07 EDF/CP-SAT run
    (those labels stay M07's); items are {requestId, order, scheduledFor, deadline}, not the
    spec's {requestId, day, value, refill}. Swap in the engine schedule when the provider reads it.
    Empty schedules are not stored while the latest row is also empty (nothing to record).
    """

    def __init__(self, lead_time: timedelta = timedelta(hours=24)) -> None:
        self.lead_time = lead_time

    async def refresh_treasury(
        self, connection: asyncpg.Connection, treasury_id: uuid.UUID, *, now: datetime
    ) -> bool:
        org_id = await connection.fetchval(
            "SELECT org_id FROM treasuries WHERE id = $1 AND status IN ('Ready', 'Paused')",
            treasury_id,
        )
        if org_id is None:
            return False
        items: list[dict[str, Any]] = []
        # Cooldown parameter is `now` (not `now - REPLAN_COOLDOWN`): the provider's `live` set filters it.
        for order, row in enumerate(await connection.fetch(_CANDIDATES, treasury_id, now)):
            deadline = _pay_by(row["due_at"], PaymentTerms.model_validate(as_json(row["terms"])))
            items.append(
                {
                    "requestId": str(row["id"]),
                    "order": order,
                    "scheduledFor": (deadline - self.lead_time).isoformat(),
                    "deadline": deadline.isoformat(),
                }
            )
        # M05 §5: Approved -> Scheduled (SYSTEM) once the window is open; far-future requests
        # stay Approved so they remain editable (the pipeline also moves them when a plan starts).
        open_ids = [
            uuid.UUID(item["requestId"])
            for item in items
            if now >= datetime.fromisoformat(item["scheduledFor"])
        ]
        for moved in await connection.fetch(
            "UPDATE payment_requests SET status = 'Scheduled', version = version + 1, "
            "updated_at = now() WHERE id = ANY($1::uuid[]) AND status = 'Approved' RETURNING id",
            open_ids,
        ):
            await connection.execute(
                'INSERT INTO request_status_events (id, request_id, "from", "to", actor_type, '
                "reason) VALUES ($1, $2, 'Approved', 'Scheduled', 'SYSTEM', 'schedule')",
                uuid7(),
                moved["id"],
            )
        latest = await connection.fetchval(
            "SELECT items FROM schedules WHERE treasury_id = $1 ORDER BY computed_at DESC LIMIT 1",
            treasury_id,
        )
        # Append-only, but an unchanged schedule is not a new row (96 identical rows a day).
        if (as_json(latest) if latest is not None else []) == items:
            return True
        await connection.execute(
            "INSERT INTO schedules (id, org_id, treasury_id, computed_at, solver, items) "
            "VALUES ($1, $2, $3, $4, 'DUE_DATE', $5::jsonb)",
            uuid7(),
            org_id,
            treasury_id,
            now,
            json.dumps(items),
        )
        # Retention: same transaction as the writer; keep 30 days of history per treasury.
        await connection.execute(
            "DELETE FROM schedules WHERE treasury_id = $1 AND computed_at < $2",
            treasury_id,
            now - SCHEDULE_RETENTION,
        )
        return True


class DbScheduleProvider:
    """First request of the current schedule whose window is open (spec §7.1/§8.1, BR-052).

    The schedule is refreshed first (no new row when unchanged), so an approval just made is
    in it without waiting for the 15-minute scheduling cycle, and the latest `schedules` row
    is always "today's" (never a stale row). Items in plan cooldown or with an open plan are skipped; a treasury
    with no schedule row has nothing to run.
    """

    def __init__(self, lead_time: timedelta = timedelta(hours=24)) -> None:
        self.lead_time = lead_time
        self._writer = DbScheduleWriter(lead_time)

    async def next_eligible_request(
        self, connection: asyncpg.Connection, treasury_id: uuid.UUID, *, now: datetime
    ) -> RequestSelection:
        # A plan waiting for a fee decision is stale once the policy was accepted after it was
        # made: free its request (it would otherwise stay open and block planning forever).
        await connection.execute(
            "UPDATE plans SET status = 'Expired', updated_at = now() "
            "WHERE treasury_id = $1 AND status = 'AwaitingFeeAcceptance' AND EXISTS ("
            "SELECT 1 FROM treasury_fee_policies f WHERE f.treasury_id = plans.treasury_id "
            "AND f.accepted_at IS NOT NULL AND f.superseded_at IS NULL "
            "AND f.accepted_at > plans.created_at)",
            treasury_id,
        )
        await self._writer.refresh_treasury(connection, treasury_id, now=now)
        rows = await connection.fetch(_CANDIDATES, treasury_id, now - REPLAN_COOLDOWN)
        live = {row["id"] for row in rows}
        rows = await connection.fetch(_CANDIDATES, treasury_id, now - REPLAN_COOLDOWN)
        live = {row["id"] for row in rows}
        latest = await connection.fetchval(
            "SELECT items FROM schedules WHERE treasury_id = $1 ORDER BY computed_at DESC LIMIT 1",
            treasury_id,
        )
        # The refresh above ran for a Ready/Paused treasury, so a row exists unless it was empty.
        items = as_json(latest) if latest is not None else []
        for order, item in enumerate(items):
            request_id = uuid.UUID(item["requestId"])
            if request_id in live and now >= datetime.fromisoformat(item["scheduledFor"]):
                deadline = datetime.fromisoformat(item["deadline"])
                return RequestSelection(ScheduledRequest(request_id, deadline, order))
        return RequestSelection(None)


class DbPlanStarter:
    """Claim a `Draft` plan (unique per open request) and hand it to the planning task."""

    def __init__(self, enqueue: Callable[[uuid.UUID, uuid.UUID], None]) -> None:
        self.enqueue = enqueue

    async def start(
        self,
        connection: asyncpg.Connection,
        treasury_id: uuid.UUID,
        request: ScheduledRequest,
        *,
        now: datetime,
    ) -> bool:
        # A crash between the claim and the final write leaves a Draft; free its request.
        await connection.execute(
            "UPDATE plans SET status = 'Expired', updated_at = now() "
            "WHERE treasury_id = $1 AND status = 'Draft' AND created_at < $2",
            treasury_id,
            now - DRAFT_TIMEOUT,
        )
        plan_id = await connection.fetchval(
            f"""
            INSERT INTO plans (id, org_id, treasury_id, request_id)
            SELECT $1, org_id, id, $3 FROM treasuries WHERE id = $2
            ON CONFLICT (request_id) WHERE status IN ({_OPEN}) DO NOTHING
            RETURNING id
            """,
            uuid7(),
            treasury_id,
            request.request_id,
        )
        if plan_id is None:
            return False
        self.enqueue(plan_id, treasury_id)
        return True
