from __future__ import annotations

import asyncio
import io
import json
import urllib.error
from typing import Any

import pytest

from treasurypilot_worker.notify import chat_adapters as module
from treasurypilot_worker.notify.chat_adapters import (
    ChatPermanentError,
    ChatPlatform,
    ChatTransientError,
    HttpChatWebhookClient,
    validate_webhook_url,
)

URLS = {
    ChatPlatform.SLACK: "https://hooks.slack.com/services/T000/B000/secret",
    ChatPlatform.LARK: "https://open.larksuite.com/open-apis/bot/v2/hook/secret",
    ChatPlatform.WECOM: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret",
}


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        (ChatPlatform.SLACK, {"text": "Approval required"}),
        (
            ChatPlatform.LARK,
            {"msg_type": "text", "content": {"text": "Approval required"}},
        ),
        (
            ChatPlatform.WECOM,
            {"msgtype": "text", "text": {"content": "Approval required"}},
        ),
    ],
)
def test_adapters_post_provider_text_payload(
    monkeypatch: pytest.MonkeyPatch, platform: ChatPlatform, expected: dict[str, Any]
) -> None:
    captured: dict[str, Any] = {}

    class Response(io.BytesIO):
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def urlopen(request: Any, timeout: float) -> Response:
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response(b'{"code":0,"errcode":0}')

    monkeypatch.setattr(module, "_open", urlopen)
    asyncio.run(HttpChatWebhookClient(platform).send_message(URLS[platform], "Approval required"))

    assert captured["url"] == URLS[platform]
    assert captured["body"] == expected
    assert captured["timeout"] > 0


@pytest.mark.parametrize(
    ("platform", "url"),
    [
        (ChatPlatform.SLACK, "https://example.com/hook"),
        (ChatPlatform.LARK, "https://127.0.0.1/open-apis/bot/v2/hook/x"),
        (ChatPlatform.WECOM, "http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x"),
        (ChatPlatform.WECOM, "https://qyapi.weixin.qq.com/redirect?key=x"),
    ],
)
def test_webhook_validation_rejects_non_provider_destinations(
    platform: ChatPlatform, url: str
) -> None:
    with pytest.raises(ValueError, match="invalid webhook URL"):
        validate_webhook_url(platform, url)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (302, ChatPermanentError),
        (429, ChatTransientError),
        (503, ChatTransientError),
        (400, ChatPermanentError),
    ],
)
def test_http_errors_do_not_include_webhook_secret(
    monkeypatch: pytest.MonkeyPatch, status: int, error: type[Exception]
) -> None:
    url = URLS[ChatPlatform.SLACK]

    def urlopen(request: Any, timeout: float) -> None:
        raise urllib.error.HTTPError(request.full_url, status, "secret", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(module, "_open", urlopen)
    with pytest.raises(error) as caught:
        asyncio.run(HttpChatWebhookClient(ChatPlatform.SLACK).send_message(url, "hello"))
    assert "secret" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_provider_rejection_is_a_fixed_error() -> None:
    class Response(io.BytesIO):
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def urlopen(request: Any, timeout: float) -> Response:
        return Response(b'{"errcode":40001,"errmsg":"secret"}')

    original = module._open
    module._open = urlopen
    try:
        with pytest.raises(ChatPermanentError) as caught:
            asyncio.run(
                HttpChatWebhookClient(ChatPlatform.WECOM).send_message(
                    URLS[ChatPlatform.WECOM], "hello"
                )
            )
        assert "secret" not in str(caught.value)
    finally:
        module._open = original
