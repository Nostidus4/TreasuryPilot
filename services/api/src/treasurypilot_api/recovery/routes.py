from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.recovery.models import ReviewItem
from treasurypilot_api.recovery.review_queue import ReviewAction, ReviewType, route_for

router = APIRouter(prefix="/v1/orgs/{organization_id}/review-items", tags=["review-items"])


class ReviewActionRequest(ApiModel):
    action: ReviewAction
    note: str | None = Field(default=None, max_length=4_000)
    version: int = Field(ge=1)


def _failure(status: int, code: str, detail: str) -> AuthFailure:
    return AuthFailure(
        status=status, code=code, title=code.replace("_", " ").title(), detail=detail
    )


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions = getattr(request.app.state, "review_sessions", None)
    if sessions is None:
        raise _failure(503, "REVIEW_UNAVAILABLE", "Review storage is not configured.")
    return cast(async_sessionmaker[AsyncSession], sessions)


def _visible(item: ReviewItem, member: MemberAccess) -> bool:
    return not member.roles.isdisjoint(item.assigned_roles)


def _allowed_actions(item: ReviewItem, member: MemberAccess) -> list[str]:
    if item.status != "Open" or not _visible(item, member):
        return []
    actions = list(route_for(ReviewType(item.type), item.primary_code).actions)
    if item.type == ReviewType.UNCERTAIN_TX and not item.evidence_resolved:
        actions.remove(ReviewAction.ACKNOWLEDGE)
    return [action.value for action in actions]


def _view(item: ReviewItem, member: MemberAccess) -> dict[str, object]:
    return {
        "id": str(item.id),
        "orgId": str(item.org_id),
        "treasuryId": str(item.treasury_id),
        "requestId": str(item.request_id),
        "requestVersion": item.request_version,
        "planId": str(item.plan_id) if item.plan_id else None,
        "type": item.type,
        "primaryCode": item.primary_code,
        "reasonCodes": item.reason_codes,
        "completedSteps": item.completed_steps,
        "assignedRoles": item.assigned_roles,
        "status": item.status,
        "slaDueAt": item.sla_due_at.isoformat(),
        "resolvedBy": str(item.resolved_by) if item.resolved_by else None,
        "resolvedAt": item.resolved_at.isoformat() if item.resolved_at else None,
        "resolution": item.resolution,
        "note": item.note,
        "version": item.version,
        "allowedActions": _allowed_actions(item, member),
    }


@router.get("", openapi_extra={"x-organization-scoped": True})
async def list_review_items(
    organization_id: uuid.UUID,
    request: Request,
    status: str | None = None,
    type: ReviewType | None = None,
    role: str | None = None,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> dict[str, object]:
    statement = select(ReviewItem).where(ReviewItem.org_id == member.organization_id)
    if status is not None:
        statement = statement.where(ReviewItem.status == status)
    if type is not None:
        statement = statement.where(ReviewItem.type == type.value)
    statement = statement.order_by(ReviewItem.sla_due_at, ReviewItem.id)
    async with _sessions(request)() as session:
        items = (await session.scalars(statement)).all()
    return {
        "items": [
            _view(item, member)
            for item in items
            if _visible(item, member) and (role is None or role in item.assigned_roles)
        ]
    }


@router.get("/{item_id}", openapi_extra={"x-organization-scoped": True})
async def get_review_item(
    organization_id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> dict[str, object]:
    async with _sessions(request)() as session:
        item = await session.scalar(
            select(ReviewItem).where(
                ReviewItem.id == item_id, ReviewItem.org_id == member.organization_id
            )
        )
        if item is None or not _visible(item, member):
            raise _failure(404, "REVIEW_ITEM_NOT_FOUND", "The review item is unavailable.")
        payment = await session.scalar(
            select(PaymentRequest).where(PaymentRequest.id == item.request_id)
        )
        view = _view(item, member)
    return {
        "item": view,
        "request": {"id": str(payment.id), "status": payment.status} if payment else None,
        "plan": {"id": str(item.plan_id)} if item.plan_id else None,
        "steps": item.completed_steps,
        "validations": item.reason_codes,
        "evidence": {"resolved": item.evidence_resolved},
        "allowedActions": view["allowedActions"],
    }


@router.post("/{item_id}/actions", openapi_extra={"x-organization-scoped": True})
async def act_on_review_item(
    organization_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ReviewActionRequest,
    request: Request,
    response: Response,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> dict[str, object]:
    async with _sessions(request)() as session, session.begin():
        item = await session.scalar(
            select(ReviewItem)
            .where(ReviewItem.id == item_id, ReviewItem.org_id == member.organization_id)
            .with_for_update()
        )
        if item is None:
            raise _failure(404, "REVIEW_ITEM_NOT_FOUND", "The review item is unavailable.")
        if not _visible(item, member):
            raise _failure(403, "NOT_ROUTED_ROLE", "This item is routed to another role.")
        if item.status != "Open" or item.version != payload.version:
            raise _failure(409, "STALE_ITEM", "Reload the review item before acting.")
        payment = await session.scalar(
            select(PaymentRequest).where(PaymentRequest.id == item.request_id)
        )
        if payment is None or payment.version != item.request_version:
            raise _failure(409, "STALE_ITEM", "The underlying request has changed.")
        if payload.action.value not in _allowed_actions(item, member):
            raise _failure(409, "ACTION_NOT_ALLOWED", "The action is not allowed for this item.")
        item.note = payload.note
        if payload.action != ReviewAction.DEFER:
            item.status = "Resolved"
            item.resolution = payload.action.value
            item.resolved_by = member.user_id
            item.resolved_at = datetime.now(UTC)
        await session.flush()
        await session.refresh(item)
        view = _view(item, member)
    response.headers["ETag"] = f'"{item.version}"'
    return {"item": view}
