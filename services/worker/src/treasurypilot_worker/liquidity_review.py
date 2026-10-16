"""Review items of a liquidity plan (EXE-014).

A liquidity plan serves no request, so its items are keyed by plan (``ck_review_items_subject``,
migration 0089): one open item per (plan, type). The same queue, roles and actions as a request
item; the API resolves them like any other.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.ids import uuid7

# type -> (assigned roles, SLA); the only types the schema accepts for a plan-keyed item
_ROUTES: dict[str, tuple[list[str], timedelta]] = {
    "FEE_APPROVAL": (["Finance", "Operator", "Owner"], timedelta(hours=24)),
    "INFRA": (["Operator"], timedelta(hours=48)),
    "UNCERTAIN_TX": (["Operator", "Owner"], timedelta(hours=1)),
}


async def open_liquidity_review(
    connection: asyncpg.Connection,
    *,
    plan_id: uuid.UUID,
    kind: str,
    primary_code: str,
    reason_codes: tuple[str, ...] = (),
    completed_steps: list[dict[str, object]] | None = None,
    fee_estimate_wei: int | None = None,
    now: datetime | None = None,
) -> None:
    """Open the item for ``plan_id`` unless one of this type is already open (idempotent).

    Any type the schema does not accept for a plan (a policy block, an AI rejection) is filed as
    ``INFRA`` with its own code, so an Operator still sees the stop.
    """

    kind = kind if kind in _ROUTES else "INFRA"
    roles, sla = _ROUTES[kind]
    await connection.execute(
        "INSERT INTO review_items (id, org_id, treasury_id, request_id, request_version, plan_id, "
        "type, primary_code, reason_codes, completed_steps, assigned_roles, status, sla_due_at, "
        "evidence_resolved, fee_estimate_wei) SELECT $1, p.org_id, p.treasury_id, NULL, NULL, p.id, "
        "$2, $3, $4, $5::jsonb, $6, 'Open', $7, false, $8 FROM plans p "
        "WHERE p.id = $9 AND p.request_id IS NULL "
        "ON CONFLICT (plan_id, type) WHERE status = 'Open' AND request_id IS NULL "
        "AND mandate_version_id IS NULL DO NOTHING",
        uuid7(),
        kind,
        primary_code,
        list(reason_codes or (primary_code,)),
        json.dumps(completed_steps or []),
        roles,
        (now or datetime.now(UTC)) + sla,
        fee_estimate_wei,
        plan_id,
    )
