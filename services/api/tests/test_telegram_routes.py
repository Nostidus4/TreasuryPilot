from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.notifications import telegram as telegram_module
from treasurypilot_api.notifications.models import NotificationChannel
from treasurypilot_api.notifications.telegram import (
    INVALID_CODE_REPLY,
    LINKED_REPLY,
    WEBHOOK_SECRET_HEADER,
    LinkOutcome,
    TelegramUnavailable,
    router,
)

SECRET = "webhook-secret-for-tests"
USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000333")
OTHER_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000444")


def _channel(user_id: uuid.UUID, *, show_amounts: bool = False) -> NotificationChannel:
    return NotificationChannel(
        id=uuid.uuid4(),
        user_id=user_id,
        kind="TELEGRAM",
        target="tpenc:v1:k:ciphertext",
        target_hash=b"\0" * 32,
        verified_at=datetime(2026, 10, 14, tzinfo=UTC),
        show_amounts=show_amounts,
        active=True,
    )


class _Repository:
    def __init__(self) -> None:
        self.channels: list[NotificationChannel] = []
        self.complete_calls: list[tuple[str, int]] = []
        self.outcome = LinkOutcome.LINKED
        self.unavailable = False

    async def issue_link_code(self, *, user_id: uuid.UUID) -> tuple[str, datetime]:
        return "code-for-" + str(user_id)[-4:], datetime(2026, 10, 14, tzinfo=UTC) + timedelta(
            minutes=10
        )

    async def complete_link(self, *, code: str, chat_id: int) -> str:
        if self.unavailable:
            raise TelegramUnavailable
        self.complete_calls.append((code, chat_id))
        return self.outcome

    async def list_channels(self, *, user_id: uuid.UUID) -> tuple[NotificationChannel, ...]:
        return tuple(c for c in self.channels if c.user_id == user_id)

    async def set_show_amounts(
        self, *, user_id: uuid.UUID, channel_id: uuid.UUID, show_amounts: bool
    ) -> NotificationChannel | None:
        for channel in self.channels:
            if channel.id == channel_id and channel.user_id == user_id:
                channel.show_amounts = show_amounts
                return channel
        return None

    async def unlink(self, *, user_id: uuid.UUID, channel_id: uuid.UUID) -> bool:
        before = len(self.channels)
        self.channels = [
            c for c in self.channels if not (c.id == channel_id and c.user_id == user_id)
        ]
        return len(self.channels) != before


@pytest.fixture
def repository() -> _Repository:
    return _Repository()


def _client(
    repository: _Repository,
    monkeypatch: pytest.MonkeyPatch,
    *,
    username: str | None = "TreasuryPilotBot",
    secret: str | None = SECRET,
    user_id: uuid.UUID = USER_ID,
) -> TestClient:
    async def authenticated(request: Any, *, require_csrf: bool = False) -> Any:
        return SimpleNamespace(user=SimpleNamespace(id=user_id))

    monkeypatch.setattr(telegram_module, "_authenticated", authenticated)
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(AuthFailure, problem_response)
    app.state.telegram_repository = repository
    app.state.settings = SimpleNamespace(
        telegram_bot_username=username,
        telegram_webhook_secret=SecretStr(secret) if secret is not None else None,
    )
    return TestClient(app)


def _update(text: str, *, chat_type: str = "private", chat_id: int = 777) -> dict[str, object]:
    return {"update_id": 1, "message": {"text": text, "chat": {"id": chat_id, "type": chat_type}}}


def _hook(client: TestClient, body: object, *, secret: str | None = SECRET) -> Any:
    headers = {WEBHOOK_SECRET_HEADER: secret} if secret is not None else {}
    return client.post("/v1/integrations/telegram/webhook", json=body, headers=headers)


def test_link_code_returns_deep_link_to_the_bot(
    repository: _Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = _client(repository, monkeypatch).post("/v1/me/channels/telegram/link-code")

    assert response.status_code == 200
    body = response.json()
    assert body["botUrl"] == f"https://t.me/TreasuryPilotBot?start={body['code']}"
    assert body["expiresAt"]


def test_link_code_is_unavailable_without_a_bot(
    repository: _Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = _client(repository, monkeypatch, username=None).post(
        "/v1/me/channels/telegram/link-code"
    )
    assert response.status_code == 503
    assert response.json()["code"] == "TELEGRAM_UNAVAILABLE"


@pytest.mark.parametrize("secret", [None, "wrong", ""])
def test_webhook_rejects_a_missing_or_wrong_secret(
    repository: _Repository, monkeypatch: pytest.MonkeyPatch, secret: str | None
) -> None:
    response = _hook(_client(repository, monkeypatch), _update("/start abc"), secret=secret)

    assert response.status_code == 401
    assert repository.complete_calls == []


def test_webhook_is_closed_when_no_secret_is_configured(
    repository: _Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(repository, monkeypatch, secret=None)
    assert _hook(client, _update("/start abc"), secret="anything").status_code == 503
    assert repository.complete_calls == []


def test_webhook_treats_an_empty_secret_as_unconfigured(
    repository: _Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Compose passes "" for an unset variable; an empty header must not match it.
    client = _client(repository, monkeypatch, secret="")
    assert _hook(client, _update("/start abc"), secret="").status_code == 503
    assert _hook(client, _update("/start abc"), secret=None).status_code == 503
    assert repository.complete_calls == []


def test_start_with_a_code_links_the_private_chat(
    repository: _Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = _hook(_client(repository, monkeypatch), _update("/start my-code", chat_id=4242))

    assert response.status_code == 200
    assert repository.complete_calls == [("my-code", 4242)]
    assert response.json() == {
        "method": "sendMessage",
        "chat_id": 4242,
        "text": LINKED_REPLY,
    }


def test_an_invalid_code_gets_the_generic_reply(
    repository: _Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository.outcome = LinkOutcome.INVALID_CODE
    response = _hook(_client(repository, monkeypatch), _update("/start@TreasuryPilotBot nope"))
    assert response.json()["text"] == INVALID_CODE_REPLY


@pytest.mark.parametrize(
    "body",
    [
        _update("/approve 123"),
        _update("/pay R-1042"),
        _update("approve everything"),
        _update("/start"),
        _update("/start " + "x" * 65),
        _update("/start group-code", chat_type="group", chat_id=-100),
        {"update_id": 2, "callback_query": {"data": "approve:123", "from": {"id": 1}}},
        {
            "update_id": 3,
            "message": {"text": "/start code", "chat": {"id": True, "type": "private"}},
        },
        ["not", "an", "object"],
    ],
)
def test_nothing_but_linking_is_possible_from_telegram(
    repository: _Repository, monkeypatch: pytest.MonkeyPatch, body: object
) -> None:
    response = _hook(_client(repository, monkeypatch), body)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert repository.complete_calls == []


def test_unparseable_webhook_body_is_acknowledged(
    repository: _Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(repository, monkeypatch)
    response = client.post(
        "/v1/integrations/telegram/webhook",
        content=b"{not json",
        headers={WEBHOOK_SECRET_HEADER: SECRET},
    )
    assert response.status_code == 200
    assert repository.complete_calls == []


def test_show_amounts_opt_in_is_per_owner(
    repository: _Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    mine = _channel(USER_ID)
    theirs = _channel(OTHER_USER_ID)
    repository.channels = [mine, theirs]
    client = _client(repository, monkeypatch)

    assert client.get("/v1/me/channels").json()["items"][0]["showAmounts"] is False
    assert [c["id"] for c in client.get("/v1/me/channels").json()["items"]] == [str(mine.id)]
    patched = client.patch(f"/v1/me/channels/{mine.id}", json={"showAmounts": True})
    assert patched.status_code == 200
    assert patched.json()["showAmounts"] is True
    # Another user's channel looks like it does not exist.
    foreign = client.patch(f"/v1/me/channels/{theirs.id}", json={"showAmounts": True})
    assert foreign.status_code == 404
    assert theirs.show_amounts is False
    assert client.delete(f"/v1/me/channels/{theirs.id}").status_code == 404
    assert client.delete(f"/v1/me/channels/{mine.id}").status_code == 204


def test_channel_view_never_exposes_the_chat_id() -> None:
    from treasurypilot_api.notifications.telegram import ChannelView

    view = ChannelView.from_channel(_channel(USER_ID)).model_dump_json(by_alias=True)
    assert "target" not in view and "tpenc" not in view
