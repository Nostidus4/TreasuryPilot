"""http_sentinel maps the signer's answer onto a circuit_events.details.onchain value."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import aiohttp
import pytest

from treasurypilot_worker.recovery import circuit
from treasurypilot_worker.recovery.circuit import http_sentinel


class _Response:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status, self._body = status, body

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def json(self) -> dict[str, Any]:
        return self._body


def _session(response: _Response | Exception) -> type:
    class Session:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        def post(self, *_: object, **__: object) -> _Response:
            if isinstance(response, Exception):
                raise response
            return response

    return Session


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (_Response(200, {"alreadyPaused": False}), "SENTINEL_SUBMITTED"),
        (_Response(200, {"alreadyPaused": True}), "ALREADY_PAUSED"),
        (_Response(503, {}), "SENTINEL_FAILED"),
        (aiohttp.ClientConnectionError(), "SENTINEL_FAILED"),
    ],
)
def test_sentinel_answers(
    monkeypatch: pytest.MonkeyPatch, response: _Response | Exception, expected: str
) -> None:
    monkeypatch.setattr(circuit.aiohttp, "ClientSession", _session(response))
    assert asyncio.run(http_sentinel("http://signer", "s")(uuid.uuid4())) == expected


def test_unconfigured_sentinel_makes_no_call() -> None:
    assert asyncio.run(http_sentinel(None, "s")(uuid.uuid4())) == "NOT_CONFIGURED"
    assert asyncio.run(http_sentinel("http://signer", None)(uuid.uuid4())) == "NOT_CONFIGURED"
