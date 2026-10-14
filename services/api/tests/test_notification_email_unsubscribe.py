from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import SecretStr

from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.notifications.models import NotificationEmailPreference
from treasurypilot_api.notifications.routes import email_router
from treasurypilot_core.notifications import unsubscribe_signature

USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000123")
SECRET = "s" * 32


class _Session:
    def __init__(self) -> None:
        self.rows: dict[Any, Any] = {}

    async def get(self, model: type, key: uuid.UUID) -> Any:
        if model is NotificationEmailPreference:
            return self.rows.get(key)
        return SimpleNamespace(id=key)  # the User exists

    def add(self, row: NotificationEmailPreference) -> None:
        self.rows[row.user_id] = row

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


def _client(secret: str | None) -> tuple[TestClient, _Session]:
    app = FastAPI()
    session = _Session()
    app.state.request_sessions = lambda: session
    app.state.settings = SimpleNamespace(session_secret=SecretStr(secret) if secret else None)
    app.include_router(email_router)

    @app.exception_handler(AuthFailure)
    async def handler(_: Request, exc: AuthFailure) -> JSONResponse:
        return JSONResponse({"code": exc.code}, status_code=exc.status)

    return TestClient(app), session


def _unsubscribe(client: TestClient, signature: str) -> Any:
    return client.post(
        "/v1/me/notifications/email/unsubscribe",
        params={"user_id": str(USER_ID), "signature": signature},
    )


def test_valid_signature_turns_non_critical_email_off() -> None:
    client, session = _client(SECRET)

    response = _unsubscribe(client, unsubscribe_signature(USER_ID, SECRET))

    assert response.status_code == 204
    assert session.rows[USER_ID].delivery_mode == "off"


def test_wrong_signature_is_rejected() -> None:
    client, session = _client(SECRET)

    response = _unsubscribe(client, "0" * 64)

    assert response.status_code == 400
    assert response.json() == {"code": "INVALID_UNSUBSCRIBE_TOKEN"}
    assert not session.rows


def test_non_ascii_signature_is_a_400_not_a_server_error() -> None:
    client, _ = _client(SECRET)

    response = _unsubscribe(client, "sígnature-é")

    assert response.status_code == 400
    assert response.json() == {"code": "INVALID_UNSUBSCRIBE_TOKEN"}


@pytest.mark.parametrize("secret", [None, "too-short"])
def test_missing_or_short_secret_fails_closed_for_a_forged_dev_secret_link(
    secret: str | None,
) -> None:
    client, session = _client(secret)
    forged = unsubscribe_signature(USER_ID, "treasurypilot-local-development-only-session-secret")

    response = _unsubscribe(client, forged)

    assert response.status_code == 503
    assert not session.rows
