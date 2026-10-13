import json
import logging
from collections.abc import Iterator
from uuid import UUID

import pytest
import structlog

from treasurypilot_core.observability import (
    bind_context,
    clear_context,
    configure_logging,
    context_from_headers,
    current_context,
    is_valid_id,
)

HEX64 = "ab" * 32


@pytest.fixture(autouse=True)
def _clean_logging() -> Iterator[None]:
    clear_context()
    yield
    clear_context()
    structlog.reset_defaults()


@pytest.mark.parametrize("value", ["req-12345", "0x" + HEX64[:62], "a.b_c:d-e1", "x" * 64])
def test_valid_ids(value: str) -> None:
    assert is_valid_id(value)


@pytest.mark.parametrize(
    "value",
    [None, "", "short", "x" * 65, "has space1", "line\nbreak1", HEX64, "token:12345678"],
)
def test_invalid_ids(value: object) -> None:
    assert not is_valid_id(value)


def test_headers_keep_valid_ids() -> None:
    context, invalid = context_from_headers(
        {"x-request-id": "req-12345", "x-org-id": "org-12345", "x-plan-id": "plan-12345"}
    )

    assert context == {
        "correlation_id": "req-12345",
        "request_id": "req-12345",
        "org_id": "org-12345",
        "plan_id": "plan-12345",
    }
    assert invalid == []


def test_invalid_request_id_is_replaced_and_other_invalid_ids_dropped() -> None:
    context, invalid = context_from_headers(
        {"x-request-id": HEX64, "x-org-id": "bad value", "x-operation-id": "op-12345"}
    )

    UUID(context["request_id"])
    assert context["correlation_id"] == context["request_id"]
    assert "org_id" not in context
    assert context["operation_id"] == "op-12345"
    assert invalid == ["x-request-id", "x-org-id"]


def test_missing_request_id_gets_a_uuid() -> None:
    context, invalid = context_from_headers({})

    UUID(context["request_id"])
    assert invalid == []


def test_bind_current_and_clear_context() -> None:
    bind_context(correlation_id="corr-12345", plan_id="plan-12345")

    assert current_context() == {"correlation_id": "corr-12345", "plan_id": "plan-12345"}
    clear_context()
    assert current_context() == {}


def test_bind_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        bind_context(password="x")


def test_json_log_has_context_service_and_redaction(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("worker", "INFO", "json")
    bind_context(correlation_id="corr-12345", org_id="org-12345")

    structlog.get_logger().info("hello", authorization="Bearer abc.def.ghi", key=HEX64)
    structlog.get_logger().debug("filtered")

    line = json.loads(capsys.readouterr().out)
    assert line["event"] == "hello"
    assert line["service"] == "worker"
    assert line["level"] == "info"
    assert line["correlation_id"] == "corr-12345"
    assert line["org_id"] == "org-12345"
    assert line["timestamp"].endswith("Z")
    assert "abc.def.ghi" not in json.dumps(line)
    assert HEX64 not in json.dumps(line)


def test_console_format_is_redacted_too(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("api", "DEBUG", "console")

    structlog.get_logger().debug("hello", key=HEX64)

    out = capsys.readouterr().out
    assert "hello" in out
    assert HEX64 not in out


def test_unknown_level_is_rejected() -> None:
    with pytest.raises(ValueError):
        configure_logging("api", "LOUD")


def test_stdlib_logs_get_context_redaction_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("worker", "INFO", "json")
    bind_context(correlation_id="corr-12345")

    logging.getLogger("celery.app.trace").info("Task succeeded: %s", {"key": HEX64})

    line = json.loads(capsys.readouterr().out)
    assert line["event"].startswith("Task succeeded")
    assert line["service"] == "worker"
    assert line["correlation_id"] == "corr-12345"
    assert HEX64 not in json.dumps(line)


def test_reconfigure_keeps_foreign_handlers_and_one_own_handler(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    configure_logging("api", "INFO", "json")
    configure_logging("api", "INFO", "json")

    logging.getLogger("treasurypilot_api.identity").warning("delivery failed")

    assert "delivery failed" in caplog.text
    assert len(capsys.readouterr().out.splitlines()) == 1
