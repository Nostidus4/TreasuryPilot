"""Circuit-breaker rules and trip history (RCV-006). The worker evaluates; the Owner may only tighten."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.events import AuditEvent, log_audit_event
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_member, require_role
from treasurypilot_api.recovery.models import CircuitEvent, CircuitRuleRow
from treasurypilot_api.treasury.models import Treasury
from treasurypilot_core.circuit import COOLDOWN_SECONDS, SPECS, CircuitRule, validate_tightening

router = APIRouter(
    prefix="/v1/orgs/{organization_id}/treasuries/{treasury_id}/circuit", tags=["circuit"]
)


class CircuitRuleView(ApiModel):
    rule: CircuitRule
    threshold: int
    window_seconds: int
    action: str
    tunable: bool
    cooldown_seconds: int = COOLDOWN_SECONDS


class CircuitRulesResponse(ApiModel):
    items: list[CircuitRuleView]


class CircuitRuleUpdate(ApiModel):
    threshold: int = Field(ge=1)
    window_seconds: int = Field(ge=0, alias="windowSeconds")


class CircuitEventView(ApiModel):
    id: uuid.UUID
    rule: CircuitRule
    action: str
    details: dict[str, object]
    created_at: datetime


class CircuitEventsResponse(ApiModel):
    items: list[CircuitEventView]


def _fail(status: int, code: str, detail: str) -> AuthFailure:
    return AuthFailure(status=status, code=code, title="Circuit rule rejected", detail=detail)


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions = getattr(request.app.state, "request_sessions", None)
    if sessions is None:
        raise _fail(503, "CIRCUIT_UNAVAILABLE", "Circuit storage is not configured.")
    return cast(async_sessionmaker[AsyncSession], sessions)


async def _require_treasury(session: AsyncSession, org: uuid.UUID, treasury: uuid.UUID) -> None:
    if (
        await session.scalar(
            select(Treasury.id).where(Treasury.id == treasury, Treasury.org_id == org)
        )
        is None
    ):
        raise _fail(404, "TREASURY_NOT_FOUND", "Treasury not found.")


async def _view(session: AsyncSession, treasury_id: uuid.UUID) -> list[CircuitRuleView]:
    rows = {
        r.rule: r
        for r in await session.scalars(
            select(CircuitRuleRow).where(CircuitRuleRow.treasury_id == treasury_id)
        )
    }
    items = []
    for rule, spec in SPECS.items():
        row = rows.get(rule.value)
        items.append(
            CircuitRuleView(
                rule=rule,
                threshold=row.threshold if row else spec.threshold,
                window_seconds=row.window_seconds if row else spec.window_seconds,
                action="ALERT_THEN_PAUSE" if rule is CircuitRule.UNEXPECTED_OUTFLOW else "PAUSE",
                tunable=spec.tunable,
            )
        )
    return items


@router.get("/rules", response_model=CircuitRulesResponse)
async def list_rules(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_member)],
) -> CircuitRulesResponse:
    async with _sessions(request)() as session:
        await _require_treasury(session, member.organization_id, treasury_id)
        return CircuitRulesResponse(items=await _view(session, treasury_id))


@router.put("/rules/{rule}", response_model=CircuitRulesResponse)
async def tighten_rule(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    rule: CircuitRule,
    payload: CircuitRuleUpdate,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_role(OrganizationRole.OWNER, step_up=True))],
) -> CircuitRulesResponse:
    try:
        validate_tightening(rule, payload.threshold, payload.window_seconds)
    except ValueError as exc:
        raise _fail(422, "CIRCUIT_RULE_NOT_TIGHTER", str(exc)) from None
    async with _sessions(request)() as session, session.begin():
        await _require_treasury(session, member.organization_id, treasury_id)
        insert = pg_insert(CircuitRuleRow).values(
            id=uuid.uuid4(),
            org_id=member.organization_id,
            treasury_id=treasury_id,
            rule=rule.value,
            threshold=payload.threshold,
            window_seconds=payload.window_seconds,
            updated_by=member.user_id,
        )
        await session.execute(
            insert.on_conflict_do_update(
                constraint="uq_circuit_rules_treasury_rule",
                set_={
                    "threshold": insert.excluded.threshold,
                    "window_seconds": insert.excluded.window_seconds,
                    "updated_by": member.user_id,
                    "updated_at": func.now(),
                },
            )
        )
        await log_audit_event(
            session,
            AuditEvent(
                org_id=member.organization_id,
                actor_id=member.user_id,
                action="circuit_rule.tightened",
                entity_type="treasury",
                entity_id=treasury_id,
                data={
                    "rule": rule.value,
                    "threshold": payload.threshold,
                    "windowSeconds": payload.window_seconds,
                },
            ),
        )
        return CircuitRulesResponse(items=await _view(session, treasury_id))


@router.get("/events", response_model=CircuitEventsResponse)
async def list_events(
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request: Request,
    member: Annotated[MemberAccess, Depends(require_member)],
) -> CircuitEventsResponse:
    async with _sessions(request)() as session:
        await _require_treasury(session, member.organization_id, treasury_id)
        rows = await session.scalars(
            select(CircuitEvent)
            .where(CircuitEvent.treasury_id == treasury_id)
            .order_by(CircuitEvent.created_at.desc())
            .limit(100)
        )
        return CircuitEventsResponse(
            items=[
                CircuitEventView(
                    id=r.id,
                    rule=CircuitRule(r.rule),
                    action=r.action,
                    details=r.details,
                    created_at=r.created_at,
                )
                for r in rows
            ]
        )
