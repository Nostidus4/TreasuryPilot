from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sqlalchemy import bindparam, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.events.writer import append_domain_event
from treasurypilot_api.identity.models import Organization, OrganizationRole, uuid7
from treasurypilot_api.invoices.fingerprints import (
    DenyDuplicateAllowance,
    DuplicateAllowance,
    assert_no_active_duplicate,
)
from treasurypilot_api.invoices.models import (
    ApprovalStatus,
    CancelOnchainStatus,
    PaymentApproval,
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
    PREPARATION_FAILED = "preparation_failed"
    PAY_SUBMITTED = "pay_submitted"
    PAY_CONFIRMED = "pay_confirmed"
    PAY_UNKNOWN = "pay_unknown"
    REVIEW_RESOLVED = "review_resolved"
    RESUME_PARTIAL = "resume_partial"
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


class MakerCheckerViolation(TransitionForbidden):
    code = "MAKER_CHECKER"


class PayOperationInFlight(RequestTransitionError):
    code = "PAYMENT_IN_FLIGHT"


class RequestVersionConflict(RequestTransitionError):
    status_code = 412
    code = "PRECONDITION_FAILED"


class RequestNotFound(RequestTransitionError):
    """The request does not exist or is outside the requested organization."""

    status_code = 404
    code = "REQUEST_NOT_FOUND"


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
    # Maker-checker: the actor must be neither the creator nor the last editor.
    checker_only: bool = False


def _user_rule(
    source: RequestStatus,
    target: RequestStatus,
    action: TransitionAction,
    *roles: OrganizationRole,
    creator_only: bool = False,
    checker_only: bool = False,
) -> TransitionRule:
    return TransitionRule(
        source,
        target,
        action,
        StatusEventActorType.USER,
        frozenset(roles),
        creator_only,
        checker_only,
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
        checker_only=True,
    ),
    _user_rule(
        RequestStatus.AWAITING_APPROVAL,
        RequestStatus.APPROVED,
        TransitionAction.APPROVE,
        OrganizationRole.APPROVER,
        checker_only=True,
    ),
    _user_rule(
        RequestStatus.AWAITING_APPROVAL,
        RequestStatus.REJECTED,
        TransitionAction.REJECT,
        OrganizationRole.APPROVER,
        checker_only=True,
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
    _system_rule(
        RequestStatus.PREPARING,
        RequestStatus.NEEDS_REVIEW,
        TransitionAction.PREPARATION_FAILED,
    ),
    _system_rule(RequestStatus.PREPARING, RequestStatus.PAYING, TransitionAction.PAY_SUBMITTED),
    _system_rule(RequestStatus.PAYING, RequestStatus.PAID, TransitionAction.PAY_CONFIRMED),
    _system_rule(RequestStatus.PAYING, RequestStatus.NEEDS_REVIEW, TransitionAction.PAY_UNKNOWN),
    _system_rule(
        RequestStatus.NEEDS_REVIEW,
        RequestStatus.SCHEDULED,
        TransitionAction.REVIEW_RESOLVED,
    ),
    _system_rule(
        RequestStatus.NEEDS_REVIEW, RequestStatus.PREPARING, TransitionAction.RESUME_PARTIAL
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
# M05 §5: cancel is allowed from every state before Paying.
_RULES += tuple(
    _user_rule(source, RequestStatus.CANCELLED, TransitionAction.CANCEL, role)
    for source in (
        RequestStatus.AWAITING_APPROVAL,
        RequestStatus.APPROVED,
        RequestStatus.SCHEDULED,
        RequestStatus.PLANNING,
        RequestStatus.AWAITING_AUTHORITY,
        RequestStatus.PREPARING,
        RequestStatus.NEEDS_REVIEW,
    )
    for role in (OrganizationRole.ORG_ADMIN, OrganizationRole.OWNER)
)

PAY_IN_FLIGHT_STATUSES = frozenset({"NotSubmitted", "Submitted", "Pending", "Unknown"})


_CHECKER_ACTIONS = frozenset(rule.action for rule in _RULES if rule.checker_only)


def _blocked_by_pay_in_flight(target: RequestStatus, action: TransitionAction) -> bool:
    """Cancelling and editing bound fields both need no PAY operation in flight."""
    return target == RequestStatus.CANCELLED or action == TransitionAction.EDIT_BOUND_FIELDS


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
    last_edited_by: uuid.UUID | None = None,
    solo_mode: bool = False,
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

    rule = authorized[0]
    if (
        rule.checker_only
        and not solo_mode
        and actor.actor_id in {created_by, last_edited_by} - {None}
    ):
        raise MakerCheckerViolation(
            "The creator or last editor of a request cannot review it unless solo mode is on."
        )
    if _blocked_by_pay_in_flight(target_status, actor.action) and pay_operation_in_flight:
        raise PayOperationInFlight("This change is not allowed while a PAY operation is in flight.")
    return rule


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
    """Look for an in-flight PAY operation of a request.

    The ``operations`` table belongs to the execution module (M07) and is not
    migrated yet. Until it exists no PAY operation can be in flight, so the guard
    checks for the table first instead of failing every cancel with UndefinedTable.
    """

    _IN_FLIGHT = text(
        "SELECT EXISTS ("
        "SELECT 1 FROM operations "
        "WHERE request_id = :request_id AND kind = 'PAY' AND status IN :statuses"
        ")"
    ).bindparams(bindparam("statuses", expanding=True))

    async def has_in_flight_pay(self, *, session: AsyncSession, request_id: uuid.UUID) -> bool:
        if await session.scalar(text("SELECT to_regclass('operations')")) is None:
            return False
        result = await session.scalar(
            self._IN_FLIGHT,
            {"request_id": request_id, "statuses": sorted(PAY_IN_FLIGHT_STATUSES)},
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
        duplicate_allowance: DuplicateAllowance | None = None,
    ) -> None:
        self._sessions = sessions
        self._audit = audit
        self._pay_operation_guard = pay_operation_guard
        self._duplicate_allowance = duplicate_allowance or DenyDuplicateAllowance()

    async def transition(
        self,
        *,
        organization_id: uuid.UUID,
        request_id: uuid.UUID,
        target: RequestStatus,
        actor: TransitionActor,
        expected_version: int | None = None,
        reason: str | None = None,
    ) -> RequestTransitionResult:
        """Apply ``target``; user actors must pass the version they saw (``If-Match``).

        The request row stays locked for the whole transaction, including the PAY
        in-flight check. M07 must take the same row lock (or re-check under it)
        before advancing a PAY operation.
        """
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
                raise RequestNotFound("Payment request not found.")
            if actor.actor_type == StatusEventActorType.USER and expected_version is None:
                raise RequestVersionConflict("If-Match with the request version is required.")
            if expected_version is not None and expected_version != request.version:
                raise RequestVersionConflict(
                    "The request changed since it was read; reload and try again."
                )

            source = _coerce_status(request.status)
            version_before = request.version
            solo_mode = False
            if actor.action in _CHECKER_ACTIONS:
                solo_mode = bool(
                    await session.scalar(
                        select(Organization.solo_mode).where(Organization.id == organization_id)
                    )
                )
            pay_operation_in_flight = _blocked_by_pay_in_flight(
                target, actor.action
            ) and await self._pay_operation_guard.has_in_flight_pay(
                session=session, request_id=request_id
            )
            rule = validate_transition(
                source=source,
                target=target,
                actor=actor,
                created_by=request.created_by,
                last_edited_by=request.last_edited_by,
                solo_mode=solo_mode,
                pay_operation_in_flight=pay_operation_in_flight,
            )

            if actor.action == TransitionAction.SUBMIT:
                await assert_no_active_duplicate(
                    session,
                    request,
                    allowance=self._duplicate_allowance,
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

            if target in (RequestStatus.CANCELLED, RequestStatus.REJECTED):
                # A signature must not stay Valid once its request is cancelled or rejected.
                await session.execute(
                    update(PaymentApproval)
                    .where(
                        PaymentApproval.request_id == request_id,
                        PaymentApproval.status == ApprovalStatus.VALID.value,
                    )
                    .values(
                        status=(
                            ApprovalStatus.CANCELLED
                            if target == RequestStatus.CANCELLED
                            else ApprovalStatus.INVALIDATED
                        ).value
                    )
                )
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
            if target == RequestStatus.AWAITING_APPROVAL:
                approval_ids: dict[str, uuid.UUID | list[uuid.UUID]] = {"requestId": request_id}
                org_solo_mode = await session.scalar(
                    select(Organization.solo_mode).where(Organization.id == organization_id)
                )
                if not org_solo_mode:
                    # Maker-checker: the creator and last editor cannot approve, so they
                    # get no "Approval required" notification they cannot act on.
                    makers = {request.created_by, request.last_edited_by} - {None}
                    approval_ids["excludeUserIds"] = sorted(makers, key=str)  # type: ignore[arg-type]
                append_domain_event(
                    session,
                    organization_id=organization_id,
                    treasury_id=request.treasury_id,
                    event_type="ApprovalNeeded",
                    entity_type="payment_request",
                    entity_id=request_id,
                    payload_ids=approval_ids,
                )
            elif target == RequestStatus.PAID:
                payload_ids = {"requestId": request_id}
                if request.created_by is not None:
                    payload_ids["creatorId"] = request.created_by
                append_domain_event(
                    session,
                    organization_id=organization_id,
                    treasury_id=request.treasury_id,
                    event_type="PaymentDone",
                    entity_type="payment_request",
                    entity_id=request_id,
                    payload_ids=payload_ids,
                )
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
                        # Only evaluated for checker actions; None means "not evaluated".
                        "soloMode": solo_mode if actor.action in _CHECKER_ACTIONS else None,
                        "cancelOnchain": request.cancel_onchain,
                        "fromVersion": version_before,
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
