from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.events.writer import append_domain_event
from treasurypilot_api.review.models import ReviewAction, ReviewItem, ReviewStatus, ReviewType


@dataclass(frozen=True, slots=True)
class ReviewRoute:
    role: str
    actions: frozenset[ReviewAction]


_OWNER_POLICY_CODES = ("PAYEE_", "LIMIT_", "BUDGET_", "MANDATE_")
_DEFAULT_ACTIONS = frozenset({ReviewAction.ACKNOWLEDGE})


def route_for_review(item_type: ReviewType | str, primary_code: str) -> ReviewRoute:
    """Resolve a review item's initial role and allowed actions deterministically."""
    review_type = ReviewType(item_type)
    if review_type == ReviewType.NEEDS_AUTHORITY:
        return ReviewRoute("Owner", frozenset({ReviewAction.GRANT_EXCEPTION, ReviewAction.CANCEL}))
    if review_type == ReviewType.POLICY_BLOCK:
        if primary_code.startswith(_OWNER_POLICY_CODES):
            return ReviewRoute("Owner", frozenset({ReviewAction.REPLAN, ReviewAction.CANCEL}))
        return ReviewRoute("Operator", frozenset({ReviewAction.EDIT_REQUEST, ReviewAction.CANCEL}))
    if review_type == ReviewType.FEE_APPROVAL:
        return ReviewRoute("Finance", frozenset({ReviewAction.ACCEPT_FEE}))
    if review_type == ReviewType.UNCERTAIN_TX:
        return ReviewRoute("Operator", frozenset({ReviewAction.ACKNOWLEDGE}))
    if review_type == ReviewType.DISCREPANCY:
        return ReviewRoute(
            "Finance", frozenset({ReviewAction.ACKNOWLEDGE, ReviewAction.MARK_MATCHED})
        )
    if review_type == ReviewType.AI_REJECTED:
        return ReviewRoute("Operator", frozenset({ReviewAction.REPLAN, ReviewAction.CANCEL}))
    if review_type == ReviewType.INFRA:
        return ReviewRoute("Operator", frozenset({ReviewAction.RETRY}))
    if review_type == ReviewType.UNEXPECTED_OUTFLOW:
        return ReviewRoute("Owner", frozenset({ReviewAction.ACKNOWLEDGE}))
    return ReviewRoute("Operator", _DEFAULT_ACTIONS)


def allowed_actions_for(item: ReviewItem) -> frozenset[ReviewAction]:
    """Escalated Owner items retain the deterministic action set for their type."""
    route = route_for_review(item.type, item.primary_code)
    if item.assigned_role == route.role:
        return route.actions
    if item.assigned_role == "Owner":
        if ReviewType(item.type) == ReviewType.POLICY_BLOCK:
            return frozenset({ReviewAction.REPLAN, ReviewAction.CANCEL})
        if ReviewType(item.type) == ReviewType.AI_REJECTED:
            return frozenset({ReviewAction.REPLAN, ReviewAction.CANCEL})
        if ReviewType(item.type) == ReviewType.INFRA:
            return frozenset({ReviewAction.RETRY})
        if ReviewType(item.type) == ReviewType.UNCERTAIN_TX:
            return frozenset({ReviewAction.ACKNOWLEDGE})
        if ReviewType(item.type) == ReviewType.DISCREPANCY:
            return frozenset({ReviewAction.ACKNOWLEDGE, ReviewAction.MARK_MATCHED})
        if ReviewType(item.type) == ReviewType.FEE_APPROVAL:
            return frozenset({ReviewAction.ACCEPT_FEE})
    return route.actions


def default_sla_due_at(item_type: ReviewType | str, *, now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    durations = {
        ReviewType.NEEDS_AUTHORITY: timedelta(hours=24),
        ReviewType.UNCERTAIN_TX: timedelta(hours=1),
    }
    return current + durations.get(ReviewType(item_type), timedelta(hours=48))


async def open_review_item(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    request_id: uuid.UUID,
    request_version: int,
    item_type: ReviewType | str,
    primary_code: str,
    reason_codes: tuple[str, ...] | list[str] | None = None,
    completed_steps: list[dict[str, object]] | None = None,
    plan_id: uuid.UUID | None = None,
    sla_due_at: datetime | None = None,
) -> tuple[ReviewItem, bool]:
    """Create one open item per request/type and emit one routed notification event.

    The partial unique index is the idempotency boundary. Repeated outcomes, including
    concurrent workers, return the already-open row without emitting another event.
    """
    if request_version < 1:
        raise ValueError("request_version must be positive")
    normalized_type = ReviewType(item_type)
    normalized_code = primary_code.strip().upper()
    if not normalized_code:
        raise ValueError("primary_code must not be empty")
    route = route_for_review(normalized_type, normalized_code)
    codes = list(
        dict.fromkeys(code.strip().upper() for code in (reason_codes or [normalized_code]))
    )
    if not codes or any(not code for code in codes):
        raise ValueError("reason_codes must contain non-empty codes")
    item_id = uuid.uuid4()
    statement = (
        insert(ReviewItem)
        .values(
            id=item_id,
            org_id=organization_id,
            treasury_id=treasury_id,
            request_id=request_id,
            plan_id=plan_id,
            type=normalized_type.value,
            primary_code=normalized_code,
            reason_codes=codes,
            completed_steps=completed_steps or [],
            assigned_role=route.role,
            status=ReviewStatus.OPEN.value,
            sla_due_at=sla_due_at or default_sla_due_at(normalized_type),
            source_version=request_version,
            version=1,
        )
        .on_conflict_do_nothing(
            index_elements=[ReviewItem.request_id, ReviewItem.type],
            index_where=text("status = 'Open'"),
        )
        .returning(ReviewItem.id)
    )
    inserted_id = await session.scalar(statement)
    item = await session.scalar(
        select(ReviewItem).where(
            ReviewItem.request_id == request_id,
            ReviewItem.type == normalized_type.value,
            ReviewItem.status == ReviewStatus.OPEN.value,
        )
    )
    if item is None:
        raise RuntimeError("review item insert did not produce an open item")
    created = inserted_id is not None
    if created:
        append_domain_event(
            session,
            organization_id=organization_id,
            treasury_id=treasury_id,
            event_type=f"NeedsReview:{route.role}",
            entity_type="review_item",
            entity_id=item.id,
            payload_ids={"requestId": request_id, "reviewItemId": item.id},
        )
    return item, created
