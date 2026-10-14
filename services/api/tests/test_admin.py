from fastapi.testclient import TestClient
from pydantic import SecretStr

from treasurypilot_api.config import Settings
from treasurypilot_api.main import create_app

TOKEN = "x" * 48


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
    client = TestClient(create_app(settings=settings))

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
