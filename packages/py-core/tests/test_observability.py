import asyncio
import json
import logging
from typing import Any

import pytest
import structlog
from structlog.contextvars import bound_contextvars, get_contextvars

from treasurypilot_core.observability import (
    CONTEXT_HEADERS,
    CorrelationMiddleware,
    configure_logging,
    context_headers,
)
from treasurypilot_core.privacy import REDACTED


def _lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in capsys.readouterr().err.splitlines() if line]


def test_structlog_and_stdlib_records_render_as_redacted_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("api")

    with bound_contextvars(correlation_id="corr-1", org_id="org-1"):
        structlog.get_logger("tp.test").info("plan.built", api_key="sk-secret")
        logging.getLogger("tp.stdlib").warning("mail to alice@example.com failed")

    structured, stdlib = _lines(capsys)
    assert structured["event"] == "plan.built"
    assert structured["service"] == "api"
    assert structured["level"] == "info"
    assert structured["correlation_id"] == "corr-1"
    assert structured["org_id"] == "org-1"
    assert structured["api_key"] == REDACTED
    assert stdlib["logger"] == "tp.stdlib"
    assert stdlib["correlation_id"] == "corr-1"
    assert "alice@example.com" not in stdlib["event"]


def test_uvicorn_errors_render_as_json_and_access_log_is_dropped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging.getLogger("uvicorn.error").addHandler(logging.StreamHandler())
    configure_logging("api")

    logging.getLogger("uvicorn.error").error("bind failed for token=abc")
    logging.getLogger("uvicorn.access").info("GET /verify?token=abc")

    (line,) = _lines(capsys)
    assert line["logger"] == "uvicorn.error"
    assert "abc" not in line["event"]


def test_exception_tracebacks_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("worker")

    try:
        raise RuntimeError("password=hunter2")
    except RuntimeError:
        structlog.get_logger().exception("task.failed")

    (line,) = _lines(capsys)
    assert "RuntimeError" in line["exception"]
    assert "hunter2" not in json.dumps(line)


def test_context_headers_carry_only_bound_ids() -> None:
    with bound_contextvars(correlation_id="corr-1", plan_id="plan-9", user="ignored"):
        assert context_headers() == {
            CONTEXT_HEADERS["correlation_id"]: "corr-1",
            CONTEXT_HEADERS["plan_id"]: "plan-9",
        }


def _call(
    app: CorrelationMiddleware, headers: dict[str, str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    async def send(message: Any) -> None:
        sent.append(dict(message))

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
    }
    asyncio.run(app(scope, receive, send))
    return sent, get_contextvars()


async def _echo_context(scope: Any, receive: Any, send: Any) -> None:
    seen.update(get_contextvars())
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


seen: dict[str, Any] = {}


def test_middleware_binds_trusted_ids_and_logs_one_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("signer")
    seen.clear()
    app = CorrelationMiddleware(_echo_context, trusted_ids=("correlation_id", "org_id"))

    sent, after = _call(
        app,
        {
            CONTEXT_HEADERS["correlation_id"]: "corr-7",
            CONTEXT_HEADERS["org_id"]: "org-7",
            CONTEXT_HEADERS["plan_id"]: "untrusted",
        },
    )

    assert seen == {"correlation_id": "corr-7", "org_id": "org-7"}
    assert (b"x-tp-correlation-id", b"corr-7") in sent[0]["headers"]
    assert after == {}
    (line,) = _lines(capsys)
    assert line["event"] == "http.request"
    assert line["correlation_id"] == "corr-7"
    assert line["org_id"] == "org-7"
    assert line["status"] == 204


def test_middleware_replaces_malformed_correlation_id() -> None:
    seen.clear()
    with bound_contextvars(stale="from-previous-request"):
        _call(CorrelationMiddleware(_echo_context), {CONTEXT_HEADERS["correlation_id"]: "bad id\n"})

    assert set(seen) == {"correlation_id"}
    assert seen["correlation_id"] != "bad id\n"
