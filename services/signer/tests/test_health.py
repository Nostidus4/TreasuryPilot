from fastapi.testclient import TestClient

from treasurypilot_signer.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["service"] == "signer"


def test_signing_endpoint_is_not_exposed_before_exe_005() -> None:
    response = TestClient(app).post("/sign-and-send", json={})

    assert response.status_code == 404
