"""Owner-only tightening of circuit rules (RCV-006); rejected before any storage is touched."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import SessionAccess, UserRecord
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.main import create_app

ORG, USER, TREASURY = (uuid.uuid4() for _ in range(3))


def _client(role: str, step_up_age: timedelta = timedelta(0)) -> TestClient:
    app = create_app(settings=Settings(environment="local"))

    async def member(organization_id: uuid.UUID) -> MemberAccess:
        access = SessionAccess(
            user=UserRecord(USER, "u@example.test", None, "active"),
            session_id=uuid.uuid4(),
            step_up_at=datetime.now(UTC) - step_up_age,
        )
        return MemberAccess(access=access, organization_id=organization_id, roles=frozenset({role}))

    app.dependency_overrides[require_member] = member
    return TestClient(app)


URL = f"/v1/orgs/{ORG}/treasuries/{TREASURY}/circuit/rules"


@pytest.mark.parametrize("role", ["Guardian", "Approver", "Operator"])
def test_only_the_owner_may_change_a_rule(role: str) -> None:
    response = _client(role).put(f"{URL}/REJECTIONS", json={"threshold": 2, "windowSeconds": 600})
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("rule", "body"),
    [
        ("REJECTIONS", {"threshold": 5, "windowSeconds": 600}),
        ("DISCREPANCY", {"threshold": 1, "windowSeconds": 0}),
        ("UNEXPECTED_OUTFLOW", {"threshold": 50, "windowSeconds": 0}),
    ],
)
def test_loosening_or_disabling_is_refused(rule: str, body: dict[str, int]) -> None:
    response = _client("Owner").put(f"{URL}/{rule}", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "CIRCUIT_RULE_NOT_TIGHTER"


def test_stale_step_up_is_refused() -> None:
    response = _client("Owner", timedelta(hours=1)).put(
        f"{URL}/REJECTIONS", json={"threshold": 2, "windowSeconds": 600}
    )
    assert response.status_code == 403 and response.json()["code"] == "STEP_UP_REQUIRED"
