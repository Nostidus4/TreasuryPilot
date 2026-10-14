"""Outbound Slack, Lark and WeCom webhook adapters.

Each adapter accepts only its provider's official incoming-webhook URL shape,
posts a plain text notification, and reduces failures to fixed messages so the
secret webhook URL cannot leak through logs or exception chains.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from enum import StrEnum
from typing import Any, Protocol

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


def validate_webhook_url(platform: ChatPlatform, value: str) -> str:
    """Validate destination before encrypting/storing it, to prevent SSRF."""

    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("invalid webhook URL")
    if parsed.port not in (None, 443) or parsed.fragment:
        raise ValueError("invalid webhook URL")
    host = parsed.hostname.casefold()
    path = parsed.path
    if platform is ChatPlatform.SLACK:
        valid = host == "hooks.slack.com" and path.startswith("/services/")
    elif platform is ChatPlatform.LARK:
        valid = host in {"open.larksuite.com", "open.feishu.cn"} and path.startswith(
            "/open-apis/bot/v2/hook/"
        )
    else:
        valid = host == "qyapi.weixin.qq.com" and path == "/cgi-bin/webhook/send"
    if not valid or len(value) > 2048:
        raise ValueError("invalid webhook URL")
    return value


def _payload(platform: ChatPlatform, text: str) -> dict[str, Any]:
    if platform is ChatPlatform.SLACK:
        return {"text": text}
    if platform is ChatPlatform.LARK:
        return {"msg_type": "text", "content": {"text": text}}
    return {"msgtype": "text", "text": {"content": text}}


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
        # Revalidate at send time as channels can be provisioned outside this API.
        validate_webhook_url(self.platform, webhook_url)
        await asyncio.to_thread(self._send, webhook_url, text)

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
                raw = response.read(4096)
        except urllib.error.HTTPError as error:
            status = error.code
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ChatTransientError("chat provider unreachable") from None
        else:
            if response.status == 429 or response.status >= 500:
                raise ChatTransientError(f"chat provider returned {response.status}")
            if response.status >= 400:
                raise ChatPermanentError(f"chat provider returned {response.status}")
            status = response.status
        if status == 429 or status >= 500:
            raise ChatTransientError(f"chat provider returned {status}")
        if status >= 300:
            raise ChatPermanentError(f"chat provider returned {status}")
        try:
            result = json.loads(raw)
        except ValueError:
            # Slack accepts the literal response body "ok".
            if self.platform is ChatPlatform.SLACK and raw.strip() == b"ok":
                return
            raise ChatPermanentError("chat provider returned an invalid response") from None
        if self.platform is ChatPlatform.LARK:
            code = result.get("code") if isinstance(result, dict) else None
            success = code == 0
        else:
            code = result.get("errcode") if isinstance(result, dict) else None
            success = code == 0
        if not success:
            raise ChatPermanentError("chat provider rejected the message")
