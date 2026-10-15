from __future__ import annotations

import uuid

from treasurypilot_api.events.writer import (
    append_domain_event,
    append_execution_cycle_requested,
)


class _FakeSession:
    def __init__(self) -> None:
        self.events: list[object] = []

    def add(self, value: object) -> None:
        self.events.append(value)


def test_append_domain_event_serializes_scalar_and_list_ids_only() -> None:
    session = _FakeSession()
    organization_id = uuid.uuid4()
    request_id = uuid.uuid4()
    owner_id = uuid.uuid4()

    event = append_domain_event(
        session,  # type: ignore[arg-type]
        organization_id=organization_id,
        event_type="GovernanceSignatureNeeded",
        entity_type="safe_transaction",
        entity_id=request_id,
        payload_ids={"requestId": request_id, "ownerUserIds": (owner_id,)},
    )

    assert event.payload == {
        "requestId": str(request_id),
        "ownerUserIds": [str(owner_id)],
    }
    assert session.events == [event]


def test_execution_cycle_event_is_an_ids_only_transactional_outbox_row() -> None:
    session = _FakeSession()
    organization_id = uuid.uuid4()
    treasury_id = uuid.uuid4()
    request_id = uuid.uuid4()

    event = append_execution_cycle_requested(
        session,  # type: ignore[arg-type]
        organization_id=organization_id,
        treasury_id=treasury_id,
        entity_type="payment_request",
        entity_id=request_id,
    )

    assert event.event_type == "ExecutionCycleRequested"
    assert event.treasury_id == treasury_id
    assert event.entity_id == request_id
    assert event.payload == {}
    assert session.events == [event]
