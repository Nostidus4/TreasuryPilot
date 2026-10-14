from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.invoices.models import (
    CancelOnchainStatus,
    RequestStatus,
    RequestStatusEvent,
    StatusEventActorType,
)
from treasurypilot_api.invoices.state_machine import (
    _RULES,
    PAY_IN_FLIGHT_STATUSES,
    AuditEntry,
    MakerCheckerViolation,
    PayOperationInFlight,
    RequestNotFound,
    RequestStateMachine,
    RequestTransitionError,
    RequestVersionConflict,
    SqlAlchemyPayOperationGuard,
    TransitionAction,
    TransitionActor,
    TransitionForbidden,
    TransitionRule,
    validate_transition,
)

_USER_ID = uuid.UUID("00000000-0000-7000-8000-000000000001")
_OTHER_USER_ID = uuid.UUID("00000000-0000-7000-8000-000000000002")
_ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
_REQUEST_ID = uuid.UUID("00000000-0000-7000-8000-000000000020")


def _actor_for(rule: TransitionRule, *, creator_id: uuid.UUID = _USER_ID) -> TransitionActor:
    if rule.actor_type == StatusEventActorType.SYSTEM:
        return TransitionActor(
            actor_type=StatusEventActorType.SYSTEM,
            action=rule.action,
        )
    return TransitionActor(
        actor_type=StatusEventActorType.USER,
        actor_id=creator_id if rule.creator_only else _OTHER_USER_ID,
        roles=rule.roles,
        action=rule.action,
    )


def test_full_transition_matrix_allows_only_documented_edges() -> None:
    for source in RequestStatus:
        for target in RequestStatus:
            matching = tuple(
                rule for rule in _RULES if rule.source == source and rule.target == target
            )
            for rule in matching:
                assert (
                    validate_transition(
                        source=source,
                        target=target,
                        actor=_actor_for(rule),
                        created_by=_USER_ID,
                    )
                    == rule
                )

            legal_actions = {rule.action for rule in matching}
            for action in TransitionAction:
                if action in legal_actions:
                    continue
                actor = TransitionActor(
                    actor_type=StatusEventActorType.USER,
                    actor_id=_OTHER_USER_ID,
                    roles=frozenset(OrganizationRole),
                    action=action,
                )
                with pytest.raises(RequestTransitionError):
                    validate_transition(
                        source=source,
                        target=target,
                        actor=actor,
                        created_by=_USER_ID,
                    )


def test_system_transitions_reject_user_actors() -> None:
    for rule in _RULES:
        if rule.actor_type != StatusEventActorType.SYSTEM:
            continue
        user = TransitionActor(
            actor_type=StatusEventActorType.USER,
            actor_id=_USER_ID,
            roles=frozenset(OrganizationRole),
            action=rule.action,
        )
        with pytest.raises(TransitionForbidden):
            validate_transition(
                source=rule.source,
                target=rule.target,
                actor=user,
                created_by=_OTHER_USER_ID,
            )


def test_user_transition_rules_reject_roles_without_permission() -> None:
    for rule in _RULES:
        if rule.actor_type != StatusEventActorType.USER:
            continue
        actor = TransitionActor(
            actor_type=StatusEventActorType.USER,
            actor_id=_OTHER_USER_ID,
            roles=frozenset({OrganizationRole.AUDITOR}),
            action=rule.action,
        )
        with pytest.raises(TransitionForbidden):
            validate_transition(
                source=rule.source,
                target=rule.target,
                actor=actor,
                created_by=_USER_ID,
            )


@pytest.mark.parametrize(
    ("action", "source", "target", "roles"),
    [
        (
            TransitionAction.CANCEL,
            RequestStatus.DRAFT,
            RequestStatus.CANCELLED,
            {OrganizationRole.OPERATOR},
        ),
        (
            TransitionAction.EDIT_BOUND_FIELDS,
            RequestStatus.APPROVED,
            RequestStatus.DRAFT,
            {OrganizationRole.OPERATOR},
        ),
    ],
)
def test_in_flight_pay_blocks_cancel_and_bound_field_edits(
    action: TransitionAction,
    source: RequestStatus,
    target: RequestStatus,
    roles: set[OrganizationRole],
) -> None:
    actor = TransitionActor(
        actor_type=StatusEventActorType.USER,
        actor_id=_USER_ID,
        roles=frozenset(roles),
        action=action,
    )
    with pytest.raises(PayOperationInFlight):
        validate_transition(
            source=source,
            target=target,
            actor=actor,
            created_by=_USER_ID,
            pay_operation_in_flight=True,
        )


@pytest.mark.parametrize("action", [TransitionAction.APPROVE, TransitionAction.REJECT])
def test_reviewers_cannot_review_requests_they_created_or_edited(
    action: TransitionAction,
) -> None:
    target = (
        RequestStatus.APPROVED if action == TransitionAction.APPROVE else RequestStatus.REJECTED
    )
    actor = TransitionActor(
        actor_type=StatusEventActorType.USER,
        actor_id=_USER_ID,
        roles=frozenset({OrganizationRole.OPERATOR, OrganizationRole.APPROVER}),
        action=action,
    )
    for created_by, last_edited_by in ((_USER_ID, None), (_OTHER_USER_ID, _USER_ID)):
        with pytest.raises(MakerCheckerViolation):
            validate_transition(
                source=RequestStatus.AWAITING_APPROVAL,
                target=target,
                actor=actor,
                created_by=created_by,
                last_edited_by=last_edited_by,
            )

    assert (
        validate_transition(
            source=RequestStatus.AWAITING_APPROVAL,
            target=target,
            actor=actor,
            created_by=_USER_ID,
            solo_mode=True,
        ).action
        == action
    )


@pytest.mark.parametrize(
    "source",
    [RequestStatus.PLANNING, RequestStatus.PREPARING, RequestStatus.AWAITING_AUTHORITY],
)
def test_admins_can_cancel_every_state_before_paying(source: RequestStatus) -> None:
    actor = TransitionActor(
        actor_type=StatusEventActorType.USER,
        actor_id=_OTHER_USER_ID,
        roles=frozenset({OrganizationRole.ORG_ADMIN}),
        action=TransitionAction.CANCEL,
    )
    validate_transition(
        source=source, target=RequestStatus.CANCELLED, actor=actor, created_by=_USER_ID
    )


def test_failed_preparation_moves_to_needs_review() -> None:
    actor = TransitionActor(
        actor_type=StatusEventActorType.SYSTEM, action=TransitionAction.PREPARATION_FAILED
    )
    rule = validate_transition(
        source=RequestStatus.PREPARING,
        target=RequestStatus.NEEDS_REVIEW,
        actor=actor,
        created_by=_USER_ID,
    )
    assert rule.target == RequestStatus.NEEDS_REVIEW


def test_operator_can_cancel_only_their_own_draft() -> None:
    actor = TransitionActor(
        actor_type=StatusEventActorType.USER,
        actor_id=_USER_ID,
        roles=frozenset({OrganizationRole.OPERATOR}),
        action=TransitionAction.CANCEL,
    )
    with pytest.raises(TransitionForbidden):
        validate_transition(
            source=RequestStatus.DRAFT,
            target=RequestStatus.CANCELLED,
            actor=actor,
            created_by=_OTHER_USER_ID,
        )


@pytest.mark.parametrize(
    "terminal", [RequestStatus.PAID, RequestStatus.REJECTED, RequestStatus.CANCELLED]
)
def test_terminal_statuses_have_no_outgoing_transitions(terminal: RequestStatus) -> None:
    assert not any(rule.source == terminal for rule in _RULES)


@dataclass
class _FakeRequest:
    id: uuid.UUID = _REQUEST_ID
    org_id: uuid.UUID = _ORG_ID
    status: str = RequestStatus.DRAFT.value
    cancel_onchain: str = CancelOnchainStatus.NOT_NEEDED.value
    version: int = 1
    created_by: uuid.UUID = _USER_ID
    last_edited_by: uuid.UUID | None = None


@dataclass
class _FakeSession:
    request: _FakeRequest
    events: list[object] = field(default_factory=list)
    has_approved_event: bool = False
    solo_mode: bool = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def scalar(self, statement: object, *_: object, **__: object) -> object:
        if "request_status_events" in str(statement):
            return _REQUEST_ID if self.has_approved_event else None
        if "organizations" in str(statement):
            return self.solo_mode
        return self.request

    def add(self, value: object) -> None:
        self.events.append(value)

    async def flush(self) -> None:
        return None

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self)


class _FakeTransaction:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.status: str | None = None
        self.cancel_onchain: str | None = None
        self.event_count = 0

    async def __aenter__(self) -> _FakeTransaction:
        self.status = self.session.request.status
        self.cancel_onchain = self.session.request.cancel_onchain
        self.event_count = len(self.session.events)
        return self

    async def __aexit__(self, exc_type: Any, *_: object) -> bool:
        if exc_type is not None:
            self.session.request.status = self.status or RequestStatus.DRAFT.value
            self.session.request.cancel_onchain = (
                self.cancel_onchain or CancelOnchainStatus.NOT_NEEDED.value
            )
            del self.session.events[self.event_count :]
        return False


class _FakeAudit:
    def __init__(self, *, fail: bool = False) -> None:
        self.entries: list[AuditEntry] = []
        self.session: _FakeSession | None = None
        self.fail = fail

    async def append(self, *, session: _FakeSession, entry: AuditEntry) -> None:
        self.session = session
        if self.fail:
            raise RuntimeError("audit storage unavailable")
        self.entries.append(entry)


class _FakePayOperationGuard:
    def __init__(self, *, in_flight: bool = False) -> None:
        self.in_flight = in_flight

    async def has_in_flight_pay(self, *, session: _FakeSession, request_id: uuid.UUID) -> bool:
        assert request_id == _REQUEST_ID
        return self.in_flight


def _machine(
    session: _FakeSession,
    audit: _FakeAudit,
    guard: _FakePayOperationGuard | None = None,
) -> RequestStateMachine:
    return RequestStateMachine(
        lambda: session,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        pay_operation_guard=guard or _FakePayOperationGuard(),  # type: ignore[arg-type]
    )


def test_transition_writes_status_event_and_audit_entry() -> None:
    session = _FakeSession(_FakeRequest())
    audit = _FakeAudit()
    actor = TransitionActor(
        actor_type=StatusEventActorType.USER,
        action=TransitionAction.SUBMIT,
        actor_id=_USER_ID,
        roles=frozenset({OrganizationRole.OPERATOR}),
    )

    result = asyncio.run(
        _machine(session, audit).transition(
            organization_id=_ORG_ID,
            request_id=_REQUEST_ID,
            expected_version=1,
            target=RequestStatus.AWAITING_APPROVAL,
            actor=actor,
            reason="ready for approval",
        )
    )

    assert result.status == RequestStatus.AWAITING_APPROVAL
    assert session.request.status == RequestStatus.AWAITING_APPROVAL.value
    assert len(session.events) == 1
    event = session.events[0]
    assert isinstance(event, RequestStatusEvent)
    assert event.from_status == RequestStatus.DRAFT.value
    assert event.to_status == RequestStatus.AWAITING_APPROVAL.value
    assert len(audit.entries) == 1
    assert audit.session is session
    assert audit.entries[0].action == TransitionAction.SUBMIT.value
    assert audit.entries[0].data["from"] == RequestStatus.DRAFT.value


def test_audit_failure_rolls_back_request_and_status_event() -> None:
    session = _FakeSession(_FakeRequest())
    actor = TransitionActor(
        actor_type=StatusEventActorType.USER,
        action=TransitionAction.SUBMIT,
        actor_id=_USER_ID,
        roles=frozenset({OrganizationRole.OPERATOR}),
    )

    with pytest.raises(RuntimeError, match="audit storage unavailable"):
        asyncio.run(
            _machine(session, _FakeAudit(fail=True)).transition(
                organization_id=_ORG_ID,
                request_id=_REQUEST_ID,
                expected_version=1,
                target=RequestStatus.AWAITING_APPROVAL,
                actor=actor,
            )
        )

    assert session.request.status == RequestStatus.DRAFT.value
    assert session.events == []


def test_state_machine_checks_pay_operation_guard_before_cancelling() -> None:
    session = _FakeSession(_FakeRequest())
    actor = TransitionActor(
        actor_type=StatusEventActorType.USER,
        action=TransitionAction.CANCEL,
        actor_id=_USER_ID,
        roles=frozenset({OrganizationRole.OPERATOR}),
    )

    with pytest.raises(PayOperationInFlight):
        asyncio.run(
            _machine(
                session,
                _FakeAudit(),
                _FakePayOperationGuard(in_flight=True),
            ).transition(
                organization_id=_ORG_ID,
                request_id=_REQUEST_ID,
                expected_version=1,
                target=RequestStatus.CANCELLED,
                actor=actor,
            )
        )

    assert session.request.status == RequestStatus.DRAFT.value
    assert session.events == []


def test_cancelling_a_previously_approved_request_sets_onchain_cancel_pending() -> None:
    session = _FakeSession(_FakeRequest(), has_approved_event=True)
    actor = TransitionActor(
        actor_type=StatusEventActorType.USER,
        action=TransitionAction.CANCEL,
        actor_id=_OTHER_USER_ID,
        roles=frozenset({OrganizationRole.OWNER}),
    )

    result = asyncio.run(
        _machine(session, _FakeAudit()).transition(
            organization_id=_ORG_ID,
            request_id=_REQUEST_ID,
            expected_version=1,
            target=RequestStatus.CANCELLED,
            actor=actor,
        )
    )

    assert result.cancel_onchain == CancelOnchainStatus.PENDING
    assert session.request.cancel_onchain == CancelOnchainStatus.PENDING.value


def _approve(machine: RequestStateMachine, *, expected_version: int | None) -> object:
    return asyncio.run(
        machine.transition(
            organization_id=_ORG_ID,
            request_id=_REQUEST_ID,
            expected_version=expected_version,
            target=RequestStatus.APPROVED,
            actor=TransitionActor(
                actor_type=StatusEventActorType.USER,
                action=TransitionAction.APPROVE,
                actor_id=_USER_ID,
                roles=frozenset({OrganizationRole.APPROVER}),
            ),
        )
    )


def test_user_transitions_require_the_current_version() -> None:
    session = _FakeSession(
        _FakeRequest(
            status=RequestStatus.AWAITING_APPROVAL.value, version=3, created_by=_OTHER_USER_ID
        )
    )
    machine = _machine(session, _FakeAudit())

    for stale in (None, 2):
        with pytest.raises(RequestVersionConflict) as error:
            _approve(machine, expected_version=stale)
        assert error.value.status_code == 412

    assert session.request.status == RequestStatus.AWAITING_APPROVAL.value
    assert session.events == []


def test_solo_mode_lets_the_creator_approve_and_is_audited() -> None:
    request = _FakeRequest(status=RequestStatus.AWAITING_APPROVAL.value)
    audit = _FakeAudit()

    with pytest.raises(MakerCheckerViolation):
        _approve(_machine(_FakeSession(request), audit), expected_version=1)

    _approve(_machine(_FakeSession(request, solo_mode=True), audit), expected_version=1)
    assert request.status == RequestStatus.APPROVED.value
    assert audit.entries[-1].data["soloMode"] is True


def test_audit_marks_solo_mode_not_evaluated_and_records_the_version_read() -> None:
    request = _FakeRequest(status=RequestStatus.DRAFT.value, version=4, created_by=_OTHER_USER_ID)
    audit = _FakeAudit()
    actor = TransitionActor(
        actor_type=StatusEventActorType.USER,
        action=TransitionAction.SUBMIT,
        actor_id=_USER_ID,
        roles=frozenset({OrganizationRole.OPERATOR}),
    )

    asyncio.run(
        _machine(_FakeSession(request), audit).transition(
            organization_id=_ORG_ID,
            request_id=_REQUEST_ID,
            target=RequestStatus.AWAITING_APPROVAL,
            actor=actor,
            expected_version=4,
        )
    )

    assert audit.entries[-1].data["soloMode"] is None
    assert audit.entries[-1].data["fromVersion"] == 4


def test_request_not_found_maps_to_404_like_other_transition_errors() -> None:
    assert issubclass(RequestNotFound, RequestTransitionError)
    assert RequestNotFound("missing").status_code == 404


async def _guard_reports(database_url: str, rows: list[tuple[str, str]]) -> bool | None:
    """Return the guard's answer for ``rows`` in a throwaway operations table."""
    engine = create_async_engine(database_url)
    try:
        async with AsyncSession(engine) as session, session.begin():
            guard = SqlAlchemyPayOperationGuard()
            if not rows:
                return await guard.has_in_flight_pay(session=session, request_id=_REQUEST_ID)
            await session.execute(
                text("CREATE TABLE operations (request_id uuid, kind text, status text)")
            )
            for kind, status in rows:
                await session.execute(
                    text("INSERT INTO operations VALUES (:request_id, :kind, :status)"),
                    {"request_id": _REQUEST_ID, "kind": kind, "status": status},
                )
            answer = await guard.has_in_flight_pay(session=session, request_id=_REQUEST_ID)
            await session.rollback()
            return answer
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PAY guard SQL test",
)
def test_pay_operation_guard_sql_matches_only_in_flight_pay_statuses() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    # Before M07 creates operations, no PAY can be in flight.
    assert asyncio.run(_guard_reports(database_url, [])) is False
    for status in sorted(PAY_IN_FLIGHT_STATUSES):
        assert asyncio.run(_guard_reports(database_url, [("PAY", status)])) is True, status
    assert asyncio.run(_guard_reports(database_url, [("PAY", "Confirmed")])) is False
    assert asyncio.run(_guard_reports(database_url, [("REFILL", "Pending")])) is False
