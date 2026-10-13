import json

import pytest
import structlog
from fastapi.testclient import TestClient

from treasurypilot_core.observability import clear_context, current_context
from treasurypilot_signer.main import create_app

HEX64 = "ab" * 32


@pytest.fixture
def client() -> TestClient:
    app = create_app()

    @app.get("/_context")
    async def context() -> dict[str, str]:
        structlog.get_logger().info("in_handler")
        return current_context()

    return TestClient(app)


def test_valid_headers_are_bound_and_request_id_echoed(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    response = client.get(
        "/_context", headers={"X-Request-ID": "req-12345", "X-Org-ID": "org-12345"}
    )

    assert response.headers["x-request-id"] == "req-12345"
    assert response.json() == {
        "correlation_id": "req-12345",
        "request_id": "req-12345",
        "org_id": "org-12345",
    }
    line = json.loads(capsys.readouterr().out.splitlines()[0])
    assert line["service"] == "signer"
    assert line["correlation_id"] == "req-12345"
    assert line["org_id"] == "org-12345"
    assert current_context() == {}


def test_invalid_headers_are_replaced_or_dropped_and_warned(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    response = client.get("/_context", headers={"X-Request-ID": HEX64, "X-Plan-ID": "bad value"})

    request_id = response.headers["x-request-id"]
    assert request_id != HEX64
    assert response.json() == {"correlation_id": request_id, "request_id": request_id}
    warning = json.loads(capsys.readouterr().out.splitlines()[0])
    assert warning["event"] == "invalid_context_header"
    assert warning["headers"] == ["x-request-id", "x-plan-id"]
    assert HEX64 not in json.dumps(warning)
    assert "bad value" not in json.dumps(warning)


def test_context_does_not_leak_between_requests(client: TestClient) -> None:
    clear_context()
    client.get("/_context", headers={"X-Org-ID": "org-12345"})

    assert "org_id" not in client.get("/_context").json()


def test_unhandled_error_keeps_request_id_and_logs_with_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = create_app()

    @app.get("/_boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    response = TestClient(app, raise_server_exceptions=False).get(
        "/_boom", headers={"X-Request-ID": "req-12345"}
    )

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "req-12345"
    out = capsys.readouterr().out.splitlines()
    lines = [json.loads(line) for line in out if line.startswith("{")]
    error = next(line for line in lines if line["event"] == "unhandled_exception")
    assert error["correlation_id"] == "req-12345"
    assert "RuntimeError: boom" in error["exception"]
    assert current_context() == {}
