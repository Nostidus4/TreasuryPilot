from __future__ import annotations

import pytest
from pydantic import ValidationError

from treasurypilot_api.notifications.webhook_api import CreateWebhookRequest


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
