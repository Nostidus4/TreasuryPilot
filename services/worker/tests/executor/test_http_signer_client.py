"""HttpSignerClient response mapping against a local aiohttp server (EXE-007)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from treasurypilot_worker.executor.outbox import (
    HttpSignerClient,
    SignerMisconfigured,
    SignerRefused,
    SignerUnavailable,
)


async def _call(status: int, body: Any, *, raw: bool = False) -> tuple[Any, dict[str, str]]:
    seen: dict[str, str] = {}

    async def handler(request: web.Request) -> web.Response:
        seen.update(request.headers)
        if raw:
            return web.Response(status=status, text=body)
        return web.json_response(body, status=status)

    app = web.Application()
    app.router.add_post("/sign-and-send", handler)
    async with TestServer(app) as server:
        client = HttpSignerClient(str(server.make_url("/")), "s3cret")
        return await client.sign_and_send({"a": 1}), seen


def _run(status: int, body: Any, *, raw: bool = False) -> Any:
    return asyncio.run(_call(status, body, raw=raw))


def test_200_returns_body_and_sends_secret_header() -> None:
    body, seen = _run(200, {"txHash": "0x01"})
    assert body == {"txHash": "0x01"} and seen["X-Signer-Secret"] == "s3cret"


def test_4xx_is_refusal_with_code() -> None:
    with pytest.raises(SignerRefused) as refused:
        _run(422, {"code": "PAYLOAD_MISMATCH"})
    assert refused.value.code == "PAYLOAD_MISMATCH" and refused.value.terminal


def test_401_is_misconfiguration_not_refusal() -> None:
    with pytest.raises(SignerMisconfigured):
        _run(401, {"code": "UNAUTHORIZED"})


def test_5xx_and_non_json_5xx_are_unavailable() -> None:
    with pytest.raises(SignerUnavailable):
        _run(503, {"code": "CHAIN_RPC_UNAVAILABLE"})
    with pytest.raises(SignerUnavailable):
        _run(502, "<html>bad gateway</html>", raw=True)


def test_non_json_4xx_is_generic_refusal() -> None:
    with pytest.raises(SignerRefused) as refused:
        _run(400, "nope", raw=True)
    assert refused.value.code == "SIGNER_ERROR" and not refused.value.terminal
