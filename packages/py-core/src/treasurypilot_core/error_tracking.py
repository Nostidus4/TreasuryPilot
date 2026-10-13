"""Sentry error reporting and the Telegram alert hook (OBS-003), shared by api, worker and signer.

Sentry reads ``SENTRY_DSN`` and ``SENTRY_ENVIRONMENT`` itself; without a DSN nothing is sent.
The correlation ids arrive as tags through ``bind_context``.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.request
from typing import Any

import sentry_sdk
import structlog
from sentry_sdk.integrations.logging import LoggingIntegration

from treasurypilot_core.privacy import redact_event

_TELEGRAM_TIMEOUT_S = 5


def configure_error_tracking(service: str) -> None:
    def before_send(event: Any, _hint: Any) -> Any:
        event.setdefault("tags", {})["service"] = service
        # Same redaction as the logs; a failure collapses the event instead of leaking it.
        event = redact_event(None, "", event)
        if _is_unhandled(event):
            _alert_telegram(event)
        return event

    sentry_sdk.init(
        # Unhandled errors are captured by the FastAPI and Celery integrations. Log records
        # stay out: their message is the unredacted structlog event dict.
        integrations=[LoggingIntegration(level=None, event_level=None)],
        include_local_variables=False,  # locals can hold keys, tokens and invoice text
        before_send=before_send,
    )


def _is_unhandled(event: dict[str, Any]) -> bool:
    return any(
        value.get("mechanism", {}).get("handled") is False
        for value in event.get("exception", {}).get("values", [])
    )


def _alert_telegram(event: dict[str, Any]) -> None:
    token = os.environ.get("TP_TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TP_TELEGRAM_ALERT_CHAT_ID")
    if not token or not chat_id:
        return
    tags = event.get("tags", {})
    error_type = event["exception"]["values"][-1].get("type", "error")
    # Ids only: the exception message can carry business data.
    text = (
        f"[{tags.get('service')}] unhandled {error_type}\n"
        f"correlation_id: {tags.get('correlation_id', '-')}\n"
        f"sentry event: {event.get('event_id', '-')}"
    )
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": text}).encode(),
        headers={"Content-Type": "application/json"},
    )
    # Off the error path: a slow or down Telegram must not delay the request or task.
    threading.Thread(target=_send, args=(request,), daemon=True).start()


def _send(request: urllib.request.Request) -> None:
    try:
        urllib.request.urlopen(request, timeout=_TELEGRAM_TIMEOUT_S).close()  # noqa: S310
    except Exception as error:  # noqa: BLE001
        # The URL holds the bot token; log the error type only.
        structlog.get_logger().warning("telegram_alert_failed", error=type(error).__name__)


__all__ = ["configure_error_tracking"]
