import io
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self, cast

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr

from treasurypilot_api.admin import api as admin_api
from treasurypilot_api.admin.models import PlatformAdminEvent, SupportGrant
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import SessionAccess, UserRecord
from treasurypilot_api.identity.models import Organization, OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.main import create_app

TOKEN = "x" * 48
AUTH = {"Authorization": f"Bearer {TOKEN}"}
API_ROOT = Path(__file__).parents[1]
ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")


def test_platform_admin_is_unavailable_without_complete_configuration() -> None:
    client = TestClient(create_app(settings=Settings(environment="local")))

    response = client.get("/admin/tenants", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 503


def test_platform_admin_requires_staff_bearer_token() -> None:
    settings = Settings(
        environment="local",
        admin_staff_token=SecretStr(TOKEN),
        admin_staff_id="ops@example.test",
        admin_ip_allowlist="127.0.0.1/32",
    )
    client = TestClient(create_app(settings=settings), client=("127.0.0.1", 50000))

    missing = client.get("/admin/tenants")
    invalid = client.get("/admin/tenants", headers={"Authorization": "Bearer wrong"})

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_platform_admin_uses_socket_peer_and_denies_non_allowlisted_ip() -> None:
    settings = Settings(
        environment="local",
        admin_staff_token=SecretStr(TOKEN),
        admin_staff_id="ops@example.test",
        admin_ip_allowlist="192.0.2.0/24",
    )
    client = TestClient(create_app(settings=settings))

    response = client.get(
        "/admin/tenants",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Forwarded-For": "192.0.2.4",
        },
    )

    assert response.status_code == 403


class _FakeSession:
    def __init__(
        self,
        org: Organization | None,
        added: list[object],
        grant: SupportGrant | None = None,
    ) -> None:
        self.org, self.added, self.counts, self.grant = org, added, [3, 2], grant

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> Self:
        return self

    async def get(self, *_: object, **__: object) -> Organization | None:
        return self.org

    async def scalar(self, statement: object) -> int | SupportGrant | None:
        if "support_grants" in str(statement):
            if (
                self.grant is not None
                and self.grant.staff_user == "ops@example.test"
                and self.grant.scope == "read"
                and self.grant.revoked_at is None
                and self.grant.expires_at > datetime.now(UTC)
            ):
                return self.grant
            return None
        return self.counts.pop(0)

    def add(self, row: object) -> None:
        self.added.append(row)


def _admin_client(
    org: Organization | None, *, grant: SupportGrant | None = None
) -> tuple[TestClient, list[object]]:
    added: list[object] = []
    settings = Settings(
        environment="local",
        admin_staff_token=SecretStr(TOKEN),
        admin_staff_id="ops@example.test",
        admin_ip_allowlist="127.0.0.1/32",
    )
    sessions = cast(Any, lambda: _FakeSession(org, added, grant))
    app = create_app(settings=settings, admin_sessions=sessions)
    return TestClient(app, client=("127.0.0.1", 50000)), added


def _org() -> Organization:
    return Organization(
        id=ORG_ID,
        name="Acme",
        country="VN",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        platform_status="active",
    )


def test_non_ascii_bearer_token_is_401_not_500() -> None:
    client, _ = _admin_client(None)

    response = client.get(
        f"/admin/tenants/{ORG_ID}/health", headers={"Authorization": "Bearer é".encode("latin-1")}
    )

    assert response.status_code == 401


def test_disallowed_ip_gets_403_even_with_invalid_token() -> None:
    settings = Settings(
        environment="local",
        admin_staff_token=SecretStr(TOKEN),
        admin_staff_id="ops@example.test",
        admin_ip_allowlist="192.0.2.0/24",
    )
    client = TestClient(create_app(settings=settings))

    assert (
        client.get("/admin/tenants", headers={"Authorization": "Bearer wrong"}).status_code == 403
    )


def test_malformed_admin_ip_allowlist_fails_at_startup() -> None:
    with pytest.raises(ValueError, match="not-a-cidr"):
        Settings(environment="local", admin_ip_allowlist="not-a-cidr")


def test_tenant_health_success_and_404() -> None:
    client, _ = _admin_client(_org())
    missing, _ = _admin_client(None)

    ok = client.get(f"/admin/tenants/{ORG_ID}/health", headers=AUTH)

    assert ok.status_code == 200
    assert ok.json() == {
        "tenantId": str(ORG_ID),
        "status": "active",
        "activeMembers": 3,
        "treasuries": 2,
    }
    assert missing.get(f"/admin/tenants/{ORG_ID}/health", headers=AUTH).status_code == 404


def test_suspend_persists_status_with_one_audit_event_and_is_idempotent() -> None:
    org = _org()
    client, added = _admin_client(org)

    first = client.post(f"/admin/tenants/{ORG_ID}/suspend", headers=AUTH)
    second = client.post(f"/admin/tenants/{ORG_ID}/suspend", headers=AUTH)

    assert first.status_code == second.status_code == 200
    assert org.platform_status == "suspended"
    assert first.json()["status"] == "suspended"
    assert len(added) == 1
    event = cast(PlatformAdminEvent, added[0])
    assert (event.action, event.actor_id, event.org_id) == (
        "tenant.suspended",
        "ops@example.test",
        ORG_ID,
    )


def test_migration_makes_platform_admin_events_append_only() -> None:
    output = io.StringIO()
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://offline/offline")
    config.output_buffer = output

    command.upgrade(config, "20261014_0016:20261014_0017", sql=True)

    assert "platform_admin_events_append_only" in output.getvalue()


def test_migration_creates_read_only_support_grants() -> None:
    output = io.StringIO()
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://offline/offline")
    config.output_buffer = output

    command.upgrade(config, "20261014_0025:20261014_0026", sql=True)
    command.downgrade(config, "20261014_0026:20261014_0025", sql=True)

    sql = output.getvalue()
    assert "CREATE TABLE support_grants" in sql
    assert "ck_support_grants_read_only" in sql
    assert "DROP TABLE support_grants" in sql


def test_tenant_admin_can_grant_time_limited_read_support(monkeypatch: pytest.MonkeyPatch) -> None:
    client, added = _admin_client(_org())
    user_id = uuid.uuid4()
    member = MemberAccess(
        access=SessionAccess(
            user=UserRecord(user_id, "owner@example.test", "Owner", "active"),
            session_id=uuid.uuid4(),
        ),
        organization_id=ORG_ID,
        roles=frozenset({OrganizationRole.ORG_ADMIN.value}),
    )
    client.app.dependency_overrides[require_member] = lambda: member
    audit_calls: list[dict[str, object]] = []

    async def capture_audit(*_args: object, **kwargs: object) -> None:
        audit_calls.append(kwargs)

    monkeypatch.setattr(admin_api, "write_audit", capture_audit)
    response = client.post(
        f"/v1/orgs/{ORG_ID}/support-grants",
        json={"staffUser": "ops@example.test", "durationHours": 48},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["scope"] == "read"
    assert body["staffUser"] == "ops@example.test"
    assert datetime.fromisoformat(body["expiresAt"]) - datetime.fromisoformat(
        body["createdAt"]
    ) == timedelta(hours=48)
    assert len(added) == 1 and isinstance(added[0], SupportGrant)
    assert audit_calls[0]["action"] == "platform.support.granted"


def test_support_grant_requires_org_admin_or_owner() -> None:
    client, _ = _admin_client(_org())
    member = MemberAccess(
        access=SessionAccess(
            user=UserRecord(uuid.uuid4(), "operator@example.test", "Operator", "active"),
            session_id=uuid.uuid4(),
        ),
        organization_id=ORG_ID,
        roles=frozenset({OrganizationRole.OPERATOR.value}),
    )
    client.app.dependency_overrides[require_member] = lambda: member

    response = client.post(
        f"/v1/orgs/{ORG_ID}/support-grants", json={"staffUser": "ops@example.test"}
    )

    assert response.status_code == 403


def test_support_read_requires_matching_active_grant_and_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_calls: list[dict[str, object]] = []

    async def capture_audit(*_args: object, **kwargs: object) -> None:
        audit_calls.append(kwargs)

    monkeypatch.setattr(admin_api, "write_audit", capture_audit)
    now = datetime.now(UTC)
    grant = SupportGrant(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        staff_user="ops@example.test",
        scope="read",
        expires_at=now + timedelta(hours=1),
        granted_by=uuid.uuid4(),
        created_at=now - timedelta(hours=1),
    )
    client, added = _admin_client(_org(), grant=grant)

    response = client.get(f"/admin/tenants/{ORG_ID}/support", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["tenant"]["id"] == str(ORG_ID)
    assert len(added) == 1
    event = cast(PlatformAdminEvent, added[0])
    assert (event.action, event.actor_id, event.data["scope"]) == (
        "support.read",
        "ops@example.test",
        "read",
    )
    assert audit_calls[0]["action"] == "platform.support.read"
    assert audit_calls[0]["org_id"] == ORG_ID


def test_repeated_grant_is_idempotent_and_normalizes_staff_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    grant = SupportGrant(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        staff_user="ops@example.test",
        scope="read",
        expires_at=now + timedelta(hours=48),
        granted_by=uuid.uuid4(),
        created_at=now - timedelta(hours=1),
    )
    client, added = _admin_client(_org(), grant=grant)
    member = MemberAccess(
        access=SessionAccess(
            user=UserRecord(uuid.uuid4(), "owner@example.test", "Owner", "active"),
            session_id=uuid.uuid4(),
        ),
        organization_id=ORG_ID,
        roles=frozenset({OrganizationRole.ORG_ADMIN.value}),
    )
    client.app.dependency_overrides[require_member] = lambda: member

    async def no_audit(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(admin_api, "write_audit", no_audit)
    url = f"/v1/orgs/{ORG_ID}/support-grants"
    again = client.post(url, json={"staffUser": " OPS@Example.test ", "durationHours": 1})
    bad = client.post(url, json={"staffUser": "not-an-email"})

    assert again.status_code == 201
    assert again.json()["id"] == str(grant.id) and again.json()["status"] == "active"
    assert added == []
    assert bad.status_code == 422


def test_expired_or_missing_support_grant_denies_staff_access() -> None:
    grant = SupportGrant(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        staff_user="ops@example.test",
        scope="read",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        granted_by=uuid.uuid4(),
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    expired_client, _ = _admin_client(_org(), grant=grant)
    missing_client, _ = _admin_client(_org())
    revoked_grant = SupportGrant(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        staff_user="ops@example.test",
        scope="read",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        granted_by=uuid.uuid4(),
        created_at=datetime.now(UTC) - timedelta(hours=1),
        revoked_at=datetime.now(UTC),
    )
    revoked_client, _ = _admin_client(_org(), grant=revoked_grant)

    expired = expired_client.get(f"/admin/tenants/{ORG_ID}/support", headers=AUTH)
    missing = missing_client.get(f"/admin/tenants/{ORG_ID}/support", headers=AUTH)
    revoked = revoked_client.get(f"/admin/tenants/{ORG_ID}/support", headers=AUTH)

    assert expired.status_code == missing.status_code == revoked.status_code == 403


def test_admin_route_surface_cannot_sign_or_move_funds() -> None:
    client, _ = _admin_client(_org())
    admin_routes = {
        (path, method.upper())
        for path, operations in client.app.openapi()["paths"].items()
        if path.startswith("/admin/")
        for method in operations
    }

    assert admin_routes == {
        ("/admin/tenants", "GET"),
        ("/admin/tenants/{tenant_id}/health", "GET"),
        ("/admin/tenants/{tenant_id}/suspend", "POST"),
        ("/admin/tenants/{tenant_id}/support", "GET"),
        ("/admin/tenants/{tenant_id}/data-region", "GET"),
        ("/admin/tenants/{tenant_id}/data-region", "PUT"),
        ("/admin/usage", "GET"),
        ("/admin/usage/{month}/recompute", "POST"),
    }
    assert all(
        method == "GET" or path.endswith(("/suspend", "/recompute", "/data-region"))
        for path, method in admin_routes
    )
