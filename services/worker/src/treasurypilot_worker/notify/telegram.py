"""Telegram Bot API adapter.

Delivery code depends on :class:`TelegramClient` only, so tests use
:class:`FakeTelegramClient` and never touch the network. The bot token lives in the
request URL path; errors raised here carry a status code or a fixed label, never the
URL, so the token cannot reach a log through an exception message.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Protocol

_API_BASE = "https://api.telegram.org"
_TIMEOUT_SECONDS = 5.0


class TelegramError(Exception):
    """Base class; messages never contain the bot token or the chat id."""


class TelegramBotBlocked(TelegramError):
    """The user blocked the bot or deleted the chat: mark the channel inactive."""


class TelegramTransientError(TelegramError):
    """Network failure, rate limit or Telegram outage: retry with backoff."""


class TelegramPermanentError(TelegramError):
    """The request was rejected and retrying cannot help."""


class TelegramClient(Protocol):
    async def send_message(self, chat_id: str, text: str) -> None:
        """Send plain text. No buttons or inline keyboards: nothing is actionable."""


class HttpTelegramClient:
    def __init__(self, token: str, *, timeout: float = _TIMEOUT_SECONDS) -> None:
        if not token:
            raise ValueError("a Telegram bot token is required")
        self._token = token
        self._timeout = timeout

    def __repr__(self) -> str:
        return "HttpTelegramClient(token=***)"

    async def send_message(self, chat_id: str, text: str) -> None:
        await asyncio.to_thread(self._send, chat_id, text)

    def _send(self, chat_id: str, text: str) -> None:
        body = json.dumps(
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        ).encode()
        request = urllib.request.Request(  # noqa: S310 - fixed https endpoint
            f"{_API_BASE}/bot{self._token}/sendMessage",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout):  # noqa: S310
                return
        except urllib.error.HTTPError as error:
            status = error.code
        except (urllib.error.URLError, TimeoutError, OSError):
            raise TelegramTransientError("telegram unreachable") from None
        if status == 403:
            raise TelegramBotBlocked("telegram refused: bot blocked or removed")
        if status == 429 or status >= 500:
            raise TelegramTransientError(f"telegram returned {status}")
        raise TelegramPermanentError(f"telegram returned {status}")
