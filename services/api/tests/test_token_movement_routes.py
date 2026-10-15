from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from fastapi import Request
from fastapi.testclient import TestClient

from treasurypilot_api.chain.routes import TokenMovementRecord
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import SessionAccess, UserRecord
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.main import create_app

ORG_ID = uuid.UUID("00000000-0000-4000-8000-000000000111")
TREASURY_ID = uuid.UUID("00000000-0000-4000-8000-000000000222")
OWNER_ID = uuid.UUID("00000000-0000-4000-8000-000000000333")
MOVEMENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000444")


class MemoryRepository:
    def __init__(self) -> None:
        self.record = TokenMovementRecord(
            id=MOVEMENT_ID,
            treasury_id=TREASURY_ID,
            transaction_hash=b"\x11" * 32,
            block_number=123,
            block_hash=b"\x22" * 32,
            wallet=b"\x33" * 20,
            direction="OUT",
            counterparty=b"\x44" * 20,
            amount="50000000",
            classification="UNEXPECTED_OUTFLOW",
            operation_id=None,
            removed=False,
            created_at=datetime(2026, 10, 15, tzinfo=UTC),
            acknowledged_by=None,
            acknowledged_at=None,
            acknowledgement_reason=None,
        )
        self.ack_args: dict[str, object] | None = None

    async def list_recent(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID, limit: int
    ) -> tuple[TokenMovementRecord, ...] | None:
        if organization_id != ORG_ID or treasury_id != TREASURY_ID:
            return None
        return (self.record,)[:limit]

    async def acknowledge(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        movement_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: str,
    ) -> TokenMovementRecord:
        self.ack_args = {
            "organization_id": organization_id,
            "treasury_id": treasury_id,
            "movement_id": movement_id,
            "user_id": user_id,
            "reason": reason,
        }
        self.record = replace(
            self.record,
            acknowledged_by=user_id,
            acknowledged_at=datetime.now(UTC),
            acknowledgement_reason=reason.strip(),
        )
        return self.record


def _client(repository: MemoryRepository, *, roles: frozenset[str]) -> TestClient:
    app = create_app(
        settings=Settings(environment="local"),
        token_movement_repository=repository,
    )

    async def member_override(organization_id: uuid.UUID, request: Request) -> MemberAccess:
        del request
        access = SessionAccess(
            user=UserRecord(OWNER_ID, "owner@example.test", None, "active"),
            session_id=uuid.UUID("00000000-0000-4000-8000-000000000555"),
            step_up_at=datetime.now(UTC),
        )
        return MemberAccess(access=access, organization_id=organization_id, roles=roles)

    app.dependency_overrides[require_member] = member_override
    return TestClient(app)


def test_owner_can_list_and_acknowledge_unexpected_outflow() -> None:
    repository = MemoryRepository()
    with _client(repository, roles=frozenset({"Owner"})) as client:
        url = (
            f"/v1/orgs/{ORG_ID}/treasuries/{TREASURY_ID}/token-movements/{MOVEMENT_ID}/acknowledge"
        )
        listed = client.get(f"/v1/orgs/{ORG_ID}/treasuries/{TREASURY_ID}/token-movements")
        response = client.post(url, json={"reason": "Owner withdrawal"})

    assert listed.status_code == 200
    assert listed.json()["items"][0]["classification"] == "UNEXPECTED_OUTFLOW"
    assert listed.json()["items"][0]["amount"] == "50000000"
    assert response.status_code == 200
    assert response.json()["movement"]["acknowledgementReason"] == "Owner withdrawal"
    assert repository.ack_args == {
        "organization_id": ORG_ID,
        "treasury_id": TREASURY_ID,
        "movement_id": MOVEMENT_ID,
        "user_id": OWNER_ID,
        "reason": "Owner withdrawal",
    }


def test_finance_cannot_acknowledge_outflow() -> None:
    repository = MemoryRepository()
    with _client(repository, roles=frozenset({"Finance"})) as client:
        response = client.post(
            f"/v1/orgs/{ORG_ID}/treasuries/{TREASURY_ID}/token-movements/{MOVEMENT_ID}/acknowledge",
            json={"reason": "Reviewed"},
        )

    assert response.status_code == 403
    assert repository.ack_args is None


def test_token_movement_list_is_tenant_and_treasury_scoped() -> None:
    repository = MemoryRepository()
    with _client(repository, roles=frozenset({"Owner"})) as client:
        response = client.get(f"/v1/orgs/{ORG_ID}/treasuries/{uuid.uuid4()}/token-movements")

    assert response.status_code == 404
