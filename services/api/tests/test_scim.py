from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.memberships import LastAdministrator, LastOwner
from treasurypilot_api.identity.scim import (
    SCIM_PATCH_SCHEMA,
    ScimUserRecord,
)
from treasurypilot_api.main import create_app

TOKEN = "scim-test-token-with-at-least-32-bytes"
ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
USER_ID = uuid.UUID("00000000-0000-7000-8000-000000000020")
NOW = datetime(2026, 10, 15, tzinfo=UTC)


class MemoryScimRepository:
    def __init__(self) -> None:
        self.user = ScimUserRecord(
            id=USER_ID,
            user_name="person@example.com",
            display_name="Person",
            active=True,
            created_at=NOW,
            last_modified=NOW,
        )
        self.list_arguments: dict[str, object] | None = None
        self.deactivation_arguments: dict[str, object] | None = None
        self.deactivation_error: Exception | None = None

    async def list_users(
        self,
        *,
        organization_id: uuid.UUID,
        user_name: str | None,
        start_index: int,
        count: int,
    ) -> tuple[int, tuple[ScimUserRecord, ...]]:
        self.list_arguments = {
            "organization_id": organization_id,
            "user_name": user_name,
            "start_index": start_index,
            "count": count,
        }
        if user_name is not None and user_name != self.user.user_name:
            return 0, ()
        records = (self.user,) if count > 0 and start_index == 1 else ()
        return 1, records

    async def get_user(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> ScimUserRecord | None:
        return self.user if user_id == self.user.id else None

    async def deactivate_user(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, now: datetime
    ) -> ScimUserRecord | None:
        self.deactivation_arguments = {
            "organization_id": organization_id,
            "user_id": user_id,
            "now": now,
        }
        if self.deactivation_error is not None:
            raise self.deactivation_error
        if user_id != self.user.id:
            return None
        self.user = replace(self.user, active=False, last_modified=now)
        return self.user


def _client(
    repository: MemoryScimRepository | None = None,
    *,
    configured: bool = True,
) -> TestClient:
    settings = Settings(
        environment="local",
        scim_bearer_token=SecretStr(TOKEN) if configured else None,
        scim_organization_id=ORG_ID if configured else None,
    )
    app = create_app(settings=settings, scim_repository=repository)
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _patch(active: object) -> dict[str, object]:
    return {
        "schemas": [SCIM_PATCH_SCHEMA],
        "Operations": [{"op": "replace", "path": "active", "value": active}],
    }


def test_scim_configuration_requires_a_long_paired_token_and_organization() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="local", scim_bearer_token=SecretStr(TOKEN))
    with pytest.raises(ValidationError):
        Settings(
            environment="local",
            scim_bearer_token=SecretStr("too-short"),
            scim_organization_id=ORG_ID,
        )


def test_scim_is_hidden_until_configured_and_requires_bearer_auth() -> None:
    with _client(configured=False) as client:
        assert client.get("/scim/v2/Users").status_code == 404

    repository = MemoryScimRepository()
    with _client(repository) as client:
        response = client.get("/scim/v2/Users")
        assert response.status_code == 401
        assert response.json()["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
        assert response.headers["www-authenticate"] == "Bearer"
        assert (
            client.get("/scim/v2/Users", headers={"Authorization": f"Bearer {TOKEN}x"}).status_code
            == 401
        )


def test_scim_lists_existing_tenant_users_and_supports_exact_username_filter() -> None:
    repository = MemoryScimRepository()
    with _client(repository) as client:
        response = client.get(
            "/scim/v2/Users",
            params={"filter": 'userName eq "Person@Example.com"', "startIndex": 1, "count": 1},
            headers=_auth(),
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/scim+json")
        body = response.json()
        assert body["totalResults"] == 1
        assert body["Resources"][0]["id"] == str(USER_ID)
        assert body["Resources"][0]["active"] is True
        assert repository.list_arguments == {
            "organization_id": ORG_ID,
            "user_name": "person@example.com",
            "start_index": 1,
            "count": 1,
        }

        invalid = client.get(
            "/scim/v2/Users", params={"filter": 'userName co "person"'}, headers=_auth()
        )
        assert invalid.status_code == 400
        assert invalid.json()["scimType"] == "invalidFilter"

        invalid_page = client.get("/scim/v2/Users", params={"startIndex": "zero"}, headers=_auth())
        assert invalid_page.status_code == 400
        assert invalid_page.json()["scimType"] == "invalidValue"


def test_scim_reads_resources_only_in_configured_tenant() -> None:
    with _client(MemoryScimRepository()) as client:
        response = client.get(f"/scim/v2/Users/{USER_ID}", headers=_auth())
        assert response.status_code == 200
        assert response.json()["schemas"] == ["urn:ietf:params:scim:schemas:core:2.0:User"]
        assert response.json()["userName"] == "person@example.com"
        assert client.get("/scim/v2/Users/not-a-uuid", headers=_auth()).status_code == 404
        assert client.get(f"/scim/v2/Users/{uuid.uuid4()}", headers=_auth()).status_code == 404


def test_scim_patch_only_allows_deactivation_and_is_idempotent() -> None:
    repository = MemoryScimRepository()
    with _client(repository) as client:
        rejected = client.patch(f"/scim/v2/Users/{USER_ID}", json=_patch(True), headers=_auth())
        assert rejected.status_code == 400
        assert repository.deactivation_arguments is None

        response = client.patch(f"/scim/v2/Users/{USER_ID}", json=_patch(False), headers=_auth())
        assert response.status_code == 200
        assert response.json()["active"] is False
        assert repository.deactivation_arguments is not None
        assert repository.deactivation_arguments["organization_id"] == ORG_ID

        repeated = client.patch(
            f"/scim/v2/Users/{USER_ID}",
            json={
                "schemas": [SCIM_PATCH_SCHEMA],
                "Operations": [{"op": "replace", "value": {"active": False}}],
            },
            headers=_auth(),
        )
        assert repeated.status_code == 200
        assert repeated.json()["active"] is False


@pytest.mark.parametrize(
    ("failure", "detail"),
    [
        (LastAdministrator(), "last OrgAdmin"),
        (LastOwner(), "last Owner"),
    ],
)
def test_scim_cannot_deprovision_the_last_privileged_member(
    failure: Exception, detail: str
) -> None:
    repository = MemoryScimRepository()
    repository.deactivation_error = failure
    with _client(repository) as client:
        response = client.patch(f"/scim/v2/Users/{USER_ID}", json=_patch(False), headers=_auth())
    assert response.status_code == 409
    assert response.json()["scimType"] == "mutability"
    assert detail in response.json()["detail"]
