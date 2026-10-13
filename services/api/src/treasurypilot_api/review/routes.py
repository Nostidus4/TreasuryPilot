from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol, cast

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.access import MemberContext, require_member
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.invoices.models import PaymentRequest, RequestStatus, StatusEventActorType
from treasurypilot_api.invoices.state_machine import (
    RequestStateMachine,
    RequestTransitionError,
    TransitionAction,
    TransitionActor,
)
from treasurypilot_api.review.models import ReviewAction, ReviewItem, ReviewStatus, ReviewType
from treasurypilot_api.review.service import allowed_actions_for


class ReviewItemView(ApiModel):
    id: uuid.UUID
    treasury_id: uuid.UUID
    request_id: uuid.UUID
    plan_id: uuid.UUID | None
    type: ReviewType
    primary_code: str
    reason_codes: list[str]
    completed_steps: list[dict[str, object]]
    assigned_role: str
    status: ReviewStatus
    sla_due_at: datetime
    source_version: int
    version: int
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    resolution: ReviewAction | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    allowed_actions: list[ReviewAction] = Field(
        default_factory=list, serialization_alias="allowedActions"
    )

    @classmethod
    def from_item(cls, item: ReviewItem) -> ReviewItemView:
        return cls.model_validate(
            {
                "id": item.id,
                "treasury_id": item.treasury_id,
                "request_id": item.request_id,
                "plan_id": item.plan_id,
                "type": item.type,
                "primary_code": item.primary_code,
                "reason_codes": item.reason_codes,
                "completed_steps": item.completed_steps,
                "assigned_role": item.assigned_role,
                "status": item.status,
                "sla_due_at": item.sla_due_at,
                "source_version": item.source_version,
                "version": item.version,
                "resolved_by": item.resolved_by,
                "resolved_at": item.resolved_at,
                "resolution": item.resolution,
                "note": item.note,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "allowed_actions": sorted(
                    allowed_actions_for(item), key=lambda action: action.value
                ),
            }
        )


class ReviewActionRequest(ApiModel):
    action: ReviewAction
    note: str | None = Field(default=None, max_length=2000)
    version: int = Field(gt=0)


class ReviewItemList(ApiModel):
    items: list[ReviewItemView]


class ReviewItemResponse(ApiModel):
    item: ReviewItemView


class ReviewRepository(Protocol):
    async def list_items(
        self,
        *,
        organization_id: uuid.UUID,
        roles: tuple[str, ...],
        status: ReviewStatus | None,
        item_type: ReviewType | None,
        role: str | None,
        limit: int,
    ) -> tuple[ReviewItem, ...]: ...

    async def get_item(
        self, *, organization_id: uuid.UUID, item_id: uuid.UUID, roles: tuple[str, ...]
    ) -> ReviewItem | None: ...

    async def act(
        self,
        *,
        organization_id: uuid.UUID,
        item_id: uuid.UUID,
        actor_id: uuid.UUID,
        roles: tuple[str, ...],
        action: ReviewAction,
        note: str | None,
        expected_version: int,
    ) -> ReviewItem: ...


class ReviewNotFound(Exception):
    pass


class ReviewForbidden(Exception):
    pass


class StaleReviewItem(Exception):
    pass


class ReviewActionNotAllowed(Exception):
    pass


class ReviewTransitionsUnavailable(Exception):
    """The action must move the payment request, but no state machine is configured."""


# What each resolution does to the payment request (M12 §5). Actions that hand off to
# another flow (GRANT_EXCEPTION -> M03 governance, EDIT_REQUEST -> re-approval,
# ACCEPT_FEE -> fee policy) or only record a decision leave the request where it is.
_REQUEST_TRANSITIONS: dict[ReviewAction, tuple[RequestStatus, TransitionAction]] = {
    ReviewAction.CANCEL: (RequestStatus.CANCELLED, TransitionAction.CANCEL),
    ReviewAction.RETRY: (RequestStatus.SCHEDULED, TransitionAction.REVIEW_RESOLVED),
    ReviewAction.REPLAN: (RequestStatus.SCHEDULED, TransitionAction.REVIEW_RESOLVED),
}


class SqlAlchemyReviewRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        state_machine: RequestStateMachine | None = None,
    ) -> None:
        self._sessions = sessions
        self._state_machine = state_machine

    async def list_items(
        self,
        *,
        organization_id: uuid.UUID,
        roles: tuple[str, ...],
        status: ReviewStatus | None = None,
        item_type: ReviewType | None = None,
        role: str | None = None,
        limit: int = 100,
    ) -> tuple[ReviewItem, ...]:
        async with self._sessions() as session:
            statement = select(ReviewItem).where(
                ReviewItem.org_id == organization_id,
                ReviewItem.assigned_role.in_(roles),
            )
            if status is not None:
                statement = statement.where(ReviewItem.status == status.value)
            if item_type is not None:
                statement = statement.where(ReviewItem.type == item_type.value)
            if role is not None:
                statement = statement.where(ReviewItem.assigned_role == role)
            rows = await session.scalars(
                statement.order_by(
                    ReviewItem.sla_due_at, ReviewItem.created_at, ReviewItem.id
                ).limit(limit)
            )
            return tuple(rows)

    async def get_item(
        self, *, organization_id: uuid.UUID, item_id: uuid.UUID, roles: tuple[str, ...]
    ) -> ReviewItem | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(ReviewItem).where(
                    ReviewItem.id == item_id,
                    ReviewItem.org_id == organization_id,
                    ReviewItem.assigned_role.in_(roles),
                )
            )

    async def act(
        self,
        *,
        organization_id: uuid.UUID,
        item_id: uuid.UUID,
        actor_id: uuid.UUID,
        roles: tuple[str, ...],
        action: ReviewAction,
        note: str | None,
        expected_version: int,
    ) -> ReviewItem:
        async with self._sessions() as session, session.begin():
            visible_item = await session.scalar(
                select(ReviewItem).where(
                    ReviewItem.id == item_id,
                    ReviewItem.org_id == organization_id,
                )
            )
            if visible_item is None:
                raise ReviewNotFound
            if visible_item.assigned_role not in roles:
                raise ReviewForbidden

            # Lock the source request before the review row. State transitions use
            # the same order when they create an item, which avoids a request/item
            # deadlock during a concurrent recovery action.
            current_request_version = await session.scalar(
                select(PaymentRequest.version)
                .where(
                    PaymentRequest.id == visible_item.request_id,
                    PaymentRequest.org_id == organization_id,
                )
                .with_for_update()
            )
            if current_request_version is None:
                raise StaleReviewItem

            item = await session.scalar(
                select(ReviewItem)
                .where(ReviewItem.id == item_id, ReviewItem.org_id == organization_id)
                .with_for_update()
            )
            if item is None:
                raise ReviewNotFound
            if item.assigned_role not in roles:
                raise ReviewForbidden
            if item.status != ReviewStatus.OPEN.value or item.version != expected_version:
                raise StaleReviewItem
            # A request change invalidates an action even if the review row itself
            # has not yet been refreshed by another recovery run.
            if current_request_version != item.source_version:
                raise StaleReviewItem
            if action not in allowed_actions_for(item):
                raise ReviewActionNotAllowed

            now = datetime.now(UTC)
            item.status = ReviewStatus.RESOLVED.value
            item.resolved_by = actor_id
            item.resolved_at = now
            item.resolution = action.value
            item.note = note.strip() if note and note.strip() else None
            item.version += 1
            # Set explicitly: a server onupdate value is expired after flush and would be
            # read on a detached instance once the session closes.
            item.updated_at = now
            await session.flush()

            move = _REQUEST_TRANSITIONS.get(action)
            if move is not None:
                if self._state_machine is None:
                    raise ReviewTransitionsUnavailable
                target, transition = move
                # The resolution and the request transition commit (or fail) together.
                user_action = transition == TransitionAction.CANCEL
                await self._state_machine.apply(
                    session,
                    organization_id=organization_id,
                    request_id=item.request_id,
                    target=target,
                    actor=TransitionActor(
                        actor_type=(
                            StatusEventActorType.USER
                            if user_action
                            else StatusEventActorType.SYSTEM
                        ),
                        action=transition,
                        actor_id=actor_id if user_action else None,
                        roles=frozenset(
                            OrganizationRole(role)
                            for role in roles
                            if role in OrganizationRole._value2member_map_
                        ),
                    ),
                    expected_version=current_request_version if user_action else None,
                    reason=f"review_item:{item.id} {action.value}",
                )
            return item


def _repository(request: Request) -> ReviewRepository:
    repository = getattr(request.app.state, "review_repository", None)
    if repository is None:
        raise AuthFailure(
            status=503,
            code="REVIEW_UNAVAILABLE",
            title="Review queue unavailable",
            detail="Review item storage is not configured.",
        )
    return cast(ReviewRepository, repository)


def _failure(*, status: int, code: str, title: str, detail: str) -> AuthFailure:
    return AuthFailure(status=status, code=code, title=title, detail=detail)


router = APIRouter(prefix="/v1/orgs/{organization_id}/review-items", tags=["review"])


@router.get("", response_model=ReviewItemList, openapi_extra={"x-organization-scoped": True})
async def list_review_items(
    request: Request,
    status: ReviewStatus | None = None,
    item_type: ReviewType | None = Query(default=None, alias="type"),  # noqa: B008
    role: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),  # noqa: B008
    include_closed: bool = Query(default=False, alias="includeClosed"),  # noqa: B008
    member: MemberContext = Depends(require_member),  # noqa: B008
) -> ReviewItemList:
    if role is not None and role not in member.roles:
        raise _failure(
            status=403,
            code="NOT_ROUTED_ROLE",
            title="Role not routed",
            detail="This role is not assigned to the current user.",
        )
    items = await _repository(request).list_items(
        organization_id=member.organization_id,
        roles=tuple(member.roles),
        # Default to the actionable queue; closed history only when asked for.
        status=status if status is not None or include_closed else ReviewStatus.OPEN,
        item_type=item_type,
        role=role,
        limit=limit,
    )
    return ReviewItemList(items=[ReviewItemView.from_item(item) for item in items])


@router.get(
    "/{item_id}",
    response_model=ReviewItemResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def get_review_item(
    item_id: uuid.UUID,
    request: Request,
    member: MemberContext = Depends(require_member),  # noqa: B008
) -> ReviewItemResponse:
    item = await _repository(request).get_item(
        organization_id=member.organization_id,
        item_id=item_id,
        roles=tuple(member.roles),
    )
    if item is None:
        raise _failure(
            status=404,
            code="REVIEW_NOT_FOUND",
            title="Review item not found",
            detail="The review item does not exist or is not routed to this user.",
        )
    return ReviewItemResponse(item=ReviewItemView.from_item(item))


@router.post(
    "/{item_id}/actions",
    response_model=ReviewItemResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def act_on_review_item(
    item_id: uuid.UUID,
    payload: ReviewActionRequest,
    request: Request,
    member: MemberContext = Depends(require_member),  # noqa: B008
) -> ReviewItemResponse:
    try:
        item = await _repository(request).act(
            organization_id=member.organization_id,
            item_id=item_id,
            actor_id=member.user_id,
            roles=tuple(member.roles),
            action=payload.action,
            note=payload.note,
            expected_version=payload.version,
        )
    except ReviewNotFound as exc:
        raise _failure(
            status=404,
            code="REVIEW_NOT_FOUND",
            title="Review item not found",
            detail="The review item does not exist.",
        ) from exc
    except ReviewForbidden as exc:
        raise _failure(
            status=403,
            code="NOT_ROUTED_ROLE",
            title="Role not routed",
            detail="Only the routed role can act on this review item.",
        ) from exc
    except StaleReviewItem as exc:
        raise _failure(
            status=409,
            code="STALE_ITEM",
            title="Review item changed",
            detail="The review item or its request changed; reload before acting.",
        ) from exc
    except ReviewActionNotAllowed as exc:
        raise _failure(
            status=409,
            code="ACTION_NOT_ALLOWED",
            title="Action not allowed",
            detail="This action is not available for the review item's routed role.",
        ) from exc
    except RequestTransitionError as exc:
        # The request itself refused the move (e.g. this role cannot cancel it).
        raise _failure(
            status=exc.status_code,
            code=exc.code,
            title="Request transition refused",
            detail=exc.detail,
        ) from exc
    except ReviewTransitionsUnavailable as exc:
        raise _failure(
            status=503,
            code="REVIEW_UNAVAILABLE",
            title="Review actions unavailable",
            detail="Request transitions are not configured, so this action cannot be applied.",
        ) from exc
    return ReviewItemResponse(item=ReviewItemView.from_item(item))
