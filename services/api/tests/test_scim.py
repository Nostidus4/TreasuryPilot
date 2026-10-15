from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.memberships import LastAdministrator, LastOwner
from treasurypilot_api.identity.scim import (
    SCIM_GROUP_SCHEMA,
    SCIM_PATCH_SCHEMA,
    ScimGroupConflict,
    ScimGroupInvalidMember,
    ScimGroupNotAllowed,
    ScimGroupRecord,
    ScimUserRecord,
    _group_patch_members,
    _GroupPatch,
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
        self.organization_present = True
        self.groups: dict[uuid.UUID, ScimGroupRecord] = {}

    async def organization_exists(self, organization_id: uuid.UUID) -> bool:
        return self.organization_present

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

    async def list_groups(
        self,
        *,
        organization_id: uuid.UUID,
        display_name: str | None,
        start_index: int,
        count: int,
    ) -> tuple[int, tuple[ScimGroupRecord, ...]]:
        records = tuple(
            sorted(
                (
                    group
                    for group in self.groups.values()
                    if display_name is None or group.display_name == display_name
                ),
                key=lambda item: (item.display_name, str(item.id)),
            )
        )
        return len(records), records[start_index - 1 : start_index - 1 + count]

    async def get_group(
        self, *, organization_id: uuid.UUID, group_id: uuid.UUID
    ) -> ScimGroupRecord | None:
        return self.groups.get(group_id)

    async def create_group(
        self,
        *,
        organization_id: uuid.UUID,
        display_name: str,
        member_ids: tuple[uuid.UUID, ...],
        role_map: Mapping[str, list[str]],
        now: datetime,
    ) -> ScimGroupRecord:
        if display_name not in role_map:
            raise ScimGroupNotAllowed
        if any(group.display_name == display_name for group in self.groups.values()):
            raise ScimGroupConflict
        if not set(member_ids) <= {self.user.id}:
            raise ScimGroupInvalidMember
        record = ScimGroupRecord(
            uuid.uuid4(), display_name, tuple(sorted(set(member_ids), key=str)), now, now
        )
        self.groups[record.id] = record
        return record

    async def patch_group_members(
        self,
        *,
        organization_id: uuid.UUID,
        group_id: uuid.UUID,
        add_member_ids: tuple[uuid.UUID, ...],
        remove_member_ids: tuple[uuid.UUID, ...] | None,
        role_map: Mapping[str, list[str]],
        now: datetime,
    ) -> ScimGroupRecord | None:
        record = self.groups.get(group_id)
        if record is None:
            return None
        if record.display_name not in role_map:
            raise ScimGroupNotAllowed
        if not set(add_member_ids) <= {self.user.id}:
            raise ScimGroupInvalidMember
        member_ids = set(record.member_ids)
        if remove_member_ids is None:
            member_ids.clear()
        else:
            member_ids.difference_update(remove_member_ids)
        member_ids.update(add_member_ids)
        updated = replace(record, member_ids=tuple(sorted(member_ids, key=str)), last_modified=now)
        self.groups[group_id] = updated
        return updated

    async def delete_group(
        self,
        *,
        organization_id: uuid.UUID,
        group_id: uuid.UUID,
        role_map: Mapping[str, list[str]],
        now: datetime,
    ) -> bool:
        return self.groups.pop(group_id, None) is not None

    async def reconcile_group_roles(
        self,
        *,
        organization_id: uuid.UUID | None,
        role_map: Mapping[str, list[str]],
        now: datetime,
    ) -> None:
        return None


def _client(
    repository: MemoryScimRepository | None = None,
    *,
    configured: bool = True,
    group_role_map: dict[str, list[str]] | None = None,
) -> TestClient:
    settings = Settings(
        environment="local",
        scim_bearer_token=SecretStr(TOKEN) if configured else None,
        scim_organization_id=ORG_ID if configured else None,
        scim_group_role_map=json.dumps(group_role_map or {}),
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
    with pytest.raises(ValidationError):
        Settings(
            environment="local",
            scim_bearer_token=SecretStr(TOKEN),
            scim_organization_id=ORG_ID,
            scim_group_role_map='{"Owners": ["Owner"]}',
        )
    with pytest.raises(ValidationError):
        Settings(
            environment="local",
            scim_bearer_token=SecretStr(TOKEN),
            scim_organization_id=ORG_ID,
            scim_group_role_map='{"Ops": ["Operator"], "ops": ["Finance"]}',
        )
    with pytest.raises(ValidationError):
        Settings(
            environment="local",
            scim_group_role_map='{"Ops": ["Operator"]}',
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


@pytest.mark.parametrize("value", ["False", "false", " FALSE "])
def test_scim_patch_accepts_entra_string_false(value: str) -> None:
    repository = MemoryScimRepository()
    with _client(repository) as client:
        response = client.patch(f"/scim/v2/Users/{USER_ID}", json=_patch(value), headers=_auth())
        assert response.status_code == 200
        assert response.json()["active"] is False
        pathless = client.patch(
            f"/scim/v2/Users/{USER_ID}",
            json={
                "schemas": [SCIM_PATCH_SCHEMA],
                "Operations": [{"op": "Replace", "value": {"active": value}}],
            },
            headers=_auth(),
        )
        assert pathless.status_code == 200


@pytest.mark.parametrize("value", ["True", "true", "", "no", 0, None])
def test_scim_patch_still_rejects_other_active_values(value: object) -> None:
    repository = MemoryScimRepository()
    with _client(repository) as client:
        response = client.patch(f"/scim/v2/Users/{USER_ID}", json=_patch(value), headers=_auth())
    assert response.status_code == 400
    assert repository.deactivation_arguments is None


@pytest.mark.parametrize(
    "params",
    [
        {"startIndex": "1_0"},
        {"startIndex": " 1"},
        {"startIndex": "-1"},
        {"startIndex": "99999999999999999999"},
        {"startIndex": str(2**31)},
        {"startIndex": "0"},
        {"count": "1_0"},
        {"count": "101"},
        {"count": "99999999999999999999"},
        {"count": "\u0661"},
    ],
)
def test_scim_rejects_malformed_or_oversized_pagination(params: dict[str, str]) -> None:
    repository = MemoryScimRepository()
    with _client(repository) as client:
        response = client.get("/scim/v2/Users", params=params, headers=_auth())
    assert response.status_code == 400
    assert response.json()["scimType"] == "invalidValue"
    assert repository.list_arguments is None


def test_scim_accepts_maximum_start_index() -> None:
    with _client(MemoryScimRepository()) as client:
        response = client.get(
            "/scim/v2/Users", params={"startIndex": str(2**31 - 1)}, headers=_auth()
        )
    assert response.status_code == 200


def test_scim_rate_limits_repeated_bad_tokens(caplog: pytest.LogCaptureFixture) -> None:
    bad = {"Authorization": "Bearer wrong-token-wrong-token-wrong-token"}
    with _client(MemoryScimRepository()) as client:
        statuses = [client.get("/scim/v2/Users", headers=bad).status_code for _ in range(11)]
        assert statuses == [401] * 10 + [429]
        limited = client.get("/scim/v2/Users", headers=bad)
        assert int(limited.headers["retry-after"]) >= 1
        assert limited.json()["status"] == "429"
    assert "wrong-token" not in caplog.text
    assert "invalid bearer token" in caplog.text


def test_scim_reports_a_missing_configured_organization(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = MemoryScimRepository()
    repository.organization_present = False
    with _client(repository) as client:
        response = client.get("/scim/v2/Users", headers=_auth())
    assert response.status_code == 503
    assert "organization does not exist" in response.json()["detail"]
    assert str(ORG_ID) in caplog.text


def test_scim_groups_are_allowlisted_tenant_scoped_and_members_can_be_updated() -> None:
    repository = MemoryScimRepository()
    role_map = {"Treasury Operators": ["Operator"], "Finance Team": ["Finance"]}
    with _client(repository, group_role_map=role_map) as client:
        hidden = client.get("/scim/v2/Groups", headers=_auth())
        assert hidden.status_code == 200
        assert hidden.json()["totalResults"] == 0

        invalid = client.post(
            "/scim/v2/Groups",
            json={"schemas": [SCIM_GROUP_SCHEMA], "displayName": "Owners"},
            headers=_auth(),
        )
        assert invalid.status_code == 400
        assert invalid.json()["scimType"] == "invalidValue"

        created = client.post(
            "/scim/v2/Groups",
            json={
                "schemas": [SCIM_GROUP_SCHEMA],
                "displayName": "Treasury Operators",
                "members": [{"value": str(USER_ID), "type": "User"}],
            },
            headers=_auth(),
        )
        assert created.status_code == 201
        assert created.headers["content-type"].startswith("application/scim+json")
        group = created.json()
        group_id = group["id"]
        assert group["members"][0]["value"] == str(USER_ID)

        filtered = client.get(
            "/scim/v2/Groups",
            params={"filter": 'displayName eq "Treasury Operators"'},
            headers=_auth(),
        )
        assert filtered.json()["totalResults"] == 1

        invalid_member = client.patch(
            f"/scim/v2/Groups/{group_id}",
            json={
                "schemas": [SCIM_PATCH_SCHEMA],
                "Operations": [
                    {
                        "op": "add",
                        "path": "members",
                        "value": [{"value": str(uuid.uuid4()), "type": "User"}],
                    }
                ],
            },
            headers=_auth(),
        )
        assert invalid_member.status_code == 400

        removed = client.patch(
            f"/scim/v2/Groups/{group_id}",
            json={
                "schemas": [SCIM_PATCH_SCHEMA],
                "Operations": [{"op": "remove", "path": f'members[value eq "{USER_ID}"]'}],
            },
            headers=_auth(),
        )
        assert removed.status_code == 200
        assert removed.json()["members"] == []

        assert client.delete(f"/scim/v2/Groups/{group_id}", headers=_auth()).status_code == 204
        assert client.get(f"/scim/v2/Groups/{group_id}", headers=_auth()).status_code == 404


def test_scim_group_patch_rejects_nested_and_role_changes() -> None:
    repository = MemoryScimRepository()
    with _client(repository, group_role_map={"Treasury Operators": ["Operator"]}) as client:
        nested = client.post(
            "/scim/v2/Groups",
            json={
                "schemas": [SCIM_GROUP_SCHEMA],
                "displayName": "Treasury Operators",
                "members": [{"value": str(USER_ID), "type": "Group"}],
            },
            headers=_auth(),
        )
        assert nested.status_code == 400

        created = client.post(
            "/scim/v2/Groups",
            json={"schemas": [SCIM_GROUP_SCHEMA], "displayName": "Treasury Operators"},
            headers=_auth(),
        )
        group_id = created.json()["id"]
        role_change = client.patch(
            f"/scim/v2/Groups/{group_id}",
            json={
                "schemas": [SCIM_PATCH_SCHEMA],
                "Operations": [{"op": "replace", "path": "displayName", "value": "Owners"}],
            },
            headers=_auth(),
        )
        assert role_change.status_code == 400


def test_scim_groups_are_disabled_without_an_allowlist() -> None:
    with _client(MemoryScimRepository()) as client:
        assert client.get("/scim/v2/Groups", headers=_auth()).status_code == 404


def test_group_patch_replace_swaps_members_and_checks_display_name() -> None:
    first, second = sorted((uuid.uuid4(), uuid.uuid4()), key=str)

    def patch(*operations: dict[str, object]) -> object:
        return _group_patch_members(
            {"schemas": [SCIM_PATCH_SCHEMA], "Operations": list(operations)}
        )

    members = patch(
        {"op": "Replace", "path": "members", "value": [{"value": str(first)}]},
        {"op": "Add", "path": "members", "value": [{"value": str(second)}]},
    )
    assert members == _GroupPatch((first, second), None, None)
    assert patch({"op": "replace", "path": "displayName", "value": "Ops"}) == _GroupPatch(
        (), (), "Ops"
    )
    assert patch({"op": "replace", "path": "displayName", "value": " "}) is None
    assert patch({"op": "add", "path": "displayName", "value": "Ops"}) is None
