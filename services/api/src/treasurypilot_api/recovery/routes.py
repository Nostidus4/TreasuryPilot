from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.events import AuditEvent, log_audit_event
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.api import _service as _auth_service
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.mandate.fees import accept_held_plan_fee
from treasurypilot_api.mandate.models import MandateVersion
from treasurypilot_api.recovery.models import ReviewItem
from treasurypilot_api.recovery.review_queue import (
    ReviewAction,
    ReviewStatus,
    ReviewType,
    route_for,
)

router = APIRouter(prefix="/v1/orgs/{organization_id}/review-items", tags=["review-items"])


class ReviewActionRequest(ApiModel):
    action: ReviewAction
    note: str | None = Field(default=None, max_length=4_000)
    version: int = Field(ge=1)


class ReviewItemView(ApiModel):
    id: str
    org_id: str
    treasury_id: str
    request_id: str | None
    request_version: int | None
    mandate_version_id: str | None
    plan_id: str | None
    fee_estimate_wei: str | None
    type: ReviewType
    primary_code: str
    reason_codes: list[str]
    completed_steps: list[dict[str, object]]
    assigned_roles: list[OrganizationRole]
    status: ReviewStatus
    sla_due_at: str
    created_at: str
    resolved_by: str | None
    resolved_at: str | None
    resolution: str | None
    note: str | None
    version: int
    allowed_actions: list[ReviewAction]


class ReviewItemList(ApiModel):
    items: list[ReviewItemView]


class ReviewItemResult(ApiModel):
    item: ReviewItemView


class ReviewRequestRef(ApiModel):
    id: str
    status: str


class ReviewMandateRef(ApiModel):
    id: str
    version: int
    status: str


class ReviewPlanRef(ApiModel):
    id: str


class ReviewItemDetail(ApiModel):
    item: ReviewItemView
    request: ReviewRequestRef | None
    mandate_version: ReviewMandateRef | None
    plan: ReviewPlanRef | None
    steps: list[dict[str, object]]
    validations: list[str]
    evidence: dict[str, object]
    allowed_actions: list[ReviewAction]


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
    if item.mandate_version_id is not None:
        return [ReviewAction.ACKNOWLEDGE.value] if ReviewAction.ACKNOWLEDGE in actions else []
    if item.type == ReviewType.UNCERTAIN_TX and not item.evidence_resolved:
        actions.remove(ReviewAction.ACKNOWLEDGE)
    if item.type == ReviewType.POLICY_BLOCK and item.completed_steps:
        # A partial plan can resume (README 7.2); the route's own roles already see the item.
        actions.append(ReviewAction.RETRY)
    return [action.value for action in actions]


def _view(item: ReviewItem, member: MemberAccess) -> dict[str, object]:
    return {
        "id": str(item.id),
        "orgId": str(item.org_id),
        "treasuryId": str(item.treasury_id),
        "requestId": str(item.request_id) if item.request_id else None,
        "requestVersion": item.request_version,
        "mandateVersionId": (
            str(item.mandate_version_id) if item.mandate_version_id is not None else None
        ),
        "planId": str(item.plan_id) if item.plan_id else None,
        "feeEstimateWei": str(item.fee_estimate_wei) if item.fee_estimate_wei is not None else None,
        "type": item.type,
        "primaryCode": item.primary_code,
        "reasonCodes": item.reason_codes,
        "completedSteps": item.completed_steps,
        "assignedRoles": item.assigned_roles,
        "status": item.status,
        "slaDueAt": item.sla_due_at.isoformat(),
        "createdAt": item.created_at.isoformat(),
        "resolvedBy": str(item.resolved_by) if item.resolved_by else None,
        "resolvedAt": item.resolved_at.isoformat() if item.resolved_at else None,
        "resolution": item.resolution,
        "note": item.note,
        "version": item.version,
        "allowedActions": _allowed_actions(item, member),
    }


async def _is_partial_recovery(
    session: AsyncSession, item: ReviewItem, action: ReviewAction
) -> bool:
    """RETRY/CANCEL on a stop of a PartiallyCompleted plan runs in the worker (RCV-003)."""

    if action not in {ReviewAction.RETRY, ReviewAction.CANCEL} or item.request_id is None:
        return False
    if item.type not in {ReviewType.POLICY_BLOCK.value, ReviewType.INFRA.value}:
        return False
    return (
        await session.scalar(
            text("SELECT 1 FROM plans WHERE request_id = :r AND status = 'PartiallyCompleted'"),
            {"r": item.request_id},
        )
        is not None
    )


@router.get("", response_model=ReviewItemList, openapi_extra={"x-organization-scoped": True})
async def list_review_items(
    organization_id: uuid.UUID,
    request: Request,
    status: ReviewStatus | None = None,
    type: ReviewType | None = None,
    role: OrganizationRole | None = None,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> dict[str, object]:
    statement = select(ReviewItem).where(
        ReviewItem.org_id == member.organization_id,
        ReviewItem.assigned_roles.overlap(list(member.roles)),
    )
    if status is not None:
        statement = statement.where(ReviewItem.status == status.value)
    if role is not None:
        statement = statement.where(ReviewItem.assigned_roles.contains([role.value]))
    if type is not None:
        statement = statement.where(ReviewItem.type == type.value)
    statement = statement.order_by(ReviewItem.sla_due_at, ReviewItem.id)
    async with _sessions(request)() as session:
        items = (await session.scalars(statement)).all()
    return {"items": [_view(item, member) for item in items]}


@router.get(
    "/{item_id}", response_model=ReviewItemDetail, openapi_extra={"x-organization-scoped": True}
)
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
        payment = None
        mandate_version = None
        if item.request_id is not None:
            payment = await session.scalar(
                select(PaymentRequest).where(
                    PaymentRequest.id == item.request_id,
                    PaymentRequest.org_id == member.organization_id,
                )
            )
        elif item.mandate_version_id is not None:
            mandate_version = await session.scalar(
                select(MandateVersion).where(
                    MandateVersion.id == item.mandate_version_id,
                    MandateVersion.org_id == member.organization_id,
                )
            )
        view = _view(item, member)
    return {
        "item": view,
        "request": {"id": str(payment.id), "status": payment.status} if payment else None,
        "mandateVersion": (
            {
                "id": str(mandate_version.id),
                "version": mandate_version.version,
                "status": mandate_version.status.value,
            }
            if mandate_version
            else None
        ),
        "plan": {"id": str(item.plan_id)} if item.plan_id else None,
        "steps": item.completed_steps,
        "validations": item.reason_codes,
        "evidence": {**item.evidence, "resolved": item.evidence_resolved},
        "allowedActions": view["allowedActions"],
    }


@router.post(
    "/{item_id}/actions",
    response_model=ReviewItemResult,
    responses={503: {"description": "RECOVERY_UNAVAILABLE: the resume/cancel task was not queued"}},
    openapi_extra={"x-organization-scoped": True},
)
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
        if item is None or not _visible(item, member):
            raise _failure(404, "REVIEW_ITEM_NOT_FOUND", "The review item is unavailable.")
        if item.status != "Open" or item.version != payload.version:
            raise _failure(409, "STALE_ITEM", "Reload the review item before acting.")
        if item.request_id is not None:
            payment = await session.scalar(
                select(PaymentRequest).where(
                    PaymentRequest.id == item.request_id,
                    PaymentRequest.org_id == member.organization_id,
                )
            )
            if payment is None or payment.version != item.request_version:
                raise _failure(409, "STALE_ITEM", "The underlying request has changed.")
        elif item.mandate_version_id is not None:
            mandate_version = await session.scalar(
                select(MandateVersion).where(
                    MandateVersion.id == item.mandate_version_id,
                    MandateVersion.org_id == member.organization_id,
                )
            )
            if mandate_version is None:
                raise _failure(409, "STALE_ITEM", "The underlying mandate version is unavailable.")
        if payload.action.value not in _allowed_actions(item, member):
            raise _failure(409, "ACTION_NOT_ALLOWED", "The action is not allowed for this item.")
        if (
            payload.action == ReviewAction.RETRY
            and item.type == ReviewType.POLICY_BLOCK.value
            and not await _is_partial_recovery(session, item, payload.action)
        ):
            raise _failure(409, "ACTION_NOT_ALLOWED", "The plan is not partially completed.")
        if payload.note is not None:
            item.note = payload.note
        if payload.action in {ReviewAction.ACCEPT_FEE, ReviewAction.DEFER}:
            if item.type != ReviewType.FEE_APPROVAL.value:
                raise _failure(
                    409, "ACTION_NOT_ALLOWED", "Fee actions are only valid for fee reviews."
                )
        if payload.action == ReviewAction.ACCEPT_FEE:
            # Accepting spends beyond the Owner's policy, so it needs a fresh second factor.
            _auth_service(request).require_step_up(member.access)
            await accept_held_plan_fee(
                session,
                item=item,
                user_id=member.user_id,
                reason=payload.note,
                now=datetime.now(UTC),
            )
        elif await _is_partial_recovery(session, item, payload.action):
            # The worker task resolves the item once it has reopened (or cancelled) the plan, so a
            # failed hand-off leaves the item Open and retryable.
            queue = getattr(request.app.state, "partial_recovery_queue", None)
            if queue is None:
                raise _failure(503, "RECOVERY_UNAVAILABLE", "Recovery queue is not configured.")
            assert item.request_id is not None
            try:
                queue.enqueue(payload.action.value, item.request_id, member.user_id)
            except Exception as error:
                raise _failure(
                    503, "RECOVERY_UNAVAILABLE", "The recovery task could not be queued."
                ) from error
            await log_audit_event(
                session,
                AuditEvent(
                    org_id=member.organization_id,
                    actor_id=member.user_id,
                    action=f"recovery.{payload.action.value.lower()}_enqueued",
                    entity_type="review_item",
                    entity_id=item.id,
                    data={"requestId": str(item.request_id)},
                ),
            )
        elif payload.action != ReviewAction.DEFER:
            item.status = "Resolved"
            item.resolution = payload.action.value
            item.resolved_by = member.user_id
            item.resolved_at = datetime.now(UTC)
        await session.flush()
        await session.refresh(item)
        view = _view(item, member)
    response.headers["ETag"] = f'"{item.version}"'
    return {"item": view}
