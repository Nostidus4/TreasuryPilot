from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.notifications.webhook_api import (
    MAX_ENABLED_ENDPOINTS,
    CreateWebhookRequest,
    create_endpoint,
    disable_endpoint,
)


def test_webhook_endpoint_request_normalizes_event_filters() -> None:
    payload = CreateWebhookRequest(
        url="https://hooks.example.test/treasury/events",
        event_types=["ApprovalNeeded", "ApprovalNeeded", "PaymentDone"],
    )

    assert payload.event_types == ["ApprovalNeeded", "PaymentDone"]
    assert payload.url == "https://hooks.example.test/treasury/events"


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.test/event",
        "https://127.0.0.1/event",
        "https://user:pass@hooks.example.test/event",
        "https://hooks.example.test/event#fragment",
    ],
)
def test_webhook_endpoint_rejects_unsafe_url_forms(url: str) -> None:
    with pytest.raises(ValidationError):
        CreateWebhookRequest(url=url, event_types=["ApprovalNeeded"])


@pytest.mark.parametrize("event_type", ["Bogus", "approvalneeded", "NeedsReview:Nobody", "*"])
def test_webhook_endpoint_rejects_unknown_event_types(event_type: str) -> None:
    with pytest.raises(ValidationError, match="unknown event types"):
        CreateWebhookRequest(url="https://hooks.example.test/e", event_types=[event_type])


def test_webhook_endpoint_accepts_review_event_types() -> None:
    payload = CreateWebhookRequest(
        url="https://hooks.example.test/e", event_types=["NeedsReview:Finance", "PaymentDone"]
    )

    assert payload.event_types == ["NeedsReview:Finance", "PaymentDone"]


class _FakeSession:
    """Answers scalar() calls in order; stands in for the AsyncSession in route handlers."""

    def __init__(self, *answers: object) -> None:
        self.answers = list(answers)

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> _FakeSession:
        return self

    async def scalar(self, _statement: object) -> object:
        return self.answers.pop(0)

    async def execute(self, _statement: object) -> None:
        return None


def _request(session: _FakeSession) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(request_sessions=lambda: session))
    )


def _member() -> SimpleNamespace:
    return SimpleNamespace(organization_id=uuid.uuid4())


def test_disabling_an_already_disabled_endpoint_is_idempotent() -> None:
    session = _FakeSession(None, uuid.uuid4())  # nothing newly disabled, but the row exists

    response = asyncio.run(
        disable_endpoint(uuid.uuid4(), _request(session), _member())  # type: ignore[arg-type]
    )

    assert response.status_code == 204


def test_disabling_an_unknown_endpoint_is_404() -> None:
    session = _FakeSession(None, None)

    with pytest.raises(AuthFailure) as raised:
        asyncio.run(
            disable_endpoint(uuid.uuid4(), _request(session), _member())  # type: ignore[arg-type]
        )

    assert raised.value.status == 404


def test_creating_beyond_the_enabled_endpoint_cap_is_rejected() -> None:
    session = _FakeSession(MAX_ENABLED_ENDPOINTS)

    with pytest.raises(AuthFailure) as raised:
        asyncio.run(
            create_endpoint(
                CreateWebhookRequest(
                    url="https://hooks.example.test/e", event_types=["PaymentDone"]
                ),
                SimpleNamespace(
                    app=SimpleNamespace(
                        state=SimpleNamespace(
                            request_sessions=lambda: session,
                            webhook_cipher=SimpleNamespace(encrypt=lambda *_, **__: "x"),
                        )
                    )
                ),  # type: ignore[arg-type]
                _member(),  # type: ignore[arg-type]
            )
        )

    assert raised.value.status == 409
