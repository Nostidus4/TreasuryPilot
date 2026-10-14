from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi import Request
from fastapi.testclient import TestClient

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.auth import AuthFailure, SessionAccess, UserRecord
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.main import create_app
from treasurypilot_api.mandate.routes import (
    MandateContext,
    MandateVersionRecord,
)

ORG_ID = uuid.UUID("00000000-0000-4000-8000-000000000111")
TREASURY_ID = uuid.UUID("00000000-0000-4000-8000-000000000222")
OWNER_ID = uuid.UUID("00000000-0000-4000-8000-000000000333")
SAFE_T = "0x" + "11" * 20
OPERATIONAL = "0x" + "22" * 20


class MemoryMandateRepository:
    def __init__(self) -> None:
        self.rows: list[MandateVersionRecord] = []
        self.active_config: dict[str, object] | None = None

    async def get_context(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> MandateContext | None:
        if organization_id != ORG_ID or treasury_id != TREASURY_ID:
            return None
        return MandateContext(
            asset_decimals=6,
            asset_symbol="tUSDC",
            wallets={SAFE_T: "SOURCE", OPERATIONAL: "OPERATIONAL"},
            active_config=self.active_config,
        )

    async def list_versions(
        self, *, organization_id: uuid.UUID, treasury_id: uuid.UUID
    ) -> tuple[MandateVersionRecord, ...] | None:
        if organization_id != ORG_ID or treasury_id != TREASURY_ID:
            return None
        return tuple(reversed(self.rows))

    async def get_version(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        mandate_id: uuid.UUID,
    ) -> MandateVersionRecord | None:
        if organization_id != ORG_ID or treasury_id != TREASURY_ID:
            return None
        return next((row for row in self.rows if row.id == mandate_id), None)

    async def create_draft(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        user_id: uuid.UUID,
        build_config: Callable[[MandateContext], dict[str, object]],
    ) -> tuple[MandateVersionRecord, MandateContext] | None:
        context = await self.get_context(organization_id=organization_id, treasury_id=treasury_id)
        if context is None:
            return None
        config = build_config(context)
        encoded = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
        row = MandateVersionRecord(
            id=uuid.uuid4(),
            treasury_id=treasury_id,
            version=len(self.rows) + 1,
            status="Draft",
            config=config,
            config_hash=hashlib.sha256(encoded).digest(),
            created_at=datetime.now(UTC),
        )
        self.rows.append(row)
        return row, context

    async def discard_draft(
        self,
        *,
        organization_id: uuid.UUID,
        treasury_id: uuid.UUID,
        mandate_id: uuid.UUID,
    ) -> MandateVersionRecord | None:
        row = await self.get_version(
            organization_id=organization_id,
            treasury_id=treasury_id,
            mandate_id=mandate_id,
        )
        if row is None:
            return None
        if row.status == "Draft":
            self.rows.remove(row)
        return row


class FakeMandateActivationService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create_mandate_activation(self, **fields: object) -> dict[str, object]:
        self.calls.append(fields)
        return {
            "id": "governance-tx",
            "status": "Collecting",
            "mandate": {"status": "PendingActivation"},
        }


def config_payload() -> dict[str, object]:
    return {
        "actions": ["PAY", "REFILL", "SUPPLY"],
        "refillPaths": [{"from": SAFE_T, "to": OPERATIONAL}],
        "limits": {
            "PAY": {"perRequest": "2000000000", "daily": "10000000000"},
            "REFILL": {"perRequest": "2500000000", "daily": "12000000000"},
        },
        "supplyLimits": {"perRequest": "5000000000", "daily": "20000000000"},
        "buffers": [
            {"wallet": SAFE_T, "minimum": "1000000000"},
            {"wallet": OPERATIONAL, "minimum": "10000000", "target": "150000000"},
        ],
        "gasFundingCapWei": "50000000000000000",
        "executor": "0x" + "33" * 20,
        "approvers": ["0x" + "44" * 20],
        "guardian": "0x" + "55" * 20,
        # Relative to now: drafts that are already expired are rejected.
        "validFrom": _iso(datetime.now(UTC) + timedelta(days=1)),
        "expiresAt": _iso(datetime.now(UTC) + timedelta(days=30)),
    }


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_client(
    repository: MemoryMandateRepository,
    *,
    roles: frozenset[str] = frozenset({"Owner"}),
    step_up_at: datetime | None = None,
    governance_service: object | None = None,
) -> TestClient:
    app = create_app(
        settings=Settings(environment="local"),
        mandate_repository=cast(object, repository),
        governance_service=cast(object, governance_service) if governance_service else None,
    )

    async def member_override(organization_id: uuid.UUID) -> MemberAccess:
        # Membership is granted everywhere so the repository's tenant scoping is tested.
        access = SessionAccess(
            user=UserRecord(OWNER_ID, "owner@example.test", None, "active"),
            session_id=uuid.UUID("00000000-0000-4000-8000-000000000444"),
            step_up_at=step_up_at or datetime.now(UTC),
        )
        return MemberAccess(access=access, organization_id=organization_id, roles=roles)

    app.dependency_overrides[require_member] = member_override
    return TestClient(app)


def test_create_mandate_draft_persists_supply_settings_and_summary() -> None:
    repository = MemoryMandateRepository()
    with make_client(repository) as client:
        response = client.post(
            f"/v1/orgs/{ORG_ID}/treasuries/{TREASURY_ID}/mandates", json=config_payload()
        )

    assert response.status_code == 201
    body = response.json()
    assert body["draft"]["config"]["supplyLimits"] == {
        "perRequest": "5000000000",
        "daily": "20000000000",
    }
    assert body["draft"]["config"]["minSupply"] == "500000000"
    assert body["draft"]["config"]["reserveHorizonDays"] == 30
    assert body["summary"][-1]["field"] == "reserveHorizonDays"
    assert {call["method"] for call in body["bundlePreview"]["calls"]} == {
        "configureMandate",
        "setApprovers",
        "setBuffer",
    }
    assert response.headers["location"].endswith(body["draft"]["id"])


def test_incomplete_mandate_returns_problem_fields() -> None:
    repository = MemoryMandateRepository()
    with make_client(repository) as client:
        response = client.post(f"/v1/orgs/{ORG_ID}/treasuries/{TREASURY_ID}/mandates", json={})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "MANDATE_INCOMPLETE"
    assert "fields" in response.json()
    assert repository.rows == []


def test_mandate_routes_require_owner_and_hide_other_tenants() -> None:
    repository = MemoryMandateRepository()
    with make_client(repository, roles=frozenset({"Finance"})) as client:
        denied = client.post(
            f"/v1/orgs/{ORG_ID}/treasuries/{TREASURY_ID}/mandates", json=config_payload()
        )
        hidden = client.get(f"/v1/orgs/{uuid.uuid4()}/treasuries/{TREASURY_ID}/mandates")

    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN"
    assert hidden.status_code == 404
    assert repository.rows == []


def test_mandate_activation_endpoint_requires_owner_and_builds_governance_tx() -> None:
    repository = MemoryMandateRepository()
    service = FakeMandateActivationService()
    mandate_id = uuid.uuid4()
    with make_client(repository, governance_service=service) as client:
        response = client.post(
            f"/v1/orgs/{ORG_ID}/treasuries/{TREASURY_ID}/mandates/{mandate_id}/governance-tx"
        )

    assert response.status_code == 201
    assert response.json()["mandate"]["status"] == "PendingActivation"
    assert service.calls == [
        {
            "organization_id": ORG_ID,
            "treasury_id": TREASURY_ID,
            "mandate_id": mandate_id,
            "user_id": OWNER_ID,
        }
    ]


def test_mandate_draft_can_be_listed_cloned_and_discarded() -> None:
    repository = MemoryMandateRepository()
    with make_client(repository) as client:
        base_url = f"/v1/orgs/{ORG_ID}/treasuries/{TREASURY_ID}/mandates"
        created = client.post(base_url, json=config_payload())
        original_id = created.json()["draft"]["id"]
        cloned = client.post(f"{base_url}/{original_id}/clone")
        clone_id = cloned.json()["draft"]["id"]
        listed = client.get(base_url)
        discarded = client.delete(f"{base_url}/{clone_id}")
        listed_after_discard = client.get(base_url)

    assert created.status_code == cloned.status_code == 201
    assert cloned.json()["draft"]["version"] == 2
    assert [item["version"] for item in listed.json()["items"]] == [2, 1]
    assert discarded.status_code == 204
    assert [item["version"] for item in listed_after_discard.json()["items"]] == [1]


def test_clone_of_expired_mandate_is_allowed_but_create_is_not() -> None:
    repository = MemoryMandateRepository()
    expired = config_payload() | {
        "validFrom": _iso(datetime.now(UTC) - timedelta(days=60)),
        "expiresAt": _iso(datetime.now(UTC) - timedelta(days=30)),
    }
    with make_client(repository) as client:
        base_url = f"/v1/orgs/{ORG_ID}/treasuries/{TREASURY_ID}/mandates"
        rejected = client.post(base_url, json=expired)
        repository.rows.append(
            MandateVersionRecord(
                id=uuid.uuid4(),
                treasury_id=TREASURY_ID,
                version=1,
                status="Expired",
                config=expired,
                config_hash=b"\x00" * 32,
                created_at=datetime.now(UTC),
            )
        )
        cloned = client.post(f"{base_url}/{repository.rows[0].id}/clone")

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "MANDATE_ALREADY_EXPIRED"
    assert cloned.status_code == 201
    assert cloned.json()["draft"]["version"] == 2


def test_problem_extensions_cannot_overwrite_standard_fields() -> None:
    failure = AuthFailure(
        status=422,
        code="X",
        title="t",
        detail="real detail",
        extensions={"detail": "spoofed", "status": 200, "fields": ["a"]},
    )
    request = Request({"type": "http", "path": "/p", "headers": []})

    body = json.loads(problem_response(request, failure).body)

    assert body["detail"] == "real detail"
    assert body["status"] == 422
    assert body["fields"] == ["a"]


def test_mandate_draft_requires_fresh_second_factor() -> None:
    repository = MemoryMandateRepository()
    stale = datetime.now(UTC) - timedelta(minutes=11)
    with make_client(repository, step_up_at=stale) as client:
        response = client.post(
            f"/v1/orgs/{ORG_ID}/treasuries/{TREASURY_ID}/mandates", json=config_payload()
        )

    assert response.status_code == 403
    assert response.json()["code"] == "STEP_UP_REQUIRED"
    assert repository.rows == []
