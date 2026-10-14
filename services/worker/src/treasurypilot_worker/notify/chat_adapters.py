"""Outbound Slack, Lark and WeCom webhook adapters.

Each adapter accepts only its provider's official incoming-webhook URL shape (the shared
allowlist lives in ``treasurypilot_core.notifications``), posts a plain text notification,
and reduces failures to fixed messages so the secret webhook URL cannot leak through logs
or exception chains.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import urllib.error
import urllib.request
from enum import StrEnum
from typing import Any, Protocol

from treasurypilot_core.notifications import canonical_chat_webhook_url

_TIMEOUT_SECONDS = 5.0


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_: Any, **__: Any) -> None:
        return None


def _open(request: urllib.request.Request, timeout: float) -> Any:
    # Provider-controlled redirects must not forward webhook credentials to another host.
    opener = urllib.request.build_opener(_NoRedirectHandler())
    return opener.open(request, timeout=timeout)


class ChatPlatform(StrEnum):
    SLACK = "SLACK"
    LARK = "LARK"
    WECOM = "WECOM"


class ChatDeliveryError(Exception):
    """Base failure with no destination URL or response body in its message."""


class ChatTransientError(ChatDeliveryError):
    """Network, throttling, or provider outage; retry with backoff."""


class ChatPermanentError(ChatDeliveryError):
    """Invalid payload or webhook; retrying the same request cannot help."""


class ChatWebhookClient(Protocol):
    async def send_message(self, webhook_url: str, text: str) -> None: ...


# Rate limits and busy signals that arrive as HTTP 200 with a non-zero body code.
_TRANSIENT_CODES: dict[ChatPlatform, frozenset[int]] = {
    ChatPlatform.LARK: frozenset({11232}),  # frequency limit
    ChatPlatform.WECOM: frozenset({-1, 45009, 45033}),  # system busy, rate limits
}


def _escape(platform: ChatPlatform, text: str) -> str:
    """Neutralise provider markup so notification data cannot mention or disguise links."""

    if platform is ChatPlatform.SLACK:
        # Slack control sequences (<!channel>, <url|label>) need only &, < and > escaped.
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if platform is ChatPlatform.LARK:
        # Lark text has no escape syntax; fullwidth brackets stop <at user_id="all"> mentions.
        return text.replace("<", "＜").replace(">", "＞")
    return text  # WeCom text messages carry no inline markup


def _payload(platform: ChatPlatform, text: str) -> dict[str, Any]:
    text = _escape(platform, text)
    if platform is ChatPlatform.SLACK:
        return {"text": text}
    if platform is ChatPlatform.LARK:
        return {"msg_type": "text", "content": {"text": text}}
    return {"msgtype": "text", "text": {"content": text}}


def _check_status(status: int) -> None:
    if status == 429 or status >= 500:
        raise ChatTransientError(f"chat provider returned {status}")
    if status >= 300:
        raise ChatPermanentError(f"chat provider returned {status}")


class HttpChatWebhookClient:
    """HTTP client for one chat platform's incoming webhook format."""

    def __init__(self, platform: ChatPlatform, *, timeout: float = _TIMEOUT_SECONDS) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.platform = platform
        self._timeout = timeout

    def __repr__(self) -> str:
        return f"HttpChatWebhookClient(platform={self.platform.value})"

    async def send_message(self, webhook_url: str, text: str) -> None:
        try:
            # Revalidate at send time as channels can be provisioned outside this API.
            canonical_chat_webhook_url(self.platform.value, webhook_url)
            await asyncio.to_thread(self._send, webhook_url, text)
        except ValueError:
            raise ChatPermanentError("invalid webhook URL") from None

    def _send(self, webhook_url: str, text: str) -> None:
        body = json.dumps(_payload(self.platform, text)).encode()
        request = urllib.request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with _open(request, timeout=self._timeout) as response:
                status, raw = response.status, response.read(4096)
        except urllib.error.HTTPError as error:
            status, raw = error.code, b""
            error.close()
        except http.client.InvalidURL:
            raise ChatPermanentError("invalid webhook URL") from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            raise ChatTransientError("chat provider unreachable") from None
        _check_status(status)
        try:
            result = json.loads(raw)
        except ValueError:
            # Slack accepts the literal response body "ok".
            if self.platform is ChatPlatform.SLACK and raw.strip() == b"ok":
                return
            raise ChatPermanentError("chat provider returned an invalid response") from None
        key = "code" if self.platform is ChatPlatform.LARK else "errcode"
        code = result.get(key) if isinstance(result, dict) else None
        if code == 0:
            return
        if isinstance(code, int) and code in _TRANSIENT_CODES.get(self.platform, ()):
            raise ChatTransientError("chat provider is busy or rate limiting")
        raise ChatPermanentError("chat provider rejected the message")
