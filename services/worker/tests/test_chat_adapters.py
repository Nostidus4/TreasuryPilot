from __future__ import annotations

import asyncio
import http.client
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
        (ChatPlatform.SLACK, "https://hooks.slack.com:bad/services/x"),
    ],
)
def test_send_time_validation_failure_is_a_permanent_error(
    platform: ChatPlatform, url: str
) -> None:
    with pytest.raises(ChatPermanentError, match="invalid webhook URL") as caught:
        asyncio.run(HttpChatWebhookClient(platform).send_message(url, "hello"))
    assert caught.value.__cause__ is None


def test_invalid_url_from_http_client_is_a_permanent_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen(request: Any, timeout: float) -> None:
        raise http.client.InvalidURL("URL can't contain control characters")

    monkeypatch.setattr(module, "_open", urlopen)
    with pytest.raises(ChatPermanentError):
        asyncio.run(
            HttpChatWebhookClient(ChatPlatform.SLACK).send_message(
                URLS[ChatPlatform.SLACK], "hello"
            )
        )


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


class _Response(io.BytesIO):
    status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


@pytest.mark.parametrize(
    ("platform", "body", "error"),
    [
        (ChatPlatform.LARK, b'{"code":11232,"msg":"frequency limited"}', ChatTransientError),
        (ChatPlatform.LARK, b'{"code":19001,"msg":"bad"}', ChatPermanentError),
        (ChatPlatform.WECOM, b'{"errcode":45009,"errmsg":"freq"}', ChatTransientError),
        (ChatPlatform.WECOM, b'{"errcode":-1,"errmsg":"busy"}', ChatTransientError),
        (ChatPlatform.WECOM, b'{"errcode":45033,"errmsg":"concurrent"}', ChatTransientError),
        (ChatPlatform.WECOM, b'{"errcode":93000,"errmsg":"bad"}', ChatPermanentError),
        (ChatPlatform.WECOM, b'{"errcode":[1]}', ChatPermanentError),
        (ChatPlatform.SLACK, b"invalid_payload", ChatPermanentError),
    ],
)
def test_http_200_provider_codes_are_classified(
    monkeypatch: pytest.MonkeyPatch, platform: ChatPlatform, body: bytes, error: type[Exception]
) -> None:
    monkeypatch.setattr(module, "_open", lambda request, timeout: _Response(body))
    with pytest.raises(error):
        asyncio.run(HttpChatWebhookClient(platform).send_message(URLS[platform], "hello"))


def test_slack_ok_body_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_open", lambda request, timeout: _Response(b"ok"))
    asyncio.run(
        HttpChatWebhookClient(ChatPlatform.SLACK).send_message(URLS[ChatPlatform.SLACK], "hello")
    )


def test_http_error_response_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []

    class Error(urllib.error.HTTPError):
        def close(self) -> None:
            closed.append(True)

    def urlopen(request: Any, timeout: float) -> None:
        raise Error(request.full_url, 503, "x", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(module, "_open", urlopen)
    with pytest.raises(ChatTransientError):
        asyncio.run(
            HttpChatWebhookClient(ChatPlatform.SLACK).send_message(
                URLS[ChatPlatform.SLACK], "hello"
            )
        )
    assert closed == [True]


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        (ChatPlatform.SLACK, "&lt;!channel&gt; &lt;https://evil.test|Approve&gt; a &amp; b"),
        (ChatPlatform.LARK, "\uff1c!channel\uff1e \uff1chttps://evil.test|Approve\uff1e a & b"),
        (ChatPlatform.WECOM, "<!channel> <https://evil.test|Approve> a & b"),
    ],
)
def test_message_text_is_escaped_for_the_provider(platform: ChatPlatform, expected: str) -> None:
    payload = module._payload(platform, "<!channel> <https://evil.test|Approve> a & b")
    text = (
        payload["text"]
        if platform is ChatPlatform.SLACK
        else payload["content"]["text"]
        if platform is ChatPlatform.LARK
        else payload["text"]["content"]
    )
    assert text == expected
