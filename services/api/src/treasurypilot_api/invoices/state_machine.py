from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.invoices.models import (
    CancelOnchainStatus,
    PaymentRequest,
    RequestStatus,
    RequestStatusEvent,
    StatusEventActorType,
)


class TransitionAction(StrEnum):
    SUBMIT = "submit"
    WITHDRAW = "withdraw"
    REQUEST_CHANGES = "request_changes"
    APPROVE = "approve"
    REJECT = "reject"
    EDIT_BOUND_FIELDS = "edit_bound_fields"
    SCHEDULE = "schedule"
    EXECUTION_WINDOW = "execution_window"
    NEEDS_APPROVAL = "needs_approval"
    EXCEPTION_GRANTED = "exception_granted"
    PLAN_ALLOWED = "plan_allowed"
    PLAN_BLOCKED = "plan_blocked"
    PAY_SUBMITTED = "pay_submitted"
    PAY_CONFIRMED = "pay_confirmed"
    PAY_UNKNOWN = "pay_unknown"
    REVIEW_RESOLVED = "review_resolved"
    EXPIRE = "expire"
    RENEW = "renew"
    CANCEL = "cancel"


class RequestTransitionError(Exception):
    status_code = 409
    code = "INVALID_REQUEST_TRANSITION"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class TransitionForbidden(RequestTransitionError):
    status_code = 403
    code = "TRANSITION_FORBIDDEN"


class PayOperationInFlight(RequestTransitionError):
    code = "PAYMENT_IN_FLIGHT"


class RequestNotFound(Exception):
    """The request does not exist or is outside the requested organization."""


@dataclass(frozen=True, slots=True)
class TransitionActor:
    actor_type: StatusEventActorType
    action: TransitionAction
    actor_id: uuid.UUID | None = None
    roles: frozenset[OrganizationRole] = frozenset()


@dataclass(frozen=True, slots=True)
class TransitionRule:
    source: RequestStatus
    target: RequestStatus
    action: TransitionAction
    actor_type: StatusEventActorType
    roles: frozenset[OrganizationRole] = frozenset()
    creator_only: bool = False


def _user_rule(
    source: RequestStatus,
    target: RequestStatus,
    action: TransitionAction,
    *roles: OrganizationRole,
    creator_only: bool = False,
) -> TransitionRule:
    return TransitionRule(
        source,
        target,
        action,
        StatusEventActorType.USER,
        frozenset(roles),
        creator_only,
    )


def _system_rule(
    source: RequestStatus, target: RequestStatus, action: TransitionAction
) -> TransitionRule:
    return TransitionRule(source, target, action, StatusEventActorType.SYSTEM)


_RULES: tuple[TransitionRule, ...] = (
    _user_rule(
        RequestStatus.DRAFT,
        RequestStatus.AWAITING_APPROVAL,
        TransitionAction.SUBMIT,
        OrganizationRole.OPERATOR,
        OrganizationRole.ORG_ADMIN,
    ),
    _user_rule(
        RequestStatus.AWAITING_APPROVAL,
        RequestStatus.DRAFT,
        TransitionAction.WITHDRAW,
        OrganizationRole.OPERATOR,
        OrganizationRole.ORG_ADMIN,
    ),
    _user_rule(
        RequestStatus.AWAITING_APPROVAL,
        RequestStatus.DRAFT,
        TransitionAction.REQUEST_CHANGES,
        OrganizationRole.APPROVER,
    ),
    _user_rule(
        RequestStatus.AWAITING_APPROVAL,
        RequestStatus.APPROVED,
        TransitionAction.APPROVE,
        OrganizationRole.APPROVER,
    ),
    _user_rule(
        RequestStatus.AWAITING_APPROVAL,
        RequestStatus.REJECTED,
        TransitionAction.REJECT,
        OrganizationRole.APPROVER,
    ),
    _user_rule(
        RequestStatus.APPROVED,
        RequestStatus.DRAFT,
        TransitionAction.EDIT_BOUND_FIELDS,
        OrganizationRole.OPERATOR,
        OrganizationRole.ORG_ADMIN,
    ),
    _system_rule(RequestStatus.APPROVED, RequestStatus.SCHEDULED, TransitionAction.SCHEDULE),
    _system_rule(RequestStatus.APPROVED, RequestStatus.EXPIRED, TransitionAction.EXPIRE),
    _system_rule(
        RequestStatus.SCHEDULED, RequestStatus.PLANNING, TransitionAction.EXECUTION_WINDOW
    ),
    _system_rule(
        RequestStatus.PLANNING,
        RequestStatus.AWAITING_AUTHORITY,
        TransitionAction.NEEDS_APPROVAL,
    ),
    _system_rule(
        RequestStatus.AWAITING_AUTHORITY,
        RequestStatus.SCHEDULED,
        TransitionAction.EXCEPTION_GRANTED,
    ),
    _system_rule(RequestStatus.PLANNING, RequestStatus.PREPARING, TransitionAction.PLAN_ALLOWED),
    _system_rule(RequestStatus.PLANNING, RequestStatus.NEEDS_REVIEW, TransitionAction.PLAN_BLOCKED),
    _system_rule(RequestStatus.PREPARING, RequestStatus.PAYING, TransitionAction.PAY_SUBMITTED),
    _system_rule(RequestStatus.PAYING, RequestStatus.PAID, TransitionAction.PAY_CONFIRMED),
    _system_rule(RequestStatus.PAYING, RequestStatus.NEEDS_REVIEW, TransitionAction.PAY_UNKNOWN),
    _system_rule(
        RequestStatus.NEEDS_REVIEW,
        RequestStatus.SCHEDULED,
        TransitionAction.REVIEW_RESOLVED,
    ),
    _system_rule(RequestStatus.SCHEDULED, RequestStatus.EXPIRED, TransitionAction.EXPIRE),
    _system_rule(
        RequestStatus.AWAITING_AUTHORITY,
        RequestStatus.EXPIRED,
        TransitionAction.EXPIRE,
    ),
    _system_rule(RequestStatus.NEEDS_REVIEW, RequestStatus.EXPIRED, TransitionAction.EXPIRE),
    _user_rule(
        RequestStatus.EXPIRED,
        RequestStatus.DRAFT,
        TransitionAction.RENEW,
        OrganizationRole.OPERATOR,
    ),
    _user_rule(
        RequestStatus.DRAFT,
        RequestStatus.CANCELLED,
        TransitionAction.CANCEL,
        OrganizationRole.OPERATOR,
        creator_only=True,
    ),
    _user_rule(
        RequestStatus.DRAFT,
        RequestStatus.CANCELLED,
        TransitionAction.CANCEL,
        OrganizationRole.ORG_ADMIN,
        OrganizationRole.OWNER,
    ),
)
_RULES += tuple(
    _user_rule(source, RequestStatus.CANCELLED, TransitionAction.CANCEL, role)
    for source in (
        RequestStatus.AWAITING_APPROVAL,
        RequestStatus.APPROVED,
        RequestStatus.SCHEDULED,
        RequestStatus.AWAITING_AUTHORITY,
        RequestStatus.NEEDS_REVIEW,
    )
    for role in (OrganizationRole.ORG_ADMIN, OrganizationRole.OWNER)
)

PAY_IN_FLIGHT_STATUSES = frozenset({"NotSubmitted", "Submitted", "Pending", "Unknown"})


def _coerce_status(status: RequestStatus | str) -> RequestStatus:
    try:
        return RequestStatus(status)
    except ValueError as exc:
        raise RequestTransitionError(f"Unknown payment request status: {status}.") from exc


def validate_transition(
    *,
    source: RequestStatus | str,
    target: RequestStatus | str,
    actor: TransitionActor,
    created_by: uuid.UUID | None,
    pay_operation_in_flight: bool = False,
) -> TransitionRule:
    source_status = _coerce_status(source)
    target_status = _coerce_status(target)
    matching = tuple(
        rule
        for rule in _RULES
        if rule.source == source_status
        and rule.target == target_status
        and rule.action == actor.action
    )
    if not matching:
        raise RequestTransitionError(
            f"Transition {source_status.value} → {target_status.value} is not allowed."
        )

    typed_rules = tuple(rule for rule in matching if rule.actor_type == actor.actor_type)
    if not typed_rules:
        raise TransitionForbidden("This transition is reserved for a different actor type.")

    if actor.actor_type == StatusEventActorType.SYSTEM and actor.actor_id is not None:
        raise TransitionForbidden("System transitions cannot have a user actor id.")
    if actor.actor_type == StatusEventActorType.USER and actor.actor_id is None:
        raise TransitionForbidden("User transitions require an authenticated actor id.")

    authorized = (
        typed_rules
        if actor.actor_type == StatusEventActorType.SYSTEM
        else tuple(
            rule
            for rule in typed_rules
            if not actor.roles.isdisjoint(rule.roles)
            and (not rule.creator_only or actor.actor_id == created_by)
        )
    )
    if not authorized:
        raise TransitionForbidden("The actor does not have permission for this transition.")

    if target_status == RequestStatus.CANCELLED and pay_operation_in_flight:
        raise PayOperationInFlight(
            "A payment request cannot be cancelled while a PAY operation is in flight."
        )
    return authorized[0]


@dataclass(frozen=True, slots=True)
class AuditEntry:
    organization_id: uuid.UUID
    actor_type: StatusEventActorType
    actor_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID
    data: dict[str, object]


class AuditAppender(Protocol):
    async def append(self, *, session: AsyncSession, entry: AuditEntry) -> None: ...


class PayOperationGuard(Protocol):
    async def has_in_flight_pay(self, *, session: AsyncSession, request_id: uuid.UUID) -> bool: ...


class SqlAlchemyPayOperationGuard:
    async def has_in_flight_pay(self, *, session: AsyncSession, request_id: uuid.UUID) -> bool:
        result = await session.scalar(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM operations "
                "WHERE request_id = :request_id AND kind = 'PAY' "
                "AND status IN ('NotSubmitted', 'Submitted', 'Pending', 'Unknown')"
                ")"
            ),
            {"request_id": request_id},
        )
        return bool(result)


@dataclass(frozen=True, slots=True)
class RequestTransitionResult:
    request_id: uuid.UUID
    status: RequestStatus
    cancel_onchain: CancelOnchainStatus
    version: int


class RequestStateMachine:
    """Apply request transitions and audit them in one database transaction."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        audit: AuditAppender,
        pay_operation_guard: PayOperationGuard,
    ) -> None:
        self._sessions = sessions
        self._audit = audit
        self._pay_operation_guard = pay_operation_guard

    async def transition(
        self,
        *,
        organization_id: uuid.UUID,
        request_id: uuid.UUID,
        target: RequestStatus,
        actor: TransitionActor,
        reason: str | None = None,
    ) -> RequestTransitionResult:
        async with self._sessions() as session, session.begin():
            request = await session.scalar(
                select(PaymentRequest)
                .where(
                    PaymentRequest.id == request_id,
                    PaymentRequest.org_id == organization_id,
                )
                .with_for_update()
            )
            if request is None:
                raise RequestNotFound

            source = _coerce_status(request.status)
            rule = validate_transition(
                source=source,
                target=target,
                actor=actor,
                created_by=request.created_by,
            )
            if (
                target == RequestStatus.CANCELLED
                and await self._pay_operation_guard.has_in_flight_pay(
                    session=session, request_id=request_id
                )
            ):
                raise PayOperationInFlight(
                    "A payment request cannot be cancelled while a PAY operation is in flight."
                )

            if target == RequestStatus.CANCELLED:
                approved_before = source == RequestStatus.APPROVED
                if not approved_before:
                    approved_before = (
                        await session.scalar(
                            select(RequestStatusEvent.id)
                            .where(
                                RequestStatusEvent.request_id == request_id,
                                RequestStatusEvent.to_status == RequestStatus.APPROVED.value,
                            )
                            .limit(1)
                        )
                        is not None
                    )
                if approved_before:
                    request.cancel_onchain = CancelOnchainStatus.PENDING.value

            request.status = rule.target.value
            event = RequestStatusEvent(
                id=uuid7(),
                request_id=request_id,
                from_status=source.value,
                to_status=rule.target.value,
                actor_type=actor.actor_type.value,
                actor_id=actor.actor_id,
                reason=reason,
            )
            session.add(event)
            await session.flush()

            await self._audit.append(
                session=session,
                entry=AuditEntry(
                    organization_id=organization_id,
                    actor_type=actor.actor_type,
                    actor_id=actor.actor_id,
                    action=actor.action.value,
                    entity_type="payment_request",
                    entity_id=request_id,
                    data={
                        "from": source.value,
                        "to": rule.target.value,
                        "reason": reason,
                        "cancelOnchain": request.cancel_onchain,
                        "version": request.version,
                    },
                ),
            )
            await session.flush()
            return RequestTransitionResult(
                request_id=request_id,
                status=rule.target,
                cancel_onchain=CancelOnchainStatus(request.cancel_onchain),
                version=request.version,
            )
