import io
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self, cast

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr

from treasurypilot_api.admin.models import PlatformAdminEvent
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.models import Organization
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
    def __init__(self, org: Organization | None, added: list[object]) -> None:
        self.org, self.added, self.counts = org, added, [3, 2]

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> Self:
        return self

    async def get(self, *_: object, **__: object) -> Organization | None:
        return self.org

    async def scalar(self, *_: object) -> int:
        return self.counts.pop(0)

    def add(self, row: object) -> None:
        self.added.append(row)


def _admin_client(org: Organization | None) -> tuple[TestClient, list[object]]:
    added: list[object] = []
    settings = Settings(
        environment="local",
        admin_staff_token=SecretStr(TOKEN),
        admin_staff_id="ops@example.test",
        admin_ip_allowlist="127.0.0.1/32",
    )
    sessions = cast(Any, lambda: _FakeSession(org, added))
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
