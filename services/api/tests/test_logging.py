import json
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from treasurypilot_api.config import Settings
from treasurypilot_api.main import create_app

CORRELATION_HEADER = "x-tp-correlation-id"


def _request_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    lines = [json.loads(line) for line in capsys.readouterr().err.splitlines() if line]
    return [line for line in lines if line.get("event") == "http.request"]


def test_request_log_carries_inbound_correlation_and_path_org_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = TestClient(create_app(settings=Settings(environment="local")))
    org_id = str(uuid4())

    response = client.get(f"/v1/orgs/{org_id}", headers={CORRELATION_HEADER: "corr-api-1"})

    assert response.headers[CORRELATION_HEADER] == "corr-api-1"
    (line,) = _request_lines(capsys)
    assert line["service"] == "api"
    assert line["correlation_id"] == "corr-api-1"
    assert line["org_id"] == org_id
    assert line["status"] == response.status_code


def test_api_ignores_client_supplied_business_ids(capsys: pytest.CaptureFixture[str]) -> None:
    client = TestClient(create_app(settings=Settings(environment="local")))

    response = client.get("/v1/health", headers={"x-tp-org-id": "spoofed"})

    (line,) = _request_lines(capsys)
    assert "org_id" not in line
    assert line["correlation_id"] == response.headers[CORRELATION_HEADER]
