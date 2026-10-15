from fastapi.testclient import TestClient

from treasurypilot_signer.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["service"] == "signer"


def test_signing_endpoint_is_exposed_and_validates_its_request() -> None:
    response = TestClient(app).post("/sign-and-send", json={})

    assert response.status_code == 422
