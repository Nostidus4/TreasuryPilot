from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from treasurypilot_core.notifications import NotificationChannel, preference_allows
from treasurypilot_worker.notify import delivery
from treasurypilot_worker.notify.delivery import should_send_email
from treasurypilot_worker.notify.email import (
    EmailNotification,
    render_notification_email,
    unsubscribe_signature,
    unsubscribe_url,
)


@pytest.mark.parametrize(
    ("mode", "severity", "cadence", "expected"),
    [
        ("immediate", "ACTION", "immediate", True),
        ("daily", "ACTION", "immediate", False),
        ("daily", "ACTION", "daily", True),
        ("off", "ACTION", "immediate", False),
        ("off", "CRITICAL", "immediate", True),
        ("daily", "CRITICAL", "immediate", True),
        ("daily", "CRITICAL", "daily", False),
    ],
)
def test_security_notifications_always_use_mandatory_immediate_path(
    mode: str, severity: str, cadence: str, expected: bool
) -> None:
    assert should_send_email(delivery_mode=mode, severity=severity, cadence=cadence) is expected


@pytest.mark.parametrize(
    ("event_type", "channels", "categories", "expected"),
    [
        ("PaymentDone", {"email": False}, {}, False),
        ("ApprovalNeeded", {"email": True}, {"approvals": False}, False),
        ("PaymentDone", {"email": True}, {"payments": True}, True),
        # #387's mandatory policy bypasses all channel/category suppression.
        ("CircuitBreakerTripped", {"email": False}, {"mandatory": False}, True),
    ],
)
def test_email_obeys_shared_channel_and_category_preferences(
    event_type: str, channels: dict[str, bool], categories: dict[str, bool], expected: bool
) -> None:
    assert (
        preference_allows(
            event_type, NotificationChannel.EMAIL, channels=channels, categories=categories
        )
        is expected
    )


@pytest.mark.parametrize(
    ("delivery_mode", "event_type", "severity", "cadence", "expected"),
    [
        ("off", "PaymentDone", "INFO", "immediate", False),
        ("daily", "PaymentDone", "INFO", "immediate", False),
        ("daily", "PaymentDone", "INFO", "daily", True),
        # Mandatory security events bypass off/daily selections and deliver immediately.
        ("off", "CircuitBreakerTripped", "CRITICAL", "immediate", True),
        ("daily", "CircuitBreakerTripped", "CRITICAL", "daily", False),
    ],
)
def test_email_cadence_off_daily_and_mandatory_bypass(
    delivery_mode: str, event_type: str, severity: str, cadence: str, expected: bool
) -> None:
    assert (
        should_send_email(
            delivery_mode=delivery_mode, event_type=event_type, severity=severity, cadence=cadence
        )
        is expected
    )


class _DeliveryConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetch(self, *_args: object) -> list[dict[str, object]]:
        return self.rows

    async def execute(self, query: str, notification_id: object) -> str:
        self.executed.append((query, notification_id))
        return "UPDATE 1"


class _DeliveryPool:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.connection = _DeliveryConnection(rows)

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def test_delivery_path_skips_off_and_muted_mail_but_sends_mandatory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = uuid.uuid4()
    records = [
        {
            "id": uuid.uuid4(),
            "user_id": user,
            "email": "u@example.test",
            "title": "Muted",
            "body": "body",
            "link": "/x",
            "severity": "ACTION",
            "event_type": "ApprovalNeeded",
            "created_at": 1,
            "delivery_mode": "off",
            "channels": {"email": False},
            "categories": {},
            "due": False,
        },
        {
            "id": uuid.uuid4(),
            "user_id": user,
            "email": "u@example.test",
            "title": "Security",
            "body": "urgent",
            "link": "/security",
            "severity": "CRITICAL",
            "event_type": "CircuitBreakerTripped",
            "created_at": 2,
            "delivery_mode": "off",
            "channels": {"email": False},
            "categories": {"mandatory": False},
            "due": True,
        },
    ]
    pool = _DeliveryPool(records)
    sent: list[object] = []
    monkeypatch.setattr(delivery, "send_resend_email", lambda **kwargs: sent.append(kwargs))
    settings = SimpleNamespace(
        database_url="postgresql://unused",
        resend_api_key=type("Secret", (), {"get_secret_value": lambda self: "key"})(),
        resend_from_email="notify@example.test",
        environment="local",
        session_secret=None,
        app_base_url="http://localhost:5173",
        public_api_base_url="http://localhost:8000",
    )

    result = asyncio.run(
        delivery.deliver_pending_emails(pool, settings=settings, cadence="immediate")
    )

    assert result == {"claimed": 2, "sent": 1, "skipped": 1, "failed": 0}
    assert len(sent) == 1
    assert sent[0]["recipient"] == "u@example.test"
    assert any(
        query == delivery._MARK_SENT and notification_id == records[1]["id"]
        for query, notification_id in pool.connection.executed
    )


def test_delivery_path_sends_daily_digest_for_daily_preference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "email": "daily@example.test",
        "title": "Payment complete",
        "body": "Your payment settled",
        "link": "/payments/1",
        "severity": "INFO",
        "event_type": "PaymentDone",
        "created_at": 1,
        "delivery_mode": "daily",
        "channels": {"email": True},
        "categories": {"payments": True},
        "due": True,
    }
    pool = _DeliveryPool([record])
    sent: list[object] = []
    monkeypatch.setattr(delivery, "send_resend_email", lambda **kwargs: sent.append(kwargs))
    settings = SimpleNamespace(
        database_url="postgresql://unused",
        resend_api_key=type("Secret", (), {"get_secret_value": lambda self: "key"})(),
        resend_from_email="notify@example.test",
        environment="local",
        session_secret=None,
        app_base_url="http://localhost:5173",
        public_api_base_url="http://localhost:8000",
    )

    result = asyncio.run(delivery.deliver_pending_emails(pool, settings=settings, cadence="daily"))

    assert result == {"claimed": 1, "sent": 1, "skipped": 0, "failed": 0}
    assert len(sent) == 1
    assert sent[0]["message"].subject == "TreasuryPilot daily digest"


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
    signature = unsubscribe_signature(user_id, "x" * 32)
    assert len(signature) == 64
    assert signature != unsubscribe_signature(uuid.uuid4(), "x" * 32)
    assert f"user_id={user_id}" in unsubscribe_url(
        api_base_url="https://api.example.test", user_id=user_id, secret="x" * 32
    )
    with pytest.raises(ValueError):
        unsubscribe_signature(user_id, "short")
