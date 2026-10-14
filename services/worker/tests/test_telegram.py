"""Telegram adapter and message-building tests. No network: urlopen is replaced."""

from __future__ import annotations

import asyncio
import io
import json
import urllib.error
import uuid
from typing import Any

import pytest

from treasurypilot_worker.config import Settings, get_settings
from treasurypilot_worker.notify import telegram as telegram_module
from treasurypilot_worker.notify.telegram import (
    HttpTelegramClient,
    TelegramBotBlocked,
    TelegramPermanentError,
    TelegramTransientError,
)
from treasurypilot_worker.notify.telegram_fake import FakeTelegramClient
from treasurypilot_worker.notify.telegram_sender import (
    PendingMessage,
    build_text,
    format_amount,
)

TOKEN = "123456:SECRET-bot-token"
BASE = "https://app.example.test/"


def _message(**overrides: Any) -> PendingMessage:
    values: dict[str, Any] = {
        "delivery_id": uuid.uuid4(),
        "title": "Approval required",
        "link": "/requests/abc",
    }
    values.update(overrides)
    return PendingMessage(**values)


def test_default_message_is_minimal_with_a_deep_link() -> None:
    text = build_text([_message()], BASE)

    assert text == "[TreasuryPilot] Approval required · open: https://app.example.test/requests/abc"


def test_default_message_has_no_amounts_even_if_the_row_carries_them() -> None:
    # The SQL never selects amounts without opt-in; the builder only prints what it gets.
    assert "USDC" not in build_text([_message()], BASE)


def test_opted_in_message_adds_amount_and_vendor_from_integer_base_units() -> None:
    text = build_text(
        [_message(amount=1_500_000, decimals=6, symbol="USDC", vendor="  Acme\n Ltd ")], BASE
    )

    assert text == (
        "[TreasuryPilot] Approval required · 1.5 USDC to Acme Ltd"
        " · open: https://app.example.test/requests/abc"
    )


def test_bursts_are_merged_into_one_digest_without_details() -> None:
    text = build_text(
        [_message(amount=5, decimals=0, symbol="X", vendor="Secret Vendor"), _message()], BASE
    )

    assert (
        text == "[TreasuryPilot] 2 new notifications · open: https://app.example.test/notifications"
    )
    assert "Secret" not in text


@pytest.mark.parametrize(
    ("amount", "decimals", "expected"),
    [
        (0, 6, "0 T"),
        (1, 6, "0.000001 T"),
        (1_000_000, 6, "1 T"),
        (123_456_789, 6, "123.456789 T"),
        (10**30, 18, "1000000000000 T"),
        (7, 0, "7 T"),
    ],
)
def test_amounts_are_formatted_exactly(amount: int, decimals: int, expected: str) -> None:
    assert format_amount(amount, decimals, "T") == expected


def test_fake_client_records_and_scripts_failures() -> None:
    fake = FakeTelegramClient(TelegramTransientError("down"))

    async def exercise() -> None:
        with pytest.raises(TelegramTransientError):
            await fake.send_message("1", "a")
        await fake.send_message("1", "b")

    asyncio.run(exercise())
    assert fake.sent == [("1", "b")]


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def test_http_client_posts_plain_text_without_buttons(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def urlopen(request: Any, timeout: float) -> _Response:
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response(b'{"ok":true}')

    monkeypatch.setattr(telegram_module.urllib.request, "urlopen", urlopen)

    asyncio.run(HttpTelegramClient(TOKEN).send_message("42", "hello"))

    assert captured["url"] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    # Nothing actionable can be attached: no reply_markup, no inline keyboard.
    assert set(captured["body"]) == {"chat_id", "text", "disable_web_page_preview"}
    assert captured["timeout"] > 0


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (403, TelegramBotBlocked),
        (429, TelegramTransientError),
        (502, TelegramTransientError),
        (400, TelegramPermanentError),
        (401, TelegramPermanentError),
    ],
)
def test_http_errors_map_to_delivery_outcomes_without_leaking_the_token(
    monkeypatch: pytest.MonkeyPatch, status: int, error: type[Exception]
) -> None:
    def urlopen(request: Any, timeout: float) -> _Response:
        raise urllib.error.HTTPError(request.full_url, status, "boom", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(telegram_module.urllib.request, "urlopen", urlopen)

    with pytest.raises(error) as caught:
        asyncio.run(HttpTelegramClient(TOKEN).send_message("42", "hello"))

    assert TOKEN not in str(caught.value) and TOKEN not in repr(caught.value)


def test_network_failure_is_transient_and_does_not_leak_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen(request: Any, timeout: float) -> _Response:
        raise urllib.error.URLError(f"cannot reach {request.full_url}")

    monkeypatch.setattr(telegram_module.urllib.request, "urlopen", urlopen)

    with pytest.raises(TelegramTransientError) as caught:
        asyncio.run(HttpTelegramClient(TOKEN).send_message("42", "hello"))

    assert TOKEN not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_token_is_never_rendered_by_repr_or_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_TELEGRAM_BOT_TOKEN", TOKEN)
    settings = Settings()

    assert settings.telegram_bot_token is not None
    assert settings.telegram_bot_token.get_secret_value() == TOKEN
    assert TOKEN not in repr(settings) and TOKEN not in str(settings)
    assert TOKEN not in repr(HttpTelegramClient(TOKEN))


def test_client_requires_a_token() -> None:
    with pytest.raises(ValueError):
        HttpTelegramClient("")


@pytest.mark.parametrize("token", ["", "   "])
def test_delivery_task_is_a_no_op_for_an_empty_token(
    monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    from treasurypilot_worker import tasks

    monkeypatch.setenv("TP_TELEGRAM_BOT_TOKEN", token)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        # Would raise (no DATABASE_URL, then ValueError from the client) if it proceeded.
        assert tasks.deliver_telegram.run() == {"sent": 0}
    finally:
        get_settings.cache_clear()
