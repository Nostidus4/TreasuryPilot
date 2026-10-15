from typing import cast

from fastapi.testclient import TestClient

from treasurypilot_signer.main import app, create_app
from treasurypilot_signer.service import SigningService


def test_health_reports_a_configured_signer() -> None:
    configured = create_app(signer_override=cast(SigningService, object()))

    with TestClient(configured) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["service"] == "signer"


def test_health_reports_an_unconfigured_signer() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unconfigured"


def test_signing_endpoint_is_exposed_and_validates_its_request() -> None:
    response = TestClient(app).post("/sign-and-send", json={})

    assert response.status_code == 422
