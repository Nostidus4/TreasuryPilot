"""Request selection and the idempotent plan claim behind the execution cycle (EXE-004)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

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


class DbScheduleProvider:
    """First open-window request in due-date order (BR-052).

    shortcut: reads Approved requests directly instead of a persisted M07 schedule (no
    `schedules` table yet); the engine still orders and prices the plan, this only picks who.
    """

    def __init__(self, lead_time: timedelta = timedelta(hours=24)) -> None:
        self.lead_time = lead_time

    async def next_eligible_request(
        self, connection: asyncpg.Connection, treasury_id: uuid.UUID, *, now: datetime
    ) -> RequestSelection:
        rows = await connection.fetch(_CANDIDATES, treasury_id, now - REPLAN_COOLDOWN)
        for order, row in enumerate(rows):
            terms = PaymentTerms.model_validate(as_json(row["terms"]))
            day = datetime.combine(row["due_at"], datetime.min.time(), UTC)
            if terms.discount_deadline_day is not None:
                day = min(day, datetime.fromtimestamp(terms.discount_deadline_day * 86_400, UTC))
            if now >= day - self.lead_time:
                return RequestSelection(ScheduledRequest(row["id"], day, order))
        return RequestSelection(None)


class DbPlanStarter:
    """Claim a `Draft` plan (unique per open request) and hand it to the planning task."""

    def __init__(self, enqueue: Callable[[uuid.UUID], None]) -> None:
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
        self.enqueue(plan_id)
        return True
