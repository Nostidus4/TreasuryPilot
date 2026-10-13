import json

import pytest
from fastapi.testclient import TestClient

from treasurypilot_core.observability import CONTEXT_HEADERS
from treasurypilot_signer.main import app, create_app


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["service"] == "signer"


def test_signing_endpoint_is_not_exposed_before_exe_005() -> None:
    response = TestClient(app).post("/sign-and-send", json={})

    assert response.status_code == 404


def test_request_log_carries_worker_correlation_ids(capsys: pytest.CaptureFixture[str]) -> None:
    ids = {
        "correlation_id": "corr-signer-1",
        "org_id": "org-1",
        "request_id": "req-2",
        "plan_id": "plan-3",
        "operation_id": "op-4",
    }
    client = TestClient(create_app())

    client.get("/health", headers={CONTEXT_HEADERS[key]: value for key, value in ids.items()})

    lines = [json.loads(line) for line in capsys.readouterr().err.splitlines() if line]
    (line,) = [line for line in lines if line["event"] == "http.request"]
    assert line["service"] == "signer"
    assert {key: line[key] for key in ids} == ids
