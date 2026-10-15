from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.invoices.models import PaymentRequest
from treasurypilot_api.mandate.models import MandateVersion
from treasurypilot_api.recovery.models import ReviewItem


class ReviewType(StrEnum):
    POLICY_BLOCK = "POLICY_BLOCK"
    NEEDS_AUTHORITY = "NEEDS_AUTHORITY"
    FEE_APPROVAL = "FEE_APPROVAL"
    UNCERTAIN_TX = "UNCERTAIN_TX"
    DISCREPANCY = "DISCREPANCY"
    AI_REJECTED = "AI_REJECTED"
    INFRA = "INFRA"
    UNEXPECTED_OUTFLOW = "UNEXPECTED_OUTFLOW"


class ReviewStatus(StrEnum):
    OPEN = "Open"
    RESOLVED = "Resolved"
    DISMISSED = "Dismissed"


class ReviewAction(StrEnum):
    RETRY = "RETRY"
    REPLAN = "REPLAN"
    CANCEL = "CANCEL"
    EDIT_REQUEST = "EDIT_REQUEST"
    GRANT_EXCEPTION = "GRANT_EXCEPTION"
    ACCEPT_FEE = "ACCEPT_FEE"
    DEFER = "DEFER"
    ACKNOWLEDGE = "ACKNOWLEDGE"
    MARK_MATCHED = "MARK_MATCHED"


@dataclass(frozen=True, slots=True)
class Route:
    roles: tuple[OrganizationRole, ...]
    actions: tuple[ReviewAction, ...]
    sla: timedelta | None


_ROUTES = {
    ReviewType.NEEDS_AUTHORITY: Route(
        (OrganizationRole.OWNER,),
        (ReviewAction.GRANT_EXCEPTION, ReviewAction.CANCEL),
        timedelta(hours=24),
    ),
    ReviewType.FEE_APPROVAL: Route(
        (OrganizationRole.FINANCE, OrganizationRole.OPERATOR, OrganizationRole.OWNER),
        (ReviewAction.ACCEPT_FEE, ReviewAction.DEFER),
        None,
    ),
    ReviewType.UNCERTAIN_TX: Route(
        (OrganizationRole.OPERATOR,), (ReviewAction.ACKNOWLEDGE,), timedelta(hours=1)
    ),
    ReviewType.DISCREPANCY: Route(
        (OrganizationRole.FINANCE, OrganizationRole.OWNER),
        (ReviewAction.ACKNOWLEDGE, ReviewAction.MARK_MATCHED),
        timedelta(hours=48),
    ),
    ReviewType.AI_REJECTED: Route(
        (OrganizationRole.OPERATOR,),
        (ReviewAction.REPLAN, ReviewAction.CANCEL),
        timedelta(hours=48),
    ),
    ReviewType.INFRA: Route(
        (OrganizationRole.OPERATOR,), (ReviewAction.RETRY,), timedelta(hours=48)
    ),
    ReviewType.UNEXPECTED_OUTFLOW: Route(
        (OrganizationRole.OWNER, OrganizationRole.FINANCE),
        (ReviewAction.ACKNOWLEDGE,),
        timedelta(hours=48),
    ),
}
_POLICY_EDIT_CODES = frozenset(
    {"AMOUNT_CHANGED", "PAYEE_CHANGED", "APPROVAL_INVALID", "APPROVAL_EXPIRED"}
)


def route_for(kind: ReviewType, primary_code: str) -> Route:
    if kind == ReviewType.POLICY_BLOCK:
        if primary_code in _POLICY_EDIT_CODES:
            return Route(
                (OrganizationRole.OPERATOR, OrganizationRole.APPROVER),
                (ReviewAction.EDIT_REQUEST, ReviewAction.CANCEL),
                timedelta(hours=48),
            )
        return Route(
            (OrganizationRole.OWNER,),
            (ReviewAction.REPLAN, ReviewAction.CANCEL),
            timedelta(hours=48),
        )
    return _ROUTES[kind]


async def create_for_outcome(
    session: AsyncSession,
    *,
    request: PaymentRequest,
    outcome: ReviewType | str,
    primary_code: str,
    reason_codes: tuple[str, ...] = (),
    completed_steps: tuple[dict[str, object], ...] = (),
    plan_id: uuid.UUID | None = None,
    last_safe_execution_at: datetime | None = None,
    evidence_resolved: bool = False,
    now: datetime | None = None,
) -> ReviewItem | None:
    """Idempotently materialize one open item for each non-ALLOW outcome."""
    if outcome == "ALLOW":
        return None
    kind = ReviewType(outcome)
    route = route_for(kind, primary_code)
    current = now or datetime.now(UTC)
    if kind == ReviewType.FEE_APPROVAL:
        if last_safe_execution_at is None:
            raise ValueError("FEE_APPROVAL requires last_safe_execution_at")
        due = last_safe_execution_at
    elif route.sla is None:
        raise ValueError(f"{kind.value} route has no SLA")
    else:
        due = current + route.sla
    statement = (
        insert(ReviewItem)
        .values(
            id=uuid7(),
            org_id=request.org_id,
            treasury_id=request.treasury_id,
            request_id=request.id,
            request_version=request.version,
            plan_id=plan_id,
            type=kind.value,
            primary_code=primary_code,
            reason_codes=list(reason_codes),
            completed_steps=list(completed_steps),
            assigned_roles=[role.value for role in route.roles],
            status="Open",
            sla_due_at=due,
            evidence_resolved=evidence_resolved,
        )
        .on_conflict_do_nothing(
            index_elements=[ReviewItem.request_id, ReviewItem.type],
            index_where=ReviewItem.status == "Open",
        )
    )
    # Re-point an existing open item at a newer request version so it stays actionable.
    refresh = (
        update(ReviewItem)
        .where(
            ReviewItem.request_id == request.id,
            ReviewItem.type == kind.value,
            ReviewItem.status == "Open",
            ReviewItem.request_version < request.version,
        )
        .values(
            request_version=request.version,
            plan_id=plan_id,
            version=ReviewItem.version + 1,
        )
    )
    await session.execute(statement)
    await session.execute(refresh)
    item = await session.scalar(
        select(ReviewItem)
        .where(
            ReviewItem.request_id == request.id,
            ReviewItem.type == kind.value,
            ReviewItem.status == "Open",
        )
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise RuntimeError("open review item missing after idempotent insert")
    return item


async def create_for_mandate_discrepancy(
    session: AsyncSession,
    *,
    mandate_version: MandateVersion,
    primary_code: str,
    reason_codes: tuple[str, ...] = (),
    expected: Mapping[str, object] | None = None,
    actual: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> ReviewItem:
    """Idempotently open an Owner/Finance discrepancy item for a mandate read-back mismatch."""
    kind = ReviewType.DISCREPANCY
    route = route_for(kind, primary_code)
    if route.sla is None:
        raise ValueError("DISCREPANCY route requires an SLA")
    current = now or datetime.now(UTC)
    statement = (
        insert(ReviewItem)
        .values(
            id=uuid7(),
            org_id=mandate_version.org_id,
            treasury_id=mandate_version.treasury_id,
            request_id=None,
            request_version=None,
            mandate_version_id=mandate_version.id,
            plan_id=None,
            type=kind.value,
            primary_code=primary_code,
            reason_codes=list(reason_codes),
            completed_steps=[],
            assigned_roles=[role.value for role in route.roles],
            status=ReviewStatus.OPEN.value,
            sla_due_at=current + route.sla,
            evidence_resolved=False,
            evidence={
                **({"expected": dict(expected)} if expected is not None else {}),
                **({"actual": dict(actual)} if actual is not None else {}),
            },
        )
        .on_conflict_do_nothing(
            index_elements=[ReviewItem.mandate_version_id, ReviewItem.type],
            index_where=(ReviewItem.status == ReviewStatus.OPEN.value)
            & ReviewItem.mandate_version_id.is_not(None),
        )
    )
    await session.execute(statement)
    item = await session.scalar(
        select(ReviewItem)
        .where(
            ReviewItem.mandate_version_id == mandate_version.id,
            ReviewItem.type == kind.value,
            ReviewItem.status == ReviewStatus.OPEN.value,
        )
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise RuntimeError("open mandate discrepancy item missing after idempotent insert")
    return item


async def escalate_overdue(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Add Owner access once to each overdue open item.

    Mutates ORM state only: the caller owns the transaction and must commit. Owner-routed types
    are unchanged and get no escalation marker. Escalated Owners may act, not just view.
    """
    current = now or datetime.now(UTC)
    items = (
        await session.scalars(
            select(ReviewItem)
            .where(ReviewItem.status == "Open", ReviewItem.sla_due_at < current)
            .with_for_update(skip_locked=True)
        )
    ).all()
    changed = 0
    for item in items:
        if OrganizationRole.OWNER.value not in item.assigned_roles:
            item.assigned_roles = [*item.assigned_roles, OrganizationRole.OWNER.value]
            changed += 1
    return changed
