from __future__ import annotations

import asyncio
import urllib.error
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from treasurypilot_core.notifications import unsubscribe_signature
from treasurypilot_worker.notify import delivery, email
from treasurypilot_worker.notify.delivery import email_route
from treasurypilot_worker.notify.email import (
    EmailNotification,
    PermanentEmailError,
    RenderedEmail,
    render_notification_email,
    send_resend_email,
    unsubscribe_url,
)

SECRET = "x" * 32


def _route(mode: str, event_type: str, severity: str, **overrides: Any) -> str | None:
    values: dict[str, Any] = {
        "delivery_mode": mode,
        "severity": severity,
        "event_type": event_type,
        "active": True,
        "channels": {},
        "categories": {},
    }
    return email_route(**{**values, **overrides})


@pytest.mark.parametrize("mode", ["immediate", "daily", "off"])
@pytest.mark.parametrize(
    ("event_type", "severity"),
    [
        ("CircuitBreakerTripped", "CRITICAL"),
        # Mandatory category without CRITICAL severity must not be consumed under daily/off.
        ("CoverageChanged", "ACTION"),
        ("Discrepancy", "INFO"),
    ],
)
def test_mandatory_events_bypass_cadence_and_off(mode: str, event_type: str, severity: str) -> None:
    assert _route(mode, event_type, severity) == "immediate"
    # Even a muted channel and category cannot suppress a mandatory event.
    assert (
        _route(
            mode,
            event_type,
            severity,
            channels={"email": False},
            categories={"mandatory": False},
        )
        == "immediate"
    )


@pytest.mark.parametrize(
    ("mode", "expected"), [("immediate", "immediate"), ("daily", "daily"), ("off", None)]
)
def test_optional_events_follow_the_selected_cadence(mode: str, expected: str | None) -> None:
    assert _route(mode, "PaymentDone", "INFO") == expected


@pytest.mark.parametrize(
    ("event_type", "channels", "categories"),
    [
        ("PaymentDone", {"email": False}, {}),
        ("ApprovalNeeded", {"email": True}, {"approvals": False}),
    ],
)
def test_muted_channel_or_category_is_consumed_not_sent(
    event_type: str, channels: dict[str, bool], categories: dict[str, bool]
) -> None:
    assert (
        _route("immediate", event_type, "ACTION", channels=channels, categories=categories) is None
    )


def test_inactive_accounts_are_never_emailed() -> None:
    assert _route("immediate", "CircuitBreakerTripped", "CRITICAL", active=False) is None


class _Connection:
    def __init__(self, rows: list[dict[str, Any]], *, fail_mark_sent: bool = False) -> None:
        self.rows = rows
        self.pages = 0
        self.fail_mark_sent = fail_mark_sent
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if query == delivery._PENDING:
            self.pages += 1
            return self.rows if self.pages == 1 else []
        assert query == delivery._CLAIM
        return [{"id": notification_id} for notification_id in args[0]]

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        if query == delivery._MARK_SENT and self.fail_mark_sent:
            raise ConnectionError("database went away")
        return "UPDATE 1"


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def _row(
    user_id: uuid.UUID,
    *,
    mode: str = "immediate",
    event_type: str = "PaymentDone",
    severity: str = "INFO",
    channels: Any = "{}",
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "email": "u@example.test",
        "active": True,
        "title": f"Title {event_type}",
        "body": "body",
        "link": "/x",
        "severity": severity,
        "event_type": event_type,
        "deliver_at": 1,
        "delivery_mode": mode,
        "channels": channels,  # asyncpg returns jsonb as str
        "categories": "{}",
    }


def _settings(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "database_url": "postgresql://unused",
        "resend_api_key": SimpleNamespace(get_secret_value=lambda: "key"),
        "resend_from_email": "notify@example.test",
        "environment": "local",
        "email_unsubscribe_key": SimpleNamespace(get_secret_value=lambda: SECRET),
        "app_base_url": "http://localhost:5173",
        "public_api_base_url": "http://localhost:8000",
    }
    return SimpleNamespace(**{**values, **overrides})


def _run(
    rows: list[dict[str, Any]],
    cadence: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    send: Any = None,
    fail_mark_sent: bool = False,
) -> tuple[dict[str, int], _Connection, list[dict[str, Any]]]:
    connection = _Connection(rows, fail_mark_sent=fail_mark_sent)
    sent: list[dict[str, Any]] = []

    def fake_send(**kwargs: Any) -> None:
        if send is not None:
            send(**kwargs)
        sent.append(kwargs)

    monkeypatch.setattr(delivery, "send_resend_email", fake_send)
    result = asyncio.run(
        delivery.deliver_pending_emails(_Pool(connection), settings=_settings(), cadence=cadence)
    )
    return result, connection, sent


def _ids(connection: _Connection, query: str) -> list[uuid.UUID]:
    return [i for q, args in connection.executed if q == query for i in args[0]]


@pytest.mark.parametrize("mode", ["daily", "off"])
def test_mandatory_non_critical_event_is_emailed_immediately_not_consumed(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row(uuid.uuid4(), mode=mode, event_type="CoverageChanged", severity="ACTION")

    result, connection, sent = _run([row], "immediate", monkeypatch)

    assert result == {"claimed": 1, "sent": 1, "skipped": 0, "failed": 0}
    assert len(sent) == 1
    assert _ids(connection, delivery._MARK_SENT) == [row["id"]]  # marked sent after the send


def test_daily_cadence_leaves_mandatory_events_to_the_immediate_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row(uuid.uuid4(), mode="daily", event_type="CoverageChanged", severity="ACTION")

    result, connection, sent = _run([row], "daily", monkeypatch)

    assert result == {"claimed": 0, "sent": 0, "skipped": 0, "failed": 0}
    assert not sent and not connection.executed


def test_off_mode_optional_mail_is_consumed_without_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row(uuid.uuid4(), mode="off")

    result, connection, sent = _run([row], "immediate", monkeypatch)

    assert result == {"claimed": 0, "sent": 0, "skipped": 1, "failed": 0}
    assert not sent
    assert _ids(connection, delivery._MARK_SENT) == [row["id"]]


def test_daily_digest_is_one_message_per_user_with_a_stable_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = uuid.uuid4()
    rows = [_row(user, mode="daily"), _row(user, mode="daily")]

    result, _, sent = _run(rows, "daily", monkeypatch)

    assert result["sent"] == 2
    assert len(sent) == 1
    assert sent[0]["message"].subject == "TreasuryPilot daily digest"
    assert sent[0]["message"].html.count("<li>") == 2
    assert sent[0]["idempotency_key"].startswith("notification-email/")


def test_immediate_mail_uses_the_notification_id_as_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row(uuid.uuid4())

    _, _, sent = _run([row], "immediate", monkeypatch)

    assert sent[0]["idempotency_key"] == f"notification-email/{row['id']}"


def test_transient_failure_backs_off_instead_of_hot_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row(uuid.uuid4())

    def boom(**_: Any) -> None:
        raise RuntimeError("Resend notification delivery failed")

    result, connection, _ = _run([row], "immediate", monkeypatch, send=boom)

    assert result["failed"] == 1 and result["sent"] == 0
    [(query, args)] = [e for e in connection.executed if e[0] == delivery._FAILED]
    assert args == ([row["id"]], False, delivery.MAX_ATTEMPTS)
    # Backoff, attempt counter and the attempt cap are all part of the SQL contract.
    assert "email_next_attempt_at" in query and "email_attempts + 1" in query
    assert "email_attempts < $3" in delivery._PENDING
    assert "email_next_attempt_at <= now()" in delivery._PENDING


@pytest.mark.parametrize("error", [PermanentEmailError("rejected"), ValueError("bad input")])
def test_permanent_failures_exhaust_attempts_at_once(
    error: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row(uuid.uuid4())

    def boom(**_: Any) -> None:
        raise error

    _, connection, _ = _run([row], "immediate", monkeypatch, send=boom)

    [(_, args)] = [e for e in connection.executed if e[0] == delivery._FAILED]
    assert args[1] is True


def test_failure_marking_sent_after_a_successful_send_does_not_crash_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_row(uuid.uuid4()), _row(uuid.uuid4())]

    result, connection, sent = _run(rows, "immediate", monkeypatch, fail_mark_sent=True)

    # Both emails still go out; the claim lease (and Idempotency-Key) covers the lost update.
    assert result["sent"] == 2 and len(sent) == 2
    assert not [e for e in connection.executed if e[0] == delivery._FAILED]


def test_run_stops_starting_new_users_after_its_time_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [_row(uuid.uuid4()) for _ in range(3)]
    # deadline, first page, user 1 starts, user 2 is past the budget.
    clock = iter([0.0, 0.0, 0.0, 999.0, 999.0, 999.0])
    monkeypatch.setattr(delivery, "time", SimpleNamespace(monotonic=lambda: next(clock)))

    result, _, sent = _run(rows, "immediate", monkeypatch)

    assert len(sent) == 1 and result["sent"] == 1


def test_delivery_requires_a_strong_signing_secret_in_every_environment() -> None:
    for secret in (None, SimpleNamespace(get_secret_value=lambda: "short")):
        with pytest.raises(RuntimeError, match="TP_EMAIL_UNSUBSCRIBE_KEY"):
            asyncio.run(
                delivery.deliver_pending_emails(
                    _Pool(_Connection([])),
                    settings=_settings(email_unsubscribe_key=secret),
                    cadence="immediate",
                )
            )


class _Response:
    status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _send(**overrides: Any) -> None:
    send_resend_email(
        api_key="key",
        from_email="from@example.test",
        recipient="to@example.test",
        message=RenderedEmail("subject", "<p>x</p>", "x"),
        unsubscribe_url_value="https://api.example.test/u",
        idempotency_key="notification-email/1",
        **overrides,
    )


def test_resend_request_carries_the_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Any] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        captured.append(request)
        return _Response()

    monkeypatch.setattr(email.urllib.request, "urlopen", fake_urlopen)

    _send()

    assert captured[0].get_header("Idempotency-key") == "notification-email/1"


@pytest.mark.parametrize(
    ("status", "permanent"), [(400, True), (422, True), (408, False), (429, False), (503, False)]
)
def test_only_non_retryable_4xx_responses_are_permanent(
    status: int, permanent: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_urlopen(request: Any, timeout: float) -> _Response:
        raise urllib.error.HTTPError(request.full_url, status, "err", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(email.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(PermanentEmailError if permanent else RuntimeError) as caught:
        _send()
    assert isinstance(caught.value, PermanentEmailError) is permanent


def test_template_escapes_notification_text_and_links() -> None:
    message = render_notification_email(
        (EmailNotification("<script>", "A & B", '/requests/123?x="', "ACTION"),),
        app_base_url="https://app.example.test/",
    )
    assert "&lt;script&gt;" in message.html
    assert "A &amp; B" in message.html
    assert "&quot;" in message.html
    assert "TreasuryPilot" in message.subject
    assert "/requests/123" in message.text


def test_digest_template_groups_items_and_has_digest_subject() -> None:
    message = render_notification_email(
        (
            EmailNotification("First", "Body one", "/first", "INFO"),
            EmailNotification("Second", "Body two", "/second", "ACTION"),
        ),
        app_base_url="https://app.example.test",
        digest=True,
    )
    assert message.subject == "TreasuryPilot daily digest"
    assert message.html.count("<li>") == 2
    assert "Body one" in message.text and "Body two" in message.text


def test_unsubscribe_signature_is_user_bound_and_requires_a_strong_secret() -> None:
    user_id = uuid.UUID("7fb381b5-4a6e-4a40-a852-9c7504503d20")
    signature = unsubscribe_signature(user_id, SECRET)
    assert len(signature) == 64
    assert signature != unsubscribe_signature(uuid.uuid4(), SECRET)
    assert f"user_id={user_id}" in unsubscribe_url(
        api_base_url="https://api.example.test", user_id=user_id, secret=SECRET
    )
    assert signature in unsubscribe_url(
        api_base_url="https://api.example.test", user_id=user_id, secret=SECRET
    )
    with pytest.raises(ValueError):
        unsubscribe_signature(user_id, "short")


def test_failed_pool_close_does_not_mask_the_original_task_error() -> None:
    import os

    from treasurypilot_worker.tasks import _PublisherRuntime

    class _BrokenPool:
        async def close(self) -> None:
            raise ConnectionError("close failed")

    async def work(_: Any) -> int:
        raise ValueError("original")

    runtime = _PublisherRuntime()
    runtime._pid, runtime._loop, runtime._pool = (
        os.getpid(),
        asyncio.new_event_loop(),
        _BrokenPool(),
    )

    with pytest.raises(ValueError, match="original"):
        runtime.run("postgresql://unused", work)
    assert runtime._pool is None


@pytest.mark.parametrize("key", [None, "short"])
def test_email_task_is_a_logged_no_op_without_a_strong_unsubscribe_key(
    key: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import SecretStr

    from treasurypilot_worker import tasks

    settings = _settings(
        resend_api_key=SecretStr("key"),
        email_unsubscribe_key=SecretStr(key) if key else None,
    )
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)

    assert tasks.send_notification_emails() == {"sent": 0}
